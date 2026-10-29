"""Run: python server.py --port 8765. Python 3.11+, no dependencies."""
import argparse
import collections
import json
import mimetypes
import os
import sys
import tempfile
import time
import traceback
import threading
import uuid
import webbrowser
import urllib.request
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote, quote

from core import Invalid
from samples import SAMPLES
from store import Conflict, Store

ROOT = Path(__file__).resolve().parent
JSON_MIME = "application/json; charset=utf-8"


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can let two processes bind the same local port.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Metrics:
    """Bounded, thread-safe in-process counters for local observability."""

    def __init__(self, max_samples=1000):
        self.started = time.time()
        self.lock = threading.Lock()
        self.total = 0
        self.status_counts = {}
        self.error_counts = {}
        self.latencies = collections.deque(maxlen=max_samples)

    def record(self, status, duration_ms, error=None):
        with self.lock:
            self.total += 1
            self.status_counts[status] = self.status_counts.get(status, 0) + 1
            self.latencies.append(duration_ms)
            if error is not None:
                name = type(error).__name__
                self.error_counts[name] = self.error_counts.get(name, 0) + 1

    def snapshot(self, active_jobs=0):
        with self.lock:
            samples = sorted(self.latencies)
            def percentile(p):
                if not samples:
                    return None
                index = min(len(samples) - 1, max(0, int(round((p / 100) * (len(samples) - 1)))))
                return round(samples[index], 1)
            return {
                "uptime_seconds": round(time.time() - self.started, 1),
                "requests_total": self.total,
                "status_counts": dict(sorted(self.status_counts.items())),
                "error_counts": dict(sorted(self.error_counts.items())),
                "latency_ms": {
                    "samples": len(samples),
                    "p50": percentile(50),
                    "p95": percentile(95),
                    "p99": percentile(99),
                    "max": round(samples[-1], 1) if samples else None,
                },
                "active_ai_jobs": active_jobs,
            }


class Response:
    """A route handler's return value; the dispatcher serializes it exactly once."""

    def __init__(self, data, status=200, mime=JSON_MIME, filename=None):
        self.data = data
        self.status = status
        self.mime = mime
        self.filename = filename

    def body(self):
        if isinstance(self.data, bytes):
            return self.data
        return json.dumps(self.data, ensure_ascii=False).encode("utf-8")


class RequestContext:
    """Per-request state passed through security checks, routing and logging."""

    def __init__(self, handler, method, path, request_id):
        self.handler = handler
        self.method = method
        self.path = path
        self.request_id = request_id
        self.started = time.perf_counter()
        parsed = urlsplit(path)
        self.segments = [s for s in parsed.path.strip("/").split("/") if s]
        self.query = parse_qs(parsed.query)
        self._body = None

    @property
    def is_post(self):
        return self.method == "POST"

    def body(self):
        if self._body is None:
            content_type = self.handler.headers.get("Content-Type", "").split(";")[0]
            if content_type != "application/json":
                raise Invalid("需要JSON请求")
            size = int(self.handler.headers.get("Content-Length", "0"))
            if not 0 < size <= 500000:
                raise Invalid("请求体为空或过大")
            data = json.loads(self.handler.rfile.read(size))
            if not isinstance(data, dict):
                raise Invalid("请求应为JSON对象")
            self._body = data
        return self._body


class Router:
    """Explicit route registry with static segments and <dynamic> captures."""

    def __init__(self):
        self._routes = []

    def add(self, method, pattern, handler):
        segments = [s for s in pattern.strip("/").split("/") if s]
        self._routes.append((method, segments, handler))

    def get(self, pattern):
        def decorator(handler):
            self.add("GET", pattern, handler)
            return handler
        return decorator

    def post(self, pattern):
        def decorator(handler):
            self.add("POST", pattern, handler)
            return handler
        return decorator

    def dispatch(self, ctx):
        for method, segments, handler in self._routes:
            if method != ctx.method or len(segments) != len(ctx.segments):
                continue
            params = {}
            matched = True
            for pattern, actual in zip(segments, ctx.segments):
                if pattern.startswith("<") and pattern.endswith(">"):
                    params[pattern[1:-1]] = actual
                elif pattern != actual:
                    matched = False
                    break
            if matched:
                return handler(ctx, **params)
        return None


def make_handler(store, ai_service=None, metrics=None, log_level="normal", allowed_hosts=None):
    service_holder = [ai_service]
    service_lock = threading.Lock()
    web_holder = [None]
    web_lock = threading.Lock()
    proof_holder = [None]
    proof_lock = threading.Lock()
    metrics = metrics or Metrics()
    # None keeps the safe loopback-only default; "*" disables the Host check.
    allowed_hosts = None if allowed_hosts == "*" else set(allowed_hosts or ("127.0.0.1", "localhost", "::1"))

    def websites():
        with web_lock:
            if web_holder[0] is None:
                from webcraft.store import WebStore
                web_holder[0] = WebStore(Path(store.path).parent / "websites.sqlite3")
        return web_holder[0]

    def ai():
        with service_lock:
            if service_holder[0] is None:
                from ai.service import AIService
                service_holder[0] = AIService(store)
        return service_holder[0]

    def proof_store():
        with proof_lock:
            if proof_holder[0] is None:
                proof_holder[0] = Store(Path(store.path).parent / "proof.sqlite3")
        return proof_holder[0]

    router = Router()

    def static_file(name, mime=None):
        file = ROOT / "static" / name
        return Response(file.read_bytes(), mime=mime or (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8")

    def safe_static_asset(name):
        file = (ROOT / "static" / "assets" / unquote(name)).resolve()
        if file.parent != (ROOT / "static" / "assets").resolve() or file.suffix not in (".woff2", ".ttf", ".js", ".css") or not file.is_file():
            return Response({"error": "资源不存在"}, 404)
        return Response(file.read_bytes(), mime=mimetypes.guess_type(file.name)[0] or "application/octet-stream")

    def safe_export_file(name):
        folder = (Path(store.path).resolve().parent / "exports").resolve()
        file = (folder / unquote(name)).resolve()
        if file.parent != folder or file.suffix not in (".md", ".txt", ".zip") or not file.is_file():
            return Response({"error": "交付文件不存在"}, 404)
        return Response(file.read_bytes(), mime=mimetypes.guess_type(file.name)[0] or "application/octet-stream", filename=file.name)

    def experiment_file(folder, name, allowed, missing_message):
        if name not in allowed:
            return None
        file = ROOT / "experiments" / folder / name
        if file.is_file():
            return Response(file.read_bytes(), mime=(mimetypes.guess_type(file.name)[0] or "application/octet-stream") + "; charset=utf-8")
        return Response({"error": missing_message}, 404)

    # ---- Website artifact routes ----
    @router.get("/api/websites")
    def list_websites(ctx):
        return Response({"pages": websites().listing()})

    @router.post("/api/websites")
    def create_website(ctx):
        return Response(websites().create(ctx.body()), 201)

    @router.get("/api/websites/<pid>")
    def view_website(ctx, pid):
        return Response(websites().view(pid))

    @router.post("/api/websites/<pid>/preview")
    def preview_website(ctx, pid):
        return Response(websites().preview(pid, ctx.body()))

    @router.post("/api/websites/<pid>/preference")
    def preference_website(ctx, pid):
        return Response(websites().preference(pid, ctx.body()))

    @router.post("/api/websites/<pid>/action")
    def action_website(ctx, pid):
        body = ctx.body()
        if "job_id" in body:
            raise Invalid("模型作业的采用需使用作业接口")
        return Response(websites().action(pid, body))

    @router.post("/api/websites/<pid>/ai")
    def ai_website(ctx, pid):
        return Response(ai().submit("web_copy", {**ctx.body(), "site_id": pid}), 202)

    @router.post("/api/websites/<pid>/export")
    def export_website(ctx, pid):
        package = websites().export(pid, ctx.body())
        folder = Path(store.path).parent / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / ("tessera-website-" + uuid.uuid4().hex[:12] + ".zip")
        file.write_bytes(package)
        return Response({"path": str(file.resolve()), "url": "/api/files/" + file.name, "revision": ctx.body()["revision"]})

    @router.get("/web-studio")
    def web_studio(ctx):
        return static_file("web-studio.html")

    @router.get("/web-studio.js")
    def web_studio_js(ctx):
        return static_file("web-studio.js")

    @router.get("/web-studio.css")
    def web_studio_css(ctx):
        return static_file("web-studio.css")

    @router.get("/web-render.css")
    def web_render_css(ctx):
        return static_file("web-render.css")

    # ---- Engineering evidence: isolated proof sandbox ----
    @router.get("/api/proof/state")
    def proof_state(ctx):
        import proof
        return Response(proof.state_report(proof_store(), service_holder[0]))

    @router.post("/api/proof/action")
    def proof_action(ctx):
        import proof
        body = ctx.body()
        kind = body.get("kind")
        if kind not in ("lock", "unlock"):
            raise Invalid("沙盒只支持锁定或解锁")
        sandbox = proof_store()
        sid = proof.demo_session(sandbox)
        proof.toggle_lock(sandbox, sid, body.get("revision"), kind == "lock")
        return Response(proof.chain_report(sandbox, sid))

    @router.post("/api/proof/reset")
    def proof_reset(ctx):
        import proof
        sandbox = proof_store()
        return Response(proof.chain_report(sandbox, proof.new_demo_session(sandbox)), 201)

    @router.post("/api/proof/solve")
    def proof_solve(ctx):
        import proof
        body = ctx.body()
        return Response(proof.solver_report(lock=body.get("lock") is True,
                                            require_phrase=body.get("require_phrase") is True,
                                            max_chars=body.get("max_chars")))

    @router.post("/api/proof/splice")
    def proof_splice(ctx):
        import proof
        body = ctx.body()
        if body.get("mode") == "preview":
            return Response(proof.splice_preview(body.get("text"), body.get("query"), body.get("occurrence", 1)))
        if body.get("mode") == "apply":
            receipt = proof.apply_splice(body.get("text"), body.get("start"), body.get("end"), body.get("replacement"),
                                         body.get("prefix_hash"), body.get("suffix_hash"), body.get("selection_hash"))
            return Response(receipt)
        raise Invalid("请指定 preview 或 apply")

    # ---- AI configuration and generation ----
    @router.get("/api/ai/config")
    def get_ai_config(ctx):
        return Response(ai().settings.public())

    @router.post("/api/ai/config")
    def save_ai_config(ctx):
        return Response(ai().settings.save(ctx.body()))

    @router.get("/api/ai/draft")
    def get_ai_draft(ctx):
        return Response(ai().draft())

    @router.post("/api/ai/draft")
    def save_ai_draft(ctx):
        return Response(ai().draft(ctx.body()))

    @router.get("/api/guidance")
    def guidance(ctx):
        from ai.guidance import CATALOG, VERSION
        return Response({"version": VERSION, "catalog": CATALOG})

    @router.post("/api/guidance/preview")
    def guidance_preview(ctx):
        from ai.inspiration import prepare
        body = ctx.body()
        result = prepare(body.get("guidance"), body.get("materials", []))
        return Response({k: v for k, v in result.items() if k != "materials"})

    @router.post("/api/ai/inspire")
    def inspire(ctx):
        return Response(ai().submit("inspire", ctx.body()), 202)

    @router.post("/api/ai/connect")
    def connect(ctx):
        config = ai().settings.public()
        models = ai().provider.bound(config).models()
        if ai().settings.public() != config:
            raise Invalid("连接配置在另一窗口更新，请重新读取模型")
        current = config["model"]
        if not current or (config["provider"] == "siliconflow" and current not in models):
            preferred = ["Qwen/Qwen3-30B-A3B-Instruct-2507", "Qwen/Qwen3-8B", "Qwen/Qwen3-14B", "Qwen/Qwen2.5-7B-Instruct"]
            selected = next((m for m in preferred if m in models), models[0] if models else "")
            ai().settings.save({"model": selected})
        return Response({"models": models, "config": ai().settings.public()})

    @router.post("/api/ai/generate")
    def generate(ctx):
        return Response(ai().submit("generate", ctx.body()), 202)

    @router.get("/api/ai/jobs")
    def list_ai_jobs(ctx):
        sid = ctx.query.get("session", [None])[0]
        return Response({"jobs": ai().jobs(sid)})

    @router.get("/api/ai/jobs/<jid>")
    def get_ai_job(ctx, jid):
        return Response(ai().public_job(jid))

    @router.post("/api/ai/jobs/<jid>/cancel")
    def cancel_ai_job(ctx, jid):
        return Response(ai().cancel(jid))

    @router.post("/api/ai/jobs/<jid>/apply")
    def apply_ai_job(ctx, jid):
        return Response(ai().apply(jid, ctx.body()))

    @router.post("/api/ai/jobs/<jid>/retry")
    def retry_ai_job(ctx, jid):
        return Response(ai().retry(jid, ctx.body()), 202)

    # ---- Session-scoped AI operations ----
    @router.post("/api/sessions/<sid>/ai/revise")
    def revise(ctx, sid):
        return Response(ai().submit("revise", ctx.body(), sid), 202)

    @router.post("/api/sessions/<sid>/ai/repair")
    def repair(ctx, sid):
        return Response(ai().submit("repair", ctx.body(), sid), 202)

    @router.post("/api/sessions/<sid>/ai/local_revise")
    def local_revise(ctx, sid):
        return Response(ai().submit("local_revise", ctx.body(), sid), 202)

    @router.post("/api/sessions/<sid>/ai/export")
    def export_session(ctx, sid):
        body = ctx.body()
        return Response(ai().export(sid, body.get("revision"), body.get("format", "md")))

    @router.get("/api/sessions/<sid>/ai/history")
    def session_ai_history(ctx, sid):
        return Response({"jobs": ai().jobs(sid)})

    @router.get("/api/sessions/<sid>/ai/materials")
    def get_materials(ctx, sid):
        return Response(ai().materials(sid))

    @router.post("/api/sessions/<sid>/ai/materials")
    def update_materials(ctx, sid):
        return Response(ai().update_materials(sid, ctx.body()))

    @router.get("/api/sessions/<sid>/ai/draft")
    def get_session_draft(ctx, sid):
        return Response(ai().draft(sid=sid))

    @router.post("/api/sessions/<sid>/ai/draft")
    def save_session_draft(ctx, sid):
        return Response(ai().draft(ctx.body(), sid=sid))

    @router.get("/api/sessions/<sid>/ai/delivery")
    def session_delivery(ctx, sid):
        return Response(ai().delivery(sid))

    # ---- Core session routes ----
    @router.get("/api/health")
    def health(ctx):
        return Response({
            "app": "intent-workbench",
            "version": "product-v10",
            "capabilities": ["choice-board-v1", "semantic-learning-v1", "decision-analysis-v1", "compatible-models-v1", "configuration-space-v1", "guided-intent-v1", "preserved-fragments-v1", "contextual-inspiration-v1", "requirement-trace-v1", "semantic-trace-v1", "local-revision-v1", "proof-sandbox-v1"],
            "storage": str(Path(store.path).resolve().parent),
            "database": str(Path(store.path).resolve()),
        })

    @router.get("/api/metrics")
    def metrics_endpoint(ctx):
        active = 0
        if service_holder[0] is not None:
            active = service_holder[0].active_count()
        return Response(metrics.snapshot(active_jobs=active))

    @router.get("/api/files/<name>")
    def download_export(ctx, name):
        return safe_export_file(name)

    @router.get("/api/sessions")
    def list_sessions(ctx):
        return Response({"sessions": store.sessions(), "samples": [{"id": s["id"], "title": s["title"], "category": s.get("category", ""), "brief": s.get("brief", ""), "blocks": len(s.get("blocks", [])), "variants": len(s.get("blocks", [{}])[0].get("variants", [])) if s.get("blocks") else 0} for s in SAMPLES]})

    @router.post("/api/sessions")
    def create_session(ctx):
        body = ctx.body()
        if "clone" in body:
            task = store.audit(body["clone"])["task"]
        elif "sample" in body:
            task = next((s for s in SAMPLES if s["id"] == body["sample"]), None)
            if task is None:
                raise Invalid("示例不存在")
        else:
            task = body.get("task")
            if not isinstance(task, dict):
                raise Invalid("缺少任务")
            task = {**task, "source": "custom", "category": "自建任务"}
        return Response({"id": store.create(task)}, 201)

    @router.post("/api/sessions/<sid>/learning/train")
    def train_learning(ctx, sid):
        return Response(store.learning().submit(sid, ctx.body()), 202)

    @router.get("/api/learning/runs/<rid>")
    def get_learning_run(ctx, rid):
        return Response(store.learning().public(rid))

    @router.post("/api/learning/runs/<rid>/cancel")
    def cancel_learning_run(ctx, rid):
        return Response(store.learning().cancel(rid))

    @router.get("/api/sessions/<sid>")
    def view_session(ctx, sid):
        return Response(store.view(sid))

    @router.post("/api/sessions/<sid>/action")
    def session_action(ctx, sid):
        return Response(store.action(sid, ctx.body()))

    @router.post("/api/sessions/<sid>/offer")
    def session_offer(ctx, sid):
        return Response({"offer": store.offer(sid, ctx.body().get("revision"))})

    @router.post("/api/sessions/<sid>/options")
    def session_options(ctx, sid):
        return Response(store.options(sid, ctx.body()))

    @router.post("/api/sessions/<sid>/requirement-evidence")
    def requirement_evidence(ctx, sid):
        return Response(store.requirement_evidence(sid, ctx.body()))

    @router.post("/api/sessions/<sid>/decision")
    def session_decision(ctx, sid):
        body = ctx.body()
        library = ai().materials(sid)
        if library["revision"] != body.get("revision"):
            raise Conflict("素材与稿件版本已变化，请重新计算")
        return Response(store.decision(sid, body.get("revision"), library["materials"]))

    @router.get("/api/sessions/<sid>/learning")
    def session_learning(ctx, sid):
        return Response(store.learning().summary(sid))

    @router.get("/api/sessions/<sid>/audit")
    def session_audit(ctx, sid):
        return Response(store.audit(sid))

    # ---- Static assets and reports ----
    @router.get("/assets/<name>")
    def asset(ctx, name):
        return safe_static_asset(name)

    STATIC_PAGES = {
        "": "studio.html",
        "index.html": "studio.html",
        "workbench": "index.html",
        "studio": "studio.html",
        "studio.html": "studio.html",
        "swipe": "swipe.html",
        "swipe.html": "swipe.html",
        "swipe.js": "swipe.js",
        "swipe.css": "swipe.css",
        "chat": "chat.html",
        "chat.html": "chat.html",
        "chat.js": "chat.js",
        "chat.css": "chat.css",
        "proof": "proof.html",
        "proof.html": "proof.html",
        "proof.js": "proof.js",
        "proof.css": "proof.css",
        "studio.js": "studio.js",
        "choices.js": "choices.js",
        "learning.js": "learning.js",
        "decision.js": "decision.js",
        "configuration.js": "configuration.js",
        "canvas.js": "canvas.js",
        "canvas.css": "canvas.css",
        "journey.js": "journey.js",
        "journey.css": "journey.css",
        "context-trace.js": "context-trace.js",
        "context-trace.css": "context-trace.css",
        "focused.js": "focused.js",
        "focused.css": "focused.css",
        "connections.js": "connections.js",
        "studio.css": "studio.css",
        "design.css": "design.css",
        "refined.css": "refined.css",
        "icons.js": "icons.js",
        "app.js": "app.js",
        "style.css": "style.css",
        "favicon.svg": "favicon.svg",
    }

    def register_static_pages():
        for public_name, file_name in STATIC_PAGES.items():
            pattern = "/" + public_name if public_name else "/"
            def handler(ctx, file_name=file_name):
                return static_file(file_name)
            router.add("GET", pattern, handler)

    register_static_pages()

    @router.get("/experiments/<name>")
    def experiment_report(ctx, name):
        allowed = ("report.html", "report.css", "regret.png", "cost.png", "planning.png", "calibration.png")
        return experiment_file("latest", name, allowed, "尚未生成报告，请运行研究实验入口")

    @router.get("/experiments/content/<name>")
    def content_experiment_report(ctx, name):
        allowed = ("report.html", "report.css", "accuracy.png", "regret.png", "accuracy.svg", "regret.svg", "summary.json")
        return experiment_file("content-latest", name, allowed, "尚未生成内容偏好评价报告")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Deliberately do not log request content, task text, or user facts.
            pass

        def _send(self, ctx, response):
            data = response.body()
            self.send_response(response.status)
            self.send_header("Content-Type", response.mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Request-ID", ctx.request_id)
            if response.filename:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(response.filename, safe=""))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _log(self, ctx, status, error=None):
            duration_ms = (time.perf_counter() - ctx.started) * 1000
            metrics.record(status, duration_ms, error)
            if log_level == "quiet":
                return
            if log_level == "normal" and status < 400 and duration_ms < 1000:
                return
            line = f"[{ctx.request_id}] {ctx.method} {ctx.path} -> {status} ({duration_ms:.1f}ms)"
            if error:
                line += f" error={type(error).__name__}"
            print(line, file=sys.stderr, flush=True)

        def _error(self, ctx, status, message, error=None):
            self._log(ctx, status, error)
            self._send(ctx, Response({"error": message or "请求格式错误", "request_id": ctx.request_id}, status))

        def dispatch(self, post=False):
            request_id = uuid.uuid4().hex[:12]
            ctx = RequestContext(self, "POST" if post else "GET", self.path, request_id)
            try:
                host = urlsplit("http://" + self.headers.get("Host", "")).hostname
                if allowed_hosts is not None and host not in allowed_hosts:
                    return self._error(ctx, 403, "仅接受本机访问")
                if post:
                    origin = self.headers.get("Origin")
                    if origin and origin != "http://" + self.headers.get("Host"):
                        return self._error(ctx, 403, "拒绝跨站请求")
                response = router.dispatch(ctx)
                if response is None:
                    return self._error(ctx, 404, "未找到")
                self._log(ctx, response.status)
                self._send(ctx, response)
            except Conflict as exc:
                self._error(ctx, 409, str(exc), exc)
            except (Invalid, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                self._error(ctx, 400, str(exc), exc)
            except Exception as exc:
                traceback.print_exc()
                self._error(ctx, 500, "本地服务出错，请查看启动窗口", exc)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(True)

    def close_services():
        if service_holder[0]:
            service_holder[0].close()
        if store._learning_service:
            store._learning_service.close()

    Handler.close_ai = staticmethod(close_services)
    return Handler


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def main():
    parser = argparse.ArgumentParser(description="Tessera · 拾构")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TESSERA_PORT", "8765")))
    parser.add_argument("--host", default=os.environ.get("TESSERA_HOST", "127.0.0.1"))
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("TESSERA_DB", str(ROOT / "data" / "workbench.sqlite3"))))
    parser.add_argument("--log-level", choices=("quiet", "normal", "verbose"), default=os.environ.get("TESSERA_LOG_LEVEL", "normal"))
    parser.add_argument("--open", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--quick", action="store_true", help="临时数据目录 + 随机端口，适合快速试用")
    args = parser.parse_args()

    if args.quick:
        quick_base = Path(os.environ.get("TESSERA_QUICK_DIR", "D:/CodexWork/temp" if os.name == "nt" else tempfile.gettempdir()))
        quick_base.mkdir(parents=True, exist_ok=True)
        quick_root = Path(tempfile.mkdtemp(prefix="tessera-quick-", dir=quick_base))
        args.db = quick_root / "workbench.sqlite3"
        args.port = 0
        args.log_level = "quiet"
        print(f"快速模式：临时数据目录 {quick_root}（退出后保留，可手动删除）", flush=True)
    if args.open is None:
        args.open = _env_bool("TESSERA_OPEN") or args.quick

    loopback = {"127.0.0.1", "localhost", "::1"}
    allowed_hosts = None if args.host in loopback else "*"
    if allowed_hosts == "*":
        print(f"警告：绑定 {args.host} 且未启用鉴权，请仅在受信任网络中使用。", file=sys.stderr, flush=True)

    if args.open:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=2) as response:
                running = json.load(response)
            if running.get("app") == "intent-workbench" and running.get("database") == str(args.db.resolve()):
                webbrowser.open(f"http://127.0.0.1:{args.port}")
                print("工作室已在运行，已打开现有页面。", flush=True)
                return 0
        except (OSError, ValueError):
            pass
    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    try:
        handler = make_handler(store, log_level=args.log_level, allowed_hosts=allowed_hosts)
        server = LocalHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        if args.open and args.port:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=2) as response:
                    running = json.load(response)
                if running.get("app") == "intent-workbench" and running.get("database") == str(args.db.resolve()):
                    webbrowser.open(f"http://127.0.0.1:{args.port}")
                    print("工作室已在运行，已打开现有页面。", flush=True)
                    return 0
            except (OSError, ValueError):
                pass
        print(f"无法启动端口 {args.port}: {exc}\n可用 --port 8766 指定其他端口。", file=sys.stderr)
        return 1
    url = f"http://{args.host if args.host not in loopback else '127.0.0.1'}:{server.server_port}"
    print(f"Tessera · 拾构\nLocal: {url}\nData: {args.db.resolve()}\n按 Ctrl+C 停止。", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        handler.close_ai()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run: python server.py --port 8765. Python 3.11+, no dependencies."""
import argparse
import json
import mimetypes
import sys
import traceback
import threading
import webbrowser
import urllib.request
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs,unquote,quote

from core import Invalid
from samples import SAMPLES
from store import Conflict, Store

ROOT = Path(__file__).resolve().parent


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can let two processes bind the same local port.
    allow_reuse_address=sys.platform!='win32'

    def server_bind(self):
        if sys.platform=='win32':self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def make_handler(store, ai_service=None):
    service_holder=[ai_service]
    service_lock=threading.Lock()
    def ai():
        with service_lock:
            if service_holder[0] is None:
                from ai.service import AIService
                service_holder[0]=AIService(store)
        return service_holder[0]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Deliberately do not log request content, task text, or user facts.
            pass

        def respond(self, value, status=200, mime="application/json; charset=utf-8",filename=None):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            if filename:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename,safe=''))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, post=False):
            try:
                host = urlsplit("http://" + self.headers.get("Host", "")).hostname
                if host not in ("127.0.0.1", "localhost", "::1"):
                    self.respond({"error": "仅接受本机访问"}, 403)
                    return
                parts = urlsplit(self.path).path.strip("/").split("/")
                if post:
                    origin = self.headers.get("Origin")
                    if origin and origin != "http://" + self.headers.get("Host"):
                        self.respond({"error": "拒绝跨站请求"}, 403)
                        return
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise Invalid("需要JSON请求")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 500000:
                        raise Invalid("请求体为空或过大")
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise Invalid("请求应为JSON对象")
                if parts==["api","ai","config"]:
                    self.respond(ai().settings.save(body) if post else ai().settings.public())
                    return
                if parts==['api','ai','draft']:
                    self.respond(ai().draft(body if post else None));return
                if parts==['api','guidance'] and not post:
                    from ai.guidance import CATALOG, VERSION
                    self.respond({'version':VERSION,'catalog':CATALOG});return
                if parts==['api','guidance','preview'] and post:
                    from ai.inspiration import prepare
                    result=prepare(body.get('guidance'),body.get('materials',[]))
                    self.respond({k:v for k,v in result.items() if k!='materials'});return
                if parts==['api','ai','inspire'] and post:
                    self.respond(ai().submit('inspire',body),202);return
                if parts==['api','health'] and not post:
                    self.respond({'app':'intent-workbench','version':'product-v10','capabilities':['choice-board-v1','semantic-learning-v1','decision-analysis-v1','compatible-models-v1','configuration-space-v1','guided-intent-v1','preserved-fragments-v1','contextual-inspiration-v1','requirement-trace-v1','semantic-trace-v1'],'storage':str(Path(store.path).resolve().parent),'database':str(Path(store.path).resolve())});return
                if len(parts)==3 and parts[:2]==['api','files'] and not post:
                    name=unquote(parts[2]);folder=(Path(store.path).resolve().parent/'exports').resolve();file=(folder/name).resolve()
                    if file.parent!=folder or file.suffix not in ('.md','.txt','.zip') or not file.is_file():self.respond({'error':'交付文件不存在'},404);return
                    self.respond(file.read_bytes(),mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream',filename=file.name);return
                if parts==["api","ai","connect"] and post:
                    config=ai().settings.public()
                    models=ai().provider.bound(config).models()
                    if ai().settings.public()!=config:raise Invalid('连接配置在另一窗口更新，请重新读取模型')
                    current=config["model"]
                    if not current or (config['provider']=='siliconflow' and current not in models):
                        preferred=["Qwen/Qwen3-30B-A3B-Instruct-2507","Qwen/Qwen3-8B","Qwen/Qwen3-14B","Qwen/Qwen2.5-7B-Instruct"]
                        selected=next((m for m in preferred if m in models),models[0] if models else "")
                        ai().settings.save({"model":selected})
                    self.respond({"models":models,"config":ai().settings.public()})
                    return
                if parts==["api","ai","generate"] and post:
                    self.respond(ai().submit("generate",body),202)
                    return
                if parts==["api","ai","jobs"] and not post:
                    sid=parse_qs(urlsplit(self.path).query).get("session",[None])[0]
                    self.respond({"jobs":ai().jobs(sid)})
                    return
                if len(parts) in (4,5) and parts[:3]==["api","ai","jobs"]:
                    jid=parts[3]
                    if len(parts)==4 and not post:self.respond(ai().public_job(jid));return
                    if len(parts)==5 and parts[4]=="cancel" and post:self.respond(ai().cancel(jid));return
                    if len(parts)==5 and parts[4]=="apply" and post:self.respond(ai().apply(jid,body));return
                    if len(parts)==5 and parts[4]=='retry' and post:self.respond(ai().retry(jid,body),202);return
                if len(parts)==5 and parts[:2]==["api","sessions"] and parts[3]=="ai":
                    sid,operation=parts[2],parts[4]
                    if operation in ('revise','repair') and post:self.respond(ai().submit(operation,body,sid),202);return
                    if operation=="export" and post:self.respond(ai().export(sid,body.get("revision"),body.get("format","md")));return
                    if operation=="history" and not post:self.respond({"jobs":ai().jobs(sid)});return
                    if operation=='materials':self.respond(ai().update_materials(sid,body) if post else ai().materials(sid));return
                    if operation=='draft':self.respond(ai().draft(body if post else None,sid=sid));return
                    if operation=='delivery' and not post:
                        self.respond(ai().delivery(sid));return
                if parts == ["api", "sessions"]:
                    if post:
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
                        self.respond({"id": store.create(task)}, 201)
                    else:
                        self.respond({"sessions": store.sessions(), "samples": [{"id": s["id"], "title": s["title"]} for s in SAMPLES]})
                    return
                if len(parts)==5 and parts[:2]==['api','sessions'] and parts[3:]==['learning','train'] and post:
                    self.respond(store.learning().submit(parts[2],body),202);return
                if len(parts) in (4,5) and parts[:3]==['api','learning','runs']:
                    if len(parts)==4 and not post:self.respond(store.learning().public(parts[3]));return
                    if len(parts)==5 and parts[4]=='cancel' and post:self.respond(store.learning().cancel(parts[3]));return
                if len(parts) in (3, 4) and parts[:2] == ["api", "sessions"]:
                    sid = parts[2]
                    if len(parts) == 3 and not post:
                        self.respond(store.view(sid))
                        return
                    if len(parts) == 4:
                        if parts[3] == "action" and post:
                            self.respond(store.action(sid, body))
                            return
                        if parts[3] == "offer" and post:
                            self.respond({"offer": store.offer(sid, body.get("revision"))})
                            return
                        if parts[3]=='options' and post:
                            self.respond(store.options(sid,body));return
                        if parts[3]=='requirement-evidence' and post:
                            self.respond(store.requirement_evidence(sid,body));return
                        if parts[3]=='decision' and post:
                            library=ai().materials(sid)
                            if library['revision']!=body.get('revision'):raise Conflict('素材与稿件版本已变化，请重新计算')
                            self.respond(store.decision(sid,body.get('revision'),library['materials']));return
                        if parts[3]=='learning' and not post:
                            self.respond(store.learning().summary(sid));return
                        if parts[3] == "audit" and not post:
                            self.respond(store.audit(sid))
                            return
                if not post and len(parts)==2 and parts[0]=='assets':
                    file=(ROOT/'static'/'assets'/unquote(parts[1])).resolve()
                    if file.parent!=(ROOT/'static'/'assets').resolve() or file.suffix not in ('.woff2','.ttf','.js','.css') or not file.is_file():self.respond({'error':'资源不存在'},404);return
                    self.respond(file.read_bytes(),mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream');return
                if not post and parts in ([""], ["index.html"], ["workbench"], ["studio.html"], ["studio.js"], ["choices.js"], ["learning.js"], ["decision.js"], ["configuration.js"], ["canvas.js"], ["canvas.css"], ["journey.js"], ["journey.css"], ["context-trace.js"], ["context-trace.css"], ["connections.js"], ["studio.css"], ["design.css"], ["refined.css"], ["icons.js"], ["app.js"], ["style.css"], ["favicon.svg"]):
                    name = "studio.html" if parts in ([""],["index.html"]) else "index.html" if parts==["workbench"] else parts[0]
                    self.respond((ROOT / "static" / name).read_bytes(), mime=(mimetypes.guess_type(name)[0] or "text/plain") + "; charset=utf-8")
                    return
                if not post and len(parts) == 2 and parts[0] == "experiments" and parts[1] in ("report.html", "report.css", "regret.png", "cost.png", "planning.png", "calibration.png"):
                    file = ROOT / "experiments" / "latest" / parts[1]
                    if file.is_file():
                        self.respond(file.read_bytes(), mime=(mimetypes.guess_type(file.name)[0] or "application/octet-stream"))
                    else:
                        self.respond({"error": "尚未生成报告，请运行研究实验入口"}, 404)
                    return
                if not post and len(parts)==3 and parts[:2]==["experiments","content"] and parts[2] in ("report.html","report.css","accuracy.png","regret.png","accuracy.svg","regret.svg","summary.json"):
                    file=ROOT/"experiments"/"content-latest"/parts[2]
                    if file.is_file():self.respond(file.read_bytes(),mime=(mimetypes.guess_type(file.name)[0] or "application/octet-stream")+"; charset=utf-8")
                    else:self.respond({"error":"尚未生成内容偏好评价报告"},404)
                    return
                self.respond({"error": "未找到"}, 404)
            except Conflict as exc:
                self.respond({"error": str(exc)}, 409)
            except (Invalid, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                self.respond({"error": str(exc) or "请求格式错误"}, 400)
            except Exception:
                traceback.print_exc()
                self.respond({"error": "本地服务出错，请查看启动窗口"}, 500)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(True)

    def close_services():
        if service_holder[0]:service_holder[0].close()
        if store._learning_service:store._learning_service.close()
    Handler.close_ai=staticmethod(close_services)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Tessera · 拾构")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "workbench.sqlite3")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if args.open:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=2) as response:running=json.load(response)
            if running.get('app')=='intent-workbench' and running.get('database')==str(args.db.resolve()):
                webbrowser.open(f'http://127.0.0.1:{args.port}')
                print('工作室已在运行，已打开现有页面。',flush=True)
                return 0
        except (OSError,ValueError):pass
    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    try:
        handler=make_handler(store)
        server = LocalHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as exc:
        if args.open:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=2) as response:running=json.load(response)
                if running.get('app')=='intent-workbench' and running.get('database')==str(args.db.resolve()):
                    webbrowser.open(f'http://127.0.0.1:{args.port}')
                    print('工作室已在运行，已打开现有页面。',flush=True)
                    return 0
            except (OSError,ValueError):pass
        print(f"无法启动端口 {args.port}: {exc}\n可用 --port 8766 指定其他端口。", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
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

"""Chat Completions adapters and endpoint-scoped encrypted credentials."""
import base64
import ctypes
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

from core import Invalid

BASE_URL = "https://api.siliconflow.cn/v1"


class ProviderError(Invalid):
    pass


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect_secret(value, decrypt=False):
    if os.name != "nt":
        raise ProviderError("此平台请使用服务对应的Key环境变量；自定义接口需同时设置 INTENT_MODEL_BASE_URL，不支持明文保存Key")
    raw = base64.b64decode(value) if decrypt else value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ProviderError("本地凭证加密/解密失败，请在设置中重新输入")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


class Settings:
    def __init__(self, folder):
        self.path = Path(folder) / "siliconflow.json"
        self.lock = threading.RLock()

    def raw(self):
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"provider": "siliconflow", "model": "", "preferences": "表达具体、步骤可执行；明确假设和验收方式。"}

    def profile(self, endpoint, raw=None):
        raw = self.raw() if raw is None else raw
        # Old installations retain the original encrypted SiliconFlow credential.
        legacy = {k: raw[k] for k in ('model', 'key_dpapi') if k in raw} if endpoint == BASE_URL else {}
        return {**legacy, **raw.get('profiles', {}).get(endpoint, {})}

    def read(self):
        raw = self.raw(); endpoint = normalize_endpoint(raw.get('active_endpoint', BASE_URL))
        data = self.profile(endpoint, raw)
        return {**data, 'provider': 'siliconflow' if endpoint == BASE_URL else 'compatible', 'base_url': endpoint,
                'preferences': raw.get('preferences', ''), 'stream': data.get('stream', True),
                'json_mode': data.get('json_mode', endpoint == BASE_URL),
                'token_parameter': data.get('token_parameter', 'max_tokens'), 'send_temperature': data.get('send_temperature', True)}

    def environment_key(self, endpoint):
        if endpoint == BASE_URL: return os.environ.get('INTENT_SILICONFLOW_API_KEY', '').strip()
        # A generic environment credential is usable only for its explicit endpoint.
        try: configured = normalize_endpoint(os.environ.get('INTENT_MODEL_BASE_URL', ''))
        except Invalid: return ''
        return os.environ.get('INTENT_MODEL_API_KEY', '').strip() if configured == endpoint else ''

    def key_for(self, endpoint):
        endpoint = normalize_endpoint(endpoint); env = self.environment_key(endpoint)
        if env: return env
        data = self.profile(endpoint)
        return protect_secret(data["key_dpapi"], decrypt=True) if data.get("key_dpapi") else ""

    def key(self):
        return self.key_for(self.read()['base_url'])

    def public(self):
        data = self.read()
        endpoint = data['base_url']; env = self.environment_key(endpoint)
        configured = bool(env or data.get('key_dpapi')); local = local_endpoint(endpoint)
        raw = self.raw(); endpoints = sorted(set(raw.get('profiles', {})) | {BASE_URL, endpoint})
        profiles = []
        for url in endpoints:
            p = self.profile(url, raw)
            profiles.append({'base_url': url, 'model': p.get('model', ''), 'key_configured': bool(self.environment_key(url) or p.get('key_dpapi')),
                             'stream': p.get('stream', True), 'json_mode': p.get('json_mode', url == BASE_URL),
                             'token_parameter': p.get('token_parameter', 'max_tokens'), 'send_temperature': p.get('send_temperature', True)})
        return {k: data[k] for k in ('provider', 'base_url', 'stream', 'json_mode', 'token_parameter', 'send_temperature', 'preferences')} | {
                'model': data.get('model', ''), 'key_configured': configured, 'ready': bool(data.get('model')) and (configured or local),
                'local_endpoint': local, 'key_required': not local, 'profiles': profiles,
                'key_storage': 'environment' if env else 'Windows DPAPI' if data.get('key_dpapi') else 'none'}

    def snapshot(self):
        data = self.public()
        return {k: data[k] for k in ('provider', 'base_url', 'model', 'stream', 'json_mode', 'token_parameter', 'send_temperature')}

    def save(self, body):
        with self.lock:
            raw = self.raw(); endpoint = normalize_endpoint(body.get('base_url', raw.get('active_endpoint', BASE_URL)))
            data = self.profile(endpoint, raw)
            if "api_key" in body and body["api_key"]:
                key = body["api_key"]
                if not isinstance(key, str) or not (12 if endpoint == BASE_URL else 1) <= len(key.strip()) <= 500 or any(c.isspace() for c in key.strip()):
                    raise ProviderError("API Key格式不正确")
                data["key_dpapi"] = protect_secret(key.strip())
            if body.get("clear_key"):
                data.pop("key_dpapi", None)
            if "model" in body:
                model = body["model"]
                if not isinstance(model, str) or len(model) > 150 or (model and not re.fullmatch(r"[A-Za-z0-9_./:+-]+", model)):
                    raise ProviderError("模型名格式不正确")
                data["model"] = model
            for field in ('stream', 'json_mode', 'send_temperature'):
                if field in body:
                    if type(body[field]) is not bool: raise ProviderError('模型兼容选项格式无效')
                    data[field] = body[field]
            if 'token_parameter' in body:
                if body['token_parameter'] not in ('max_tokens', 'max_completion_tokens'): raise ProviderError('输出上限参数无效')
                data['token_parameter'] = body['token_parameter']
            if "preferences" in body:
                if not isinstance(body["preferences"], str) or len(body["preferences"]) > 2000:
                    raise ProviderError("个人偏好请控制在2000字内")
                raw["preferences"] = body["preferences"]
            raw.setdefault('profiles', {})[endpoint] = data
            raw['active_endpoint'] = endpoint
            # Clearing the legacy endpoint must also remove its legacy credential.
            if endpoint == BASE_URL and body.get('clear_key'): raw.pop('key_dpapi', None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
            return self.public()


def normalize_endpoint(value):
    if not isinstance(value, str) or not value or len(value) > 500 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ProviderError('请填写完整的兼容接口地址，例如 https://服务地址/v1')
    try:
        parsed = urlsplit(value); port = parsed.port
        host = parsed.hostname
    except ValueError:
        raise ProviderError('接口地址格式无效') from None
    if not host or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or '\\' in value:
        raise ProviderError('接口地址不可包含账号、密码、查询参数或片段')
    if parsed.scheme not in ('https', 'http') or (parsed.scheme == 'http' and host.lower() not in ('localhost', '127.0.0.1', '::1')):
        raise ProviderError('远程服务请使用HTTPS；本机服务可使用HTTP')
    path = parsed.path.rstrip('/')
    if path.endswith(('/chat/completions', '/models')): raise ProviderError('请填写基础地址，去掉 /chat/completions 或 /models')
    authority = '['+host.lower()+']' if ':' in host else host.lower()
    if port is not None and port != (443 if parsed.scheme == 'https' else 80): authority += ':'+str(port)
    return urlunsplit((parsed.scheme, authority, path, '', ''))


def local_endpoint(endpoint):
    return urlsplit(endpoint).hostname in ('localhost', '127.0.0.1', '::1')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a credential to a redirected hostname.
        return None


class SiliconFlow:
    # Kept as an import-compatible name for existing integrations and evidence.
    def __init__(self, settings, transport=None, connection=None):
        self.settings, self.transport, self.connection = settings, transport, connection

    def bound(self, connection):
        return SiliconFlow(self.settings, self.transport, dict(connection))

    def request(self, path, payload=None, on_progress=None):
        config = self.connection or self.settings.public()
        endpoint = normalize_endpoint(config.get('base_url', BASE_URL))
        key = self.settings.key_for(endpoint) if hasattr(self.settings, 'key_for') else self.settings.key()
        if not key and not local_endpoint(endpoint):
            raise ProviderError("请在AI设置中为当前接口填写API Key；切换服务不会借用其他服务的Key")
        if self.transport:
            return self.transport(path, payload)
        headers = {"Content-Type": "application/json", "User-Agent": "IntentWorkbench/10"}
        if key: headers['Authorization'] = 'Bearer '+key
        request = urllib.request.Request(endpoint + path,
                                         data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
                                         headers=headers)
        started = time.perf_counter()
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=110) as response:
                if payload and payload.get("stream") and "text/event-stream" in response.headers.get("Content-Type", ""):
                    content=[];usage={};finish=None;done=False;total=0;last_progress=0
                    for line in response:
                        if time.perf_counter()-started>300:raise ProviderError("生成超过5分钟，已停止；请缩小任务范围或更换更快模型")
                        total+=len(line)
                        if total>2_000_000:raise ProviderError("模型流式输出过大，已停止")
                        if not line.startswith(b"data:"):continue
                        data=line[5:].strip()
                        if data==b"[DONE]":done=True;break
                        if not data:continue
                        chunk=json.loads(data)
                        if chunk.get("usage"):usage=chunk["usage"]
                        for choice in chunk.get("choices",[]):
                            piece=choice.get("delta",{}).get("content")
                            if isinstance(piece,str):content.append(piece)
                            if choice.get("finish_reason"):finish=choice["finish_reason"]
                        current=time.perf_counter()
                        if on_progress and current-last_progress>.8:
                            on_progress(sum(map(len,content)));last_progress=current
                    if not done and finish is None:raise ProviderError("流式连接提前结束，未采用不完整结果")
                    return {"choices":[{"message":{"content":"".join(content)},"finish_reason":finish or "stop"}],"usage":usage,
                            "_trace_id":response.headers.get("x-siliconcloud-trace-id"),"_latency_ms":round((time.perf_counter()-started)*1000)}
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProviderError("模型响应过大，已停止读取")
                result = json.loads(raw)
                result["_trace_id"] = response.headers.get("x-siliconcloud-trace-id")
                result["_latency_ms"] = round((time.perf_counter() - started) * 1000)
                return result
        except urllib.error.HTTPError as exc:
            messages = {400: "模型不接受当前生成参数，请换模型或稍后重试", 401: "API Key无效或已撤销，请更换后测试连接", 402: "账户余额不足", 403: "账户或模型没有访问权限", 404: "模型不存在或已下线，请刷新模型列表", 429: "服务商限流，请稍后重试", 500: "模型服务暂时出错", 503: "模型服务繁忙，请稍后重试"}
            # Do not echo arbitrary provider response bodies or request headers.
            raise ProviderError(messages.get(exc.code, f"模型服务请求失败（HTTP {exc.code}）")) from None
        except (socket.timeout, TimeoutError):
            raise ProviderError("模型请求超时；当前内容未改动，可稍后重试") from None
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            raise ProviderError("无法连接所选模型服务，或响应格式异常；请检查接口与兼容选项") from None

    def models(self):
        config = self.connection or self.settings.public()
        result = self.request("/models?sub_type=chat" if config.get('provider') == 'siliconflow' else '/models')
        if not isinstance(result, dict) or not isinstance(result.get('data'), list): raise ProviderError('接口没有返回兼容的模型列表，可手动填写模型名并仅保存')
        return sorted({r["id"] for r in result.get("data", []) if isinstance(r, dict) and isinstance(r.get("id"), str)})

    def json(self, messages, max_tokens=4096, model=None, on_progress=None, on_response=None):
        config = self.connection or self.settings.public()
        model = model or config.get("model")
        if not model:
            raise ProviderError("请在AI设置中选一个可用模型")
        payload = {"model": model, "messages": messages, "stream": config.get('stream', True),
                   config.get('token_parameter', 'max_tokens'): max_tokens}
        if config.get('send_temperature', True): payload['temperature'] = 0.6
        if config.get('json_mode', True): payload['response_format'] = {"type": "json_object"}
        if config.get('provider') == 'siliconflow' and "qwen3" in model.lower():
            payload["enable_thinking"] = False
        result = self.request("/chat/completions", payload, on_progress=on_progress)
        if on_response:on_response({k:result[k] for k in ('choices','usage') if k in result})
        try:
            choice = result["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ProviderError("输出达到长度上限，未采用不完整内容；可缩小任务范围后重试")
            content = choice["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError()
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError("模型没有返回有效的结构化结果，现有内容保持不变") from None
        return value, {"provider": config.get('provider', 'compatible'), "base_url": config.get('base_url', BASE_URL), "model": model, "usage": result.get("usage", {}),
                       "trace_id": result.get("_trace_id"), "latency_ms": result.get("_latency_ms")}

import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ai.provider import BASE_URL, ProviderError, Settings, SiliconFlow, normalize_endpoint
from ai.service import AIService
from store import Store
from ai_fixture import fixture_transport


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        root = Path('D:/CodexWork/temp/intent-connections-tests');root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.settings = Settings(Path(self.temp.name)/'private')
        self.env = patch.dict(os.environ, {'INTENT_SILICONFLOW_API_KEY': '', 'INTENT_MODEL_API_KEY': '', 'INTENT_MODEL_BASE_URL': ''})
        self.env.start();self.addCleanup(self.env.stop)

    def test_url_validation(self):
        self.assertEqual('https://example.test/v1', normalize_endpoint('https://EXAMPLE.test:443/v1/'))
        self.assertEqual('http://[::1]:1234/v1', normalize_endpoint('http://[::1]:1234/v1/'))
        for bad in ['file:///D:/x', 'http://remote.test/v1', 'https://user:secret@host.test/v1', 'https://x.test/v1?key=secret', 'https://x.test/#token', 'https://x.test/v1/chat/completions', r'https://x.test\x', 'https://x.test:bad', 'https://x.test/\n']:
            with self.assertRaises(ProviderError, msg=bad): normalize_endpoint(bad)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_independent_keys_profiles_environment_and_legacy_preservation(self):
        first = 'development-key-alpha-not-real';second = 'development-key-beta-not-real';url = 'https://second.example.test/v1'
        self.settings.save({'api_key': first, 'model': 'model-a'})
        self.settings.save({'base_url': url, 'model': 'model-b'})
        self.assertEqual('', self.settings.key());self.assertFalse(self.settings.public()['ready'])
        self.settings.save({'api_key': second});self.assertEqual(second, self.settings.key())
        self.settings.save({'base_url': BASE_URL});self.assertEqual(first, self.settings.key());self.assertEqual('model-a', self.settings.read()['model'])
        with patch.dict(os.environ, {'INTENT_SILICONFLOW_API_KEY': 'environment-test-key-not-real'}):
            self.settings.save({'base_url': url});self.assertEqual(second, self.settings.key())
            self.settings.save({'base_url': 'http://127.0.0.1:11434/v1', 'model': 'local-model'});self.assertEqual('', self.settings.key())
            self.assertTrue(self.settings.public()['ready'])
        self.settings.save({'base_url': url, 'clear_key': True});self.assertEqual('', self.settings.key())
        self.assertEqual(first, self.settings.key_for(BASE_URL))
        public = json.dumps(self.settings.public());saved = self.settings.path.read_text(encoding='utf-8')
        self.assertNotIn(first, public+saved);self.assertNotIn(second, public+saved)
        # Exercise an actual old-format file without any migration at read time.
        raw = self.settings.raw();legacy = {'model': 'old-model', 'key_dpapi': raw['profiles'][BASE_URL]['key_dpapi']}
        self.settings.path.write_text(json.dumps(legacy), encoding='utf-8')
        self.assertEqual(first, self.settings.key());self.assertEqual(legacy, self.settings.raw())
        self.settings.save({'base_url': url});self.assertEqual(first, self.settings.key_for(BASE_URL))
        self.settings.save({'base_url': BASE_URL, 'clear_key': True});self.assertEqual('', self.settings.key())

    def test_generic_environment_key_is_bound_to_its_endpoint(self):
        with patch.dict(os.environ, {'INTENT_MODEL_BASE_URL': 'https://a.example.test/v1', 'INTENT_MODEL_API_KEY': 'env-test-only'}):
            self.assertEqual('env-test-only', self.settings.key_for('https://a.example.test/v1'))
            self.assertEqual('', self.settings.key_for('https://b.example.test/v1'))

    def test_actual_loopback_wire_format_frozen_endpoint_and_nonstream_json(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                received.append((self.path, self.headers.get('Authorization')))
                data = json.dumps({'data': [{'id': 'local-qwen3-test'}]}).encode()
                self.send_response(200);self.send_header('Content-Length', str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, self.headers.get('Authorization'), payload))
                data = json.dumps({'choices': [{'message': {'content': '{"ok": true}'}, 'finish_reason': 'stop'}]}).encode()
                self.send_response(200);self.send_header('Content-Type', 'application/json');self.send_header('Content-Length', str(len(data)));self.end_headers();self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:'+str(server.server_port)+'/v1'
        self.settings.save({'base_url': url, 'model': 'local-qwen3-test', 'stream': False, 'json_mode': False, 'send_temperature': False, 'token_parameter': 'max_completion_tokens'})
        client = SiliconFlow(self.settings).bound(self.settings.snapshot())
        self.settings.save({'base_url': BASE_URL, 'model': 'another-model'})
        self.assertEqual(['local-qwen3-test'], client.models())
        value, meta = client.json([{'role': 'user', 'content': 'return JSON'}], max_tokens=123)
        self.assertTrue(value['ok']);self.assertEqual(url, meta['base_url']);self.assertEqual('compatible', meta['provider'])
        self.assertEqual(('/v1/models', None), received[0])
        endpoint, auth, payload = received[1]
        self.assertEqual('/v1/chat/completions', endpoint);self.assertIsNone(auth)
        self.assertFalse(payload['stream']);self.assertEqual(123, payload['max_completion_tokens'])
        for absent in ['enable_thinking', 'response_format', 'temperature', 'max_tokens']: self.assertNotIn(absent, payload)

    def test_generation_freezes_connection_across_all_calls_and_provenance(self):
        self.settings.save({'base_url': 'http://127.0.0.1:11434/v1', 'model': 'test/fixture-model'})
        entered = threading.Event();release = threading.Event();captured = []
        def transport(path, payload):
            captured.append(copy_connection())
            if not entered.is_set(): entered.set();release.wait(4)
            return fixture_transport(path, payload)
        provider = SiliconFlow(self.settings, transport=transport)
        original = provider.bound
        def bound(connection):
            captured.append(dict(connection));return original(connection)
        provider.bound = bound
        def copy_connection(): return {'active_settings': self.settings.public()['base_url']}
        store = Store(Path(self.temp.name)/'qa.sqlite3');service = AIService(store, provider);service.settings = self.settings
        self.addCleanup(service.close)
        try:
            job = service.submit('generate', {'goal': '制作一个能检查步骤和实际结果的本地项目方案', 'task_type': 'project'})
            self.assertTrue(entered.wait(4));self.settings.save({'base_url': 'http://127.0.0.1:1234/v1', 'model': 'new-model'});release.set()
            for _ in range(300):
                result = service.public_job(job['id'])
                if result['status'] not in ('queued', 'running'): break
                time.sleep(.01)
            self.assertEqual('completed', result['status'], result)
            snapshot = service.job(job['id'])['input']['connection']
            self.assertEqual('http://127.0.0.1:11434/v1', snapshot['base_url'])
            self.assertTrue(all(c['base_url'] == snapshot['base_url'] for c in captured if 'base_url' in c))
            view = store.view(result['session']);self.assertEqual('compatible', view['task']['ai']['provider']);self.assertEqual(snapshot['base_url'], view['task']['ai']['base_url'])
            self.assertTrue(all(c['base_url'] == snapshot['base_url'] for c in view['task']['ai']['calls']))
        finally: release.set()

import http.client
import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path

import proof
from core import Invalid
from server import make_handler
from store import Conflict, Store


ROOT = Path('D:/CodexWork/temp/intent-proof-tests')


def sandbox():
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = tempfile.TemporaryDirectory(dir=ROOT)
    folder = Path(temp.name)
    return temp, folder, Store(folder / 'workbench.sqlite3'), Store(folder / 'proof.sqlite3')


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.temp, self.folder, self.store, self.sandbox = sandbox()
        self.addCleanup(self.temp.cleanup)

    def test_chain_verifies_lock_and_rejects_stale_revision(self):
        sid = proof.demo_session(self.sandbox)
        initial = proof.chain_report(self.sandbox, sid)
        self.assertTrue(initial['ok'])
        self.assertEqual(0, initial['session']['revision'])
        self.assertEqual(0, initial['labels'])
        proof.toggle_lock(self.sandbox, sid, 0, True)
        locked = proof.chain_report(self.sandbox, sid)
        self.assertTrue(locked['ok'])
        self.assertEqual(1, locked['session']['revision'])
        self.assertIn('opening', locked['state']['locks'])
        self.assertEqual(1, locked['mutations'])
        self.assertGreaterEqual(locked['events_total'], 2)
        with self.assertRaises(Conflict):
            proof.toggle_lock(self.sandbox, sid, 0, False)
        self.assertTrue(proof.chain_report(self.sandbox, sid)['ok'])

    def test_chain_checker_detects_a_tampered_snapshot(self):
        sid = proof.demo_session(self.sandbox)
        proof.toggle_lock(self.sandbox, sid, 0, True)
        with closing(self.sandbox.connect()) as db:
            db.execute("UPDATE events SET after_state=? WHERE session=? AND kind='lock'", ('{}', sid))
        report = proof.chain_report(self.sandbox, sid)
        self.assertFalse(report['ok'])
        failed = {check['id'] for check in report['checks'] if not check['passed']}
        self.assertIn('snapshot_chain', failed)

    def test_proof_sandbox_cannot_operate_on_a_regular_session(self):
        sid = self.store.sessions()[0]['id']
        with self.assertRaises(Invalid):
            proof.toggle_lock(self.store, sid, 0, True)

    def test_splice_uses_code_points_and_rejects_a_stale_selection(self):
        preview = proof.splice_preview(proof.SPLICE_TEXT, proof.SPLICE_QUERY, 2)
        self.assertEqual(2, preview['count'])
        self.assertEqual(1, preview['range']['utf16_start'] - preview['range']['start'])
        self.assertEqual(proof.SPLICE_QUERY, preview['selection'])
        receipt = proof.apply_splice(proof.SPLICE_TEXT, preview['range']['start'], preview['range']['end'], '替换完成。',
                                     preview['prefix_hash'], preview['suffix_hash'], preview['selection_hash'])
        self.assertTrue(receipt['outside_unchanged'])
        self.assertEqual(proof.SPLICE_TEXT[:preview['range']['start']] + '替换完成。' + proof.SPLICE_TEXT[preview['range']['end']:], receipt['after'])
        self.assertEqual(len(proof.SPLICE_QUERY), receipt['selection_codepoints'])
        tampered = proof.SPLICE_TEXT.replace(proof.SPLICE_QUERY, '已经被另一处改过的句子。', 1)
        with self.assertRaises(Conflict):
            proof.apply_splice(tampered, preview['range']['start'], preview['range']['end'], '替换完成。',
                               preview['prefix_hash'], preview['suffix_hash'], preview['selection_hash'])
        with self.assertRaises(Invalid):
            proof.splice_preview(proof.SPLICE_TEXT, proof.SPLICE_QUERY, 3)
        with self.assertRaises(Invalid):
            proof.apply_splice(proof.SPLICE_TEXT, preview['range']['start'], preview['range']['end'], '',
                               preview['prefix_hash'], preview['suffix_hash'], preview['selection_hash'])

    def test_conflict_core_and_minimal_corrections_in_collision_case(self):
        report = proof.solver_report(lock=True, require_phrase=True, max_chars=180)
        self.assertEqual(81, report['universe'])
        self.assertEqual(0, report['eligible'])
        self.assertEqual(['lock:technical', 'required:0'], [item['id'] for item in report['conflict_core']])
        self.assertEqual(2, report['correction_count'])
        sensitivity = {item['id']: item['newly_eligible'] for item in report['sensitivity']}
        self.assertGreater(sensitivity['lock:technical'], 0)
        self.assertEqual(0, sensitivity['max_chars'])
        self.assertEqual(0, report['paid_calls'])
        witnesses = {tuple(item['relax']): item for item in report['corrections']}
        self.assertIn(('锁定：实现方法',), witnesses)
        self.assertTrue(all(item['witness'] for item in report['corrections']))

    def test_solver_without_constraints_enumerates_every_combination(self):
        report = proof.solver_report()
        self.assertEqual(81, report['universe'])
        self.assertEqual(81, report['eligible'])
        self.assertEqual([], report['conflict_core'])
        self.assertGreaterEqual(len(report['frontier']), 1)

    def test_http_routes_are_isolated_and_return_real_conflicts(self):
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.store))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        connection = http.client.HTTPConnection('127.0.0.1', httpd.server_port)
        self.addCleanup(connection.close)

        def request(method, path, data=None):
            connection.request(method, path, json.dumps(data) if data is not None else None,
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, response.read()

        status, content = request('GET', '/proof')
        self.assertEqual(200, status)
        self.assertIn(b'ENGINEERING PROOF', content)
        status, _ = request('GET', '/proof.js')
        self.assertEqual(200, status)
        status, _ = request('GET', '/proof.css')
        self.assertEqual(200, status)

        status, content = request('GET', '/api/proof/state')
        self.assertEqual(200, status)
        state = json.loads(content)
        self.assertTrue(state['chain']['ok'])
        self.assertEqual([], state['ledger'])
        self.assertEqual('proof.sqlite3', state['sandbox']['database'])

        status, content = request('POST', '/api/proof/action', {'kind': 'lock', 'revision': 0})
        self.assertEqual(200, status)
        self.assertEqual(1, json.loads(content)['session']['revision'])
        status, content = request('POST', '/api/proof/action', {'kind': 'unlock', 'revision': 0})
        self.assertEqual(409, status)
        error = json.loads(content)
        self.assertIn('v1', error['error'])
        self.assertTrue(error['request_id'])

        status, content = request('POST', '/api/proof/solve', {'lock': True, 'require_phrase': True, 'max_chars': None})
        self.assertEqual(200, status)
        report = json.loads(content)
        self.assertEqual(0, report['eligible'])
        self.assertEqual(2, len(report['conflict_core']))

        preview_request = {'mode': 'preview', 'text': proof.SPLICE_TEXT, 'query': proof.SPLICE_QUERY, 'occurrence': 2}
        status, content = request('POST', '/api/proof/splice', preview_request)
        self.assertEqual(200, status)
        preview = json.loads(content)
        self.assertEqual(1, preview['range']['utf16_start'] - preview['range']['start'])
        apply_request = {'mode': 'apply', 'text': proof.SPLICE_TEXT, 'start': preview['range']['start'],
                         'end': preview['range']['end'], 'replacement': '替换完成。',
                         'prefix_hash': preview['prefix_hash'], 'suffix_hash': preview['suffix_hash'],
                         'selection_hash': preview['selection_hash']}
        status, content = request('POST', '/api/proof/splice', apply_request)
        self.assertEqual(200, status)
        self.assertTrue(json.loads(content)['outside_unchanged'])
        apply_request['text'] = proof.SPLICE_TEXT.replace(proof.SPLICE_QUERY, '改过的内容。', 1)
        status, _ = request('POST', '/api/proof/splice', apply_request)
        self.assertEqual(409, status)

        status, content = request('POST', '/api/proof/reset', {})
        self.assertEqual(201, status)
        self.assertEqual(0, json.loads(content)['session']['revision'])
        self.assertFalse(any(item.get('source') == 'proof' for item in self.store.sessions()))


if __name__ == '__main__':
    unittest.main()

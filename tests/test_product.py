import copy
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ai.delivery import check
from ai.provider import Settings,SiliconFlow,ProviderError
from ai.service import AIService
from ai_fixture import fixture_transport
from core import Invalid
from server import make_handler,LocalHTTPServer,main as server_main
from store import Store,Conflict


class ProductTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/CodexWork/temp/intent-product-tests');root.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(temp.cleanup);self.folder=Path(temp.name)
        env=patch.dict(os.environ,{'INTENT_SILICONFLOW_API_KEY':'product-fixture-not-a-real-credential'});env.start();self.addCleanup(env.stop)
        self.store=Store(self.folder/'qa.sqlite3');self.settings=Settings(self.folder/'private');self.settings.save({'model':'test/fixture-model'})
        self.provider=SiliconFlow(self.settings,transport=fixture_transport);self.service=AIService(self.store,self.provider);self.service.settings=self.settings;self.addCleanup(self.service.close)
        self.body={'goal':'为当前工作室交付一份完整的使用说明，包含实际步骤与验收方式','facts':'本地保存于D盘','materials':[{'name':'说明.md','text':'必须先预览草案再采用。锁定章节不可改动。'}]}

    def wait(self,job):
        for _ in range(300):
            current=self.service.public_job(job['id'])
            if current['status'] not in ('queued','running'):return current
            time.sleep(.01)
        self.fail('Job timed out')

    def generate(self):
        job=self.wait(self.service.submit('generate',self.body));self.assertEqual('completed',job['status'],job['error'])
        return job['result']['session_id']

    def action(self,sid,kind,**body):
        return self.store.action(sid,{'revision':self.store.view(sid)['revision'],'kind':kind,**body})

    def test_material_ids_are_immutable_and_removal_reorder_undo_survive_restart(self):
        sid=self.generate();library=self.service.materials(sid)
        self.assertEqual(['M1'],[m['id'] for m in library['materials']])
        second=self.service.update_materials(sid,{'revision':library['revision'],'materials':library['materials']+[{'name':'追加.md','text':'新的实施标准，需要先确认输入再核对输出。'}]})
        with self.assertRaises(Conflict):self.service.update_materials(sid,{'revision':library['revision'],'materials':[]})
        reordered=self.service.update_materials(sid,{'revision':second['revision'],'materials':second['materials'][::-1]})
        self.assertEqual(['M2','M1'],[m['id'] for m in reordered['materials']])
        edited=copy.deepcopy(reordered['materials']);edited[0]['text']='更新后的标准，要保留恢复方式。'
        third=self.service.update_materials(sid,{'revision':reordered['revision'],'materials':edited})
        self.assertEqual(['M3','M1'],[m['id'] for m in third['materials']])
        self.action(sid,'undo');self.assertEqual(['M2','M1'],[m['id'] for m in self.service.materials(sid)['materials']])
        self.service.close();restored=AIService(Store(self.store.path),self.provider);self.addCleanup(restored.close)
        self.assertEqual(reordered['materials'],restored.materials(sid)['materials'])
        again=restored.update_materials(sid,{'revision':self.store.view(sid)['revision'],'materials':[{'name':'最后.md','text':'最后一份资料'}]})
        self.assertEqual('M4',again['materials'][0]['id']);self.assertEqual(0,self.store.view(sid)['pair_count'])

    def test_revision_uses_frozen_material_snapshot_and_stale_proposal_cannot_apply(self):
        sid=self.generate();entered=threading.Event();release=threading.Event();captured=[]
        def transport(path,payload=None):
            if payload:
                captured.append(json.loads(payload['messages'][-1]['content']));entered.set();release.wait(3)
            return fixture_transport(path,payload)
        self.provider.transport=transport;view=self.store.view(sid)
        job=self.service.submit('revise',{'revision':view['revision'],'instruction':'根据资料补充验收方法','scope':['section2']},sid)
        try:
            self.assertTrue(entered.wait(2))
            self.service.update_materials(sid,{'revision':view['revision'],'materials':[{'name':'全新.md','text':'这条消息在AI任务提交之后才添加。'}]})
        finally:release.set()
        completed=self.wait(job);self.assertEqual('completed',completed['status'],completed['error'])
        self.assertTrue(all(s['id'].startswith('M1#') for s in captured[0]['sources']))
        with self.assertRaises(Conflict):self.service.apply(job['id'],{'revision':view['revision']})
        self.assertEqual(view['text'],self.store.view(sid)['text'])
        warnings=check(self.store.view(sid),self.service.materials(sid)['materials'])['warnings']
        self.assertTrue(any('已移除素材' in w for w in warnings))

    def test_concurrent_duplicate_requests_only_call_provider_once(self):
        calls=[];lock=threading.Lock()
        def transport(path,payload=None):
            with lock:calls.append(path)
            return fixture_transport(path,payload)
        self.provider.transport=transport;body={**self.body,'request_id':'same-request-12345'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=list(pool.map(lambda _:self.service.submit('generate',body),range(2)))
        self.assertEqual(jobs[0]['id'],jobs[1]['id']);self.assertEqual('completed',self.wait(jobs[0])['status'])
        self.assertEqual(1,len(calls))
        self.assertEqual(jobs[0]['id'],self.service.submit('generate',body)['id'])
        with self.assertRaises(Conflict):self.service.submit('generate',{**body,'goal':'不同的目标不能复用这个请求编号'})

    def test_complete_and_quick_requests_and_structure_repair_are_disclosed(self):
        calls=[]
        def transport(path,payload=None):
            calls.append(copy.deepcopy(payload));result=fixture_transport(path,payload)
            if len(calls)==1:
                data=json.loads(result['choices'][0]['message']['content']);data['blocks']=[]
                result['choices'][0]['message']['content']=json.dumps(data)
            return result
        self.provider.transport=transport
        complete=self.wait(self.service.submit('generate',self.body));self.assertEqual('completed',complete['status'],complete['error'])
        self.assertEqual(9000,calls[0]['max_tokens'])
        self.assertIn('250–450',json.loads(calls[0]['messages'][-1]['content'])['requirements'])
        self.assertIn('structure_repair_reason',complete['result']['calls'][0])
        quick=self.wait(self.service.submit('generate',{**self.body,'detail_level':'quick'}))
        self.assertEqual('completed',quick['status'],quick['error']);self.assertEqual(4500,calls[-1]['max_tokens'])

    def test_retry_failure_and_interruption_preserves_input_with_new_settings(self):
        def fail(path,payload=None):raise ProviderError('模拟暂时断线')
        self.provider.transport=fail
        failed=self.wait(self.service.submit('generate',self.body));self.assertEqual('error',failed['status'])
        self.provider.transport=fixture_transport
        retried=self.wait(self.service.retry(failed['id'],{'request_id':'retry-id-123456'}))
        self.assertEqual('completed',retried['status'],retried['error']);self.assertEqual(failed['id'],retried['retry_of'])
        self.assertEqual(self.body['goal'],self.store.view(retried['result']['session_id'])['task']['brief'])
        with self.assertRaises(Invalid):self.service.retry(retried['id'],{})
        with closing(self.service.connect()) as db:db.execute("UPDATE jobs SET status='running' WHERE id=?",(failed['id'],))
        self.service.close();restored=AIService(self.store,self.provider);self.addCleanup(restored.close)
        self.assertEqual('interrupted',restored.public_job(failed['id'])['status'])

    def test_draft_persists_and_conflict_does_not_overwrite_or_store_unknown_fields(self):
        original=self.service.draft();value={'goal':'真实目标草稿，刷新后必须保留','facts':'每周8小时','materials':self.body['materials'],'api_key':'must-not-store'}
        saved=self.service.draft({'revision':original['revision'],'input':value})
        self.assertNotIn('api_key',saved['input'])
        self.service.close();restored=AIService(self.store,self.provider);self.addCleanup(restored.close)
        self.assertEqual(saved,restored.draft())
        with self.assertRaises(Conflict):restored.draft({'revision':0,'input':{'goal':'不能覆盖'}})
        self.assertEqual(saved,restored.draft())

    def test_review_resets_for_content_and_materials_but_undo_restores(self):
        sid=self.generate();checks={'read_through':True,'facts_checked':True,'usable':True}
        self.action(sid,'review',checks=checks);self.action(sid,'lock',block='section1')
        self.assertEqual(checks,self.store.view(sid)['state']['review'])
        blocks=copy.deepcopy(self.store.view(sid)['task']['blocks']);blocks[-1]['variants'][0]['template']+=' 新的内容。'
        self.action(sid,'edit',blocks=blocks);self.assertEqual({},self.store.view(sid)['state']['review'])
        self.action(sid,'undo');self.assertEqual(checks,self.store.view(sid)['state']['review'])
        lib=self.service.materials(sid);self.service.update_materials(sid,{'revision':lib['revision'],'materials':[]})
        self.assertEqual({},self.store.view(sid)['state']['review']);self.assertEqual(0,self.store.view(sid)['pair_count'])

    def test_revision_draft_survives_restart_is_isolated_and_conflict_keeps_saved_text(self):
        sid=self.generate();other=self.generate()
        original=self.store.view(sid);original_jobs=self.service.jobs(sid)
        saved=self.service.draft({'revision':0,'input':{'instruction':'保留预算，补充具体检查步骤。','scope':'section3','api_key':'must-not-store'}},sid=sid)
        self.assertEqual({'instruction':'保留预算，补充具体检查步骤。','scope':'section3'},saved['input'])
        self.assertEqual({},self.service.draft(sid=other)['input'])
        self.assertEqual({},self.service.draft()['input'])
        with self.assertRaises(Conflict):self.service.draft({'revision':0,'input':{'instruction':'旧窗口覆盖','scope':'all'}},sid=sid)
        for scope in ['not-a-section','fixed_facts']:
            with self.assertRaises(Invalid):self.service.draft({'revision':saved['revision'],'input':{'instruction':'修改','scope':scope}},sid=sid)
        self.service.close();restored=AIService(self.store,self.provider);self.addCleanup(restored.close)
        self.assertEqual(saved,restored.draft(sid=sid))
        self.assertEqual(original,self.store.view(sid))
        self.assertEqual(original_jobs,restored.jobs(sid))
        # Saving drafts must not create any new model jobs or preference labels.
        self.assertEqual(0,self.store.view(sid)['pair_count'])

    def test_title_only_edit_invalidates_review_and_undo_restores_export_heading(self):
        sid=self.generate();checks={'read_through':True,'facts_checked':True,'usable':True}
        self.action(sid,'review',checks=checks)
        original=self.store.view(sid);blocks=copy.deepcopy(original['task']['blocks'])
        blocks[-1]['title']='需重新核对的验收清单'
        self.action(sid,'edit',blocks=blocks)
        self.assertEqual({},self.store.view(sid)['state']['review'])
        exported=self.service.export(sid,self.store.view(sid)['revision'],'md')
        self.assertIn('## 需重新核对的验收清单',Path(exported['path']).read_text('utf-8'))
        self.action(sid,'undo')
        view=self.store.view(sid);self.assertEqual(checks,view['state']['review'])
        self.assertEqual(original['task']['blocks'][-1]['title'],view['task']['blocks'][-1]['title'])
        self.assertEqual(0,view['pair_count'])
        self.action(sid,'lock',block=blocks[-1]['id'])
        with self.assertRaises(Invalid):self.action(sid,'edit',blocks=blocks)
        self.assertEqual(checks,self.store.view(sid)['state']['review'])

    def test_one_block_generated_writing_supports_edit_compare_lock_and_export(self):
        def single(path,payload=None):
            result=fixture_transport(path,payload)
            if payload:
                value=json.loads(result['choices'][0]['message']['content'])
                if 'blocks' in value:
                    value['blocks']=value['blocks'][:1]
                    result['choices'][0]['message']['content']=json.dumps(value,ensure_ascii=False)
            return result
        self.provider.transport=single
        job=self.wait(self.service.submit('generate',{**self.body,'goal':'写一封160–220字的邀请邮件','task_type':'writing','facts':''}))
        self.assertEqual('completed',job['status'],job['error']);sid=job['result']['session_id']
        view=self.store.view(sid);self.assertEqual(1,len(view['task']['blocks']));self.assertEqual(3,view['feasible_count'])
        self.assertFalse(self.service.delivery(sid)['requirements']['length']['within_range'])
        self.assertEqual(0,view['pair_count']);offer=self.store.offer(sid,view['revision'])
        self.action(sid,'compare',offer=offer['id'],choice='a');self.assertEqual(1,self.store.view(sid)['pair_count'])
        view=self.store.view(sid);before=view['text'];blocks=copy.deepcopy(view['task']['blocks']);bid=blocks[0]['id']
        selected=view['state']['combo'][bid]
        next(v for v in blocks[0]['variants'] if v['id']==selected)['template']+=' 期待收到您的回复。'
        self.action(sid,'edit',blocks=blocks);export=self.service.export(sid,self.store.view(sid)['revision'],'txt')
        self.assertIn('期待收到您的回复',Path(export['path']).read_text('utf-8'));self.action(sid,'undo')
        self.assertEqual(before,self.store.view(sid)['text']);self.action(sid,'lock',block=bid)
        self.assertIsNone(self.store.offer(sid,self.store.view(sid)['revision']))

    def test_download_is_exact_and_zip_contains_source_originals_without_traversal(self):
        sid=self.generate();export=self.service.export(sid,self.store.view(sid)['revision'],'zip')
        with zipfile.ZipFile(export['path']) as archive:
            self.assertEqual(self.body['materials'][0]['text'],archive.read('素材/M1-说明.md').decode())
            self.assertIn('交付检查.json',archive.namelist())
            evidence=json.loads(archive.read('逐段来源核对.json'))
            self.assertEqual(self.store.view(sid)['revision'],evidence['revision'])
            self.assertEqual('not_performed',evidence['semantic_fact_check'])
            self.assertEqual('local-literal-alignment-v1',evidence['method'])
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,self.service))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with urllib.request.urlopen(base+export['url']) as response:
                self.assertIn("filename*=UTF-8''",response.headers['Content-Disposition'])
                self.assertEqual(hashlib.sha256(Path(export['path']).read_bytes()).hexdigest(),hashlib.sha256(response.read()).hexdigest())
            with self.assertRaises(urllib.error.HTTPError) as rejected:urllib.request.urlopen(base+'/api/files/%2e%2e%2fprivate%2fsiliconflow.json')
            self.assertEqual(404,rejected.exception.code)
        finally:server.shutdown();server.server_close();thread.join()

    def test_single_server_owns_port_and_reopening_uses_existing_instance(self):
        server=LocalHTTPServer(('127.0.0.1',0),make_handler(self.store,self.service))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with self.assertRaises(OSError):LocalHTTPServer(('127.0.0.1',server.server_port),make_handler(self.store,self.service))
            with patch('sys.argv',['server.py','--port',str(server.server_port),'--db',str(self.store.path),'--open']),patch('webbrowser.open') as opened:
                self.assertEqual(0,server_main());opened.assert_called_once()
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()

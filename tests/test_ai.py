import copy
import importlib.util
import io
import json
import os
import tempfile
import time
import threading
import unittest
import urllib.error
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ai.provider import ProviderError,Settings,SiliconFlow,protect_secret
from ai.retrieval import retrieve
from ai.service import AIService
from core import Invalid,render,variant_for
from store import Conflict,Store
from ai_fixture import fixture_transport

DUMMY='unit-test-credential-not-a-real-key'


class AITests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional NumPy environment')
    def test_learned_preference_reaches_revision_and_provenance_without_labels(self):
        sid=self.generate()
        self.action(sid,'research_config',config={'model':'content_neural','policy':'random','context_mode':'current','budget':8,'seed':11,'evaluate_only':True,'data_origin':'development_test'})
        self.action(sid,'lock',block='section1')
        for _ in range(4):
            view=self.store.view(sid);offer=self.store.offer(sid,view['revision'])
            self.action(sid,'compare',offer=offer['id'],choice='a')
        view=self.store.view(sid);captured=[];original=self.provider.transport
        def capture(path,payload=None):
            if payload:captured.append(json.loads(payload['messages'][-1]['content']))
            return original(path,payload)
        self.provider.transport=capture
        job=self.wait(self.service.submit('revise',{'revision':view['revision'],'instruction':'写得更具体，补上验收','scope':['section2']},sid))
        self.assertEqual('completed',job['status'],job['error'])
        ctx=captured[-1]['learned_preference_context']
        self.assertEqual('content_neural',ctx['model_id']);self.assertEqual(4,ctx['pair_count'])
        self.assertEqual(['section2'],[v['block'] for v in ctx['examples']])
        self.assertEqual(view['model_config']['snapshot_hash'],ctx['model_snapshot_hash'])
        self.assertEqual(view['text'],self.store.view(sid)['text'])
        self.service.apply(job['id'],{'revision':view['revision']})
        adopted=self.store.view(sid)
        self.assertEqual(ctx,adopted['task']['ai']['revisions'][-1]['preference_context'])
        self.assertEqual(4,adopted['pair_count']);self.assertEqual(view['state']['locks'],adopted['state']['locks'])
        self.action(sid,'undo');self.assertEqual(view['task']['ai'],self.store.view(sid)['task']['ai'])

    def setUp(self):
        root=Path('D:/CodexWork/temp/intent-ai-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'INTENT_SILICONFLOW_API_KEY':DUMMY});self.env.start();self.addCleanup(self.env.stop)
        self.store=Store(self.folder/'qa.sqlite3')
        self.settings=Settings(self.folder/'private');self.settings.save({'model':'test/fixture-model'})
        self.provider=SiliconFlow(self.settings,transport=fixture_transport)
        self.service=AIService(self.store,self.provider);self.service.settings=self.settings
        self.addCleanup(self.service.close)

    def wait(self,job):
        for _ in range(250):
            value=self.service.public_job(job['id'])
            if value['status'] not in ('queued','running'):return value
            time.sleep(.01)
        self.fail('Background job did not finish')

    def generate(self):
        job=self.wait(self.service.submit('generate',{'goal':'为学生设计一个四周可完成的校园失物招领项目，要有实施步骤和验收。','facts':'周期为四周','task_type':'project','materials':[{'name':'需求.md','text':'校园失物招领需要发布、搜索、核实认领，用户不希望公开联系方式。'}]}))
        self.assertEqual('completed',job['status'],job['error'])
        return job['result']['session_id']

    def action(self,sid,kind,**extra):
        return self.store.action(sid,{'kind':kind,'revision':self.store.view(sid)['revision'],**extra})

    def test_retrieval_and_generated_task_are_grounded_and_key_free(self):
        chunks=retrieve('认领隐私', [{'name':'相关材料','text':'认领流程必须保护隐私。'},{'name':'无关材料','text':'烹饪需要食盐和蔬菜。'}],1)
        self.assertEqual('相关材料',chunks[0]['name'])
        sid=self.generate();view=self.store.view(sid)
        self.assertEqual('generated',view['task']['source'])
        self.assertIn('周期为四周',view['text'])
        self.assertEqual(27,view['feasible_count'])
        self.assertEqual(0,view['pair_count'])
        audit=json.dumps(self.store.audit(sid),ensure_ascii=False)
        public=json.dumps(self.service.jobs(),ensure_ascii=False)
        self.assertNotIn(DUMMY,audit+public)
        self.assertNotIn('input',self.service.jobs()[0])
        self.assertIn('sources',view['task']['ai'])

    def test_unconfirmed_source_phrase_does_not_trigger_automatic_paid_repair(self):
        job=self.wait(self.service.submit('generate',{'goal':'请写一个可实施的校园项目方案','materials':[{'name':'安排','text':'最终名额尚未确认。'}]}))
        self.assertEqual('completed',job['status'],job['error']);self.assertEqual(1,len(job['result']['calls']))
        task=self.store.view(job['result']['session_id'])['task']
        self.assertIn('最终名额尚未确认',task['ai']['acceptance_suggestion']['required'])
        self.assertEqual([],task['ai']['automatic_check_contract']['required'])

    def test_unknown_citations_are_removed_and_disclosed(self):
        original=self.provider.transport
        def hallucinated(path,payload=None):
            result=original(path,payload)
            if payload:
                value=json.loads(result['choices'][0]['message']['content'])
                for b in value.get('blocks',[]):
                    b['variants']=[v+' [M9#999]' for v in b['variants']]
                result['choices'][0]['message']['content']=json.dumps(value)
            return result
        self.provider.transport=hallucinated
        sid=self.generate();view=self.store.view(sid)
        self.assertNotIn('[M9#999]',view['text'])
        self.assertIn('M9#999',view['task']['ai']['checks']['unsupported_citations_removed'])

    def test_revision_is_a_proposal_then_atomic_apply_and_undo(self):
        sid=self.generate();self.action(sid,'lock',block='section1')
        before=self.store.view(sid)
        proposal=self.wait(self.service.submit('revise',{'revision':before['revision'],'instruction':'补充具体的实施验收','scope':['section2']},sid))
        self.assertEqual('completed',proposal['status'],proposal['error'])
        self.assertEqual(before['state'],self.store.view(sid)['state'])
        self.service.apply(proposal['id'],{'revision':before['revision']})
        after=self.store.view(sid)
        self.assertNotEqual(before['text'],after['text'])
        self.assertEqual(before['state']['locks'],after['state']['locks'])
        self.assertEqual(before['state']['combo']['section1'],after['state']['combo']['section1'])
        self.assertIn('新增验收',after['text'])
        self.assertEqual(proposal['id'],after['task']['ai']['revisions'][-1]['job_id'])
        self.assertEqual(0,after['pair_count'])
        self.action(sid,'undo')
        self.assertEqual(before['text'],self.store.view(sid)['text'])
        self.assertEqual(before['task']['ai'],self.store.view(sid)['task']['ai'])

    def test_stale_and_locked_model_changes_are_rejected(self):
        sid=self.generate();before=self.store.view(sid)
        proposal=self.wait(self.service.submit('revise',{'revision':before['revision'],'instruction':'补充可操作的细节','scope':['section2']},sid))
        self.action(sid,'lock',block='section2')
        locked=self.store.view(sid)
        with self.assertRaises(Conflict):self.service.apply(proposal['id'],{'revision':before['revision']})
        self.assertEqual(locked['text'],self.store.view(sid)['text'])
        with self.assertRaises(Invalid):self.service.submit('revise',{'revision':locked['revision'],'instruction':'修改这一部分','scope':['section2']},sid)
        original=self.provider.transport
        def bad_transport(path,payload=None):
            if path.startswith('/models'):return original(path,payload)
            return {'choices':[{'message':{'content':json.dumps({'summary':'违规修改','changes':[{'block':'section2','text':'企图覆盖锁定'}]})},'finish_reason':'stop'}]}
        self.provider.transport=bad_transport
        failed=self.wait(self.service.submit('revise',{'revision':locked['revision'],'instruction':'改进其他未锁定部分','scope':['section3']},sid))
        self.assertEqual('error',failed['status'])
        self.assertEqual(locked['text'],self.store.view(sid)['text'])

    def test_invalid_generation_repairs_once_and_does_not_create_bad_task(self):
        count=len(self.store.sessions());calls=[]
        def bad(path,payload=None):
            result=fixture_transport(path,payload)
            if payload:
                prompt=json.loads(payload['messages'][-1]['content']);calls.append(prompt['operation'])
                if prompt['operation']=='生成可交付的三种候选':result['choices'][0]['message']['content']=json.dumps({'blocks':[]})
            return result
        self.provider.transport=bad
        job=self.wait(self.service.submit('generate',{'goal':'创建一个可以实际使用的项目方案','facts':'每周只有8小时'}))
        self.assertEqual('error',job['status'])
        self.assertEqual(count,len(self.store.sessions()))
        self.assertEqual(2,calls.count('生成可交付的三种候选'))

    def test_export_and_job_restore_do_not_include_credentials(self):
        sid=self.generate();view=self.store.view(sid)
        output=self.service.export(sid,view['revision'],'zip')
        self.assertTrue(Path(output['path']).is_relative_to(self.folder))
        with zipfile.ZipFile(output['path']) as archive:
            self.assertTrue({'成品.md','成品.txt','任务说明.md','素材与生成记录.json','会话审计.json','交付检查.json','素材/M1-需求.md'}<=set(archive.namelist()))
            self.assertNotIn('已确定的条件',archive.read('成品.md').decode('utf-8'))
            self.assertNotIn(DUMMY,''.join(archive.read(n).decode('utf-8') for n in archive.namelist()))
            decision = json.loads(archive.read('决策与约束证据.json'))
            self.assertEqual(view['revision'], decision['revision'])
            self.assertEqual(view['feasible_count'], decision['eligible'])
            self.assertEqual(0, decision['paid_calls'])
            self.assertTrue(decision['read_only'])
        self.assertEqual(0,self.store.view(sid)['pair_count'])
        self.service.close();restored=AIService(self.store,self.provider);self.addCleanup(restored.close)
        self.assertEqual(sid,restored.jobs()[0]['session'])

    def test_cancellation_does_not_commit_a_generated_session(self):
        entered=threading.Event();release=threading.Event();count=len(self.store.sessions())
        def blocked(path,payload=None):
            entered.set();release.wait(3)
            return fixture_transport(path,payload)
        self.provider.transport=blocked
        job=self.service.submit('generate',{'goal':'生成一个有明确验收标准的项目方案'})
        self.assertTrue(entered.wait(2))
        self.service.cancel(job['id']);release.set();self.service.pool.shutdown(wait=True)
        self.assertEqual('cancelled',self.service.public_job(job['id'])['status'])
        self.assertEqual(count,len(self.store.sessions()))

    def test_fixed_facts_are_deterministic_and_not_unlockable(self):
        sid=self.generate();before=self.store.view(sid)
        self.assertIn('fixed_facts',before['state']['locks'])
        with self.assertRaises(Invalid):self.action(sid,'lock',block='fixed_facts')
        self.assertEqual(before['state'],self.store.view(sid)['state'])

    def test_writing_export_is_just_the_body(self):
        sid=self.generate();view=self.store.view(sid)
        result=self.service.export(sid,view['revision'],'txt')
        output=Path(result['path']).read_text(encoding='utf-8')
        self.assertNotIn('已确定的条件',output)
        self.assertNotIn('# '+view['task']['title'],output)

    @unittest.skipUnless(os.name=='nt','Windows DPAPI check')
    def test_dpapi_and_public_config_never_expose_key(self):
        with patch.dict(os.environ,{'INTENT_SILICONFLOW_API_KEY':''}):
            self.settings.save({'api_key':DUMMY})
            stored=self.settings.path.read_text(encoding='utf-8')
            self.assertNotIn(DUMMY,stored)
            self.assertEqual(DUMMY,self.settings.key())
            self.assertNotIn(DUMMY,json.dumps(self.settings.public()))
            self.settings.save({'clear_key':True})
            self.assertFalse(self.settings.public()['key_configured'])

    def test_streamed_json_and_safe_provider_errors(self):
        class Response:
            headers={'Content-Type':'text/event-stream','x-siliconcloud-trace-id':'test-trace'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def __iter__(self):
                for piece in ('{"ok":','true}'):
                    yield ('data: '+json.dumps({'choices':[{'delta':{'content':piece}}]})+'\n').encode()
                yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":5}}\n'
                yield b'data: [DONE]\n'
        class Opener:
            def open(self,*args,**kwargs):return Response()
        live_transport=SiliconFlow(self.settings)
        with patch('urllib.request.build_opener',return_value=Opener()):
            value,metadata=live_transport.json([{'role':'user','content':'JSON please'}])
        self.assertTrue(value['ok']);self.assertEqual(5,metadata['usage']['total_tokens'])
        error=urllib.error.HTTPError('https://api.siliconflow.cn/v1/chat/completions',401,'provider leaked '+DUMMY,{},io.BytesIO(DUMMY.encode()))
        class Failing:
            def open(self,*args,**kwargs):raise error
        with patch('urllib.request.build_opener',return_value=Failing()):
            with self.assertRaises(ProviderError) as raised:live_transport.models()
        self.assertNotIn(DUMMY,str(raised.exception))


if __name__=='__main__':unittest.main(verbosity=2)

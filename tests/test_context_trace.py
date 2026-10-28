import copy
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ai.guidance import normalize
from ai.inspiration import prepare, validate_output
from ai.requirement_trace import report, snapshot
from ai.provider import Settings, SiliconFlow
from ai.service import AIService
from ai_fixture import fixture_transport
from core import Invalid
from store import Conflict, Store


def guide():
    return {'version':'guided-intent-v1','category':'project','confirmed':True,'goal':'校园失物招领，先验证发布与搜索',
            'answers':{'audience':'给同学使用','boundary':None,'done':'需求说明'},'keep':'不公开联系方式','change':'不要扩大范围','criteria':'提供错误恢复步骤'}


def task():
    return {'title':'需求核对开发样本','source':'example','category':'project','facts':{},'brief':'做一份有搜索和错误恢复的方案',
            'intent_brief':{'explicit_answers':[{'question':'用途','answer':'需要搜索功能'},{'question':'交付标准','answer':'提供错误恢复步骤'}],
                'unresolved':['谁负责维护？'],'keep':'','change':'','user_acceptance':''},
            'blocks':[{'id':'intro','title':'范围','variants':[{'id':'v'+str(i),'template':'先说明范围，避免扩大。'+str(i)} for i in range(3)]},
                {'id':'search','title':'查找','variants':[{'id':'v'+str(i),'template':'当前不支持搜索功能，仍需进一步设计。'+str(i)} for i in range(3)]},
                {'id':'recovery','title':'恢复','variants':[{'id':'v'+str(i),'template':'提供错误恢复步骤：失败时保留输入，再选择重新提交。'+str(i)} for i in range(3)]}]}


class ContextTraceTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/CodexWork/temp/intent-context-trace-tests');root.mkdir(parents=True,exist_ok=True)
        temporary=tempfile.TemporaryDirectory(dir=root);self.addCleanup(temporary.cleanup);folder=Path(temporary.name)
        env=patch.dict(os.environ,{'INTENT_SILICONFLOW_API_KEY':'context-fixture-not-real'});env.start();self.addCleanup(env.stop)
        self.store=Store(folder/'qa.sqlite3');settings=Settings(folder/'private');settings.save({'model':'test/fixture-model'})
        self.prompts=[]
        def transport(path,payload=None):
            if payload:self.prompts.append(json.loads(payload['messages'][-1]['content']))
            return fixture_transport(path,payload)
        self.provider=SiliconFlow(settings,transport=transport);self.service=AIService(self.store,self.provider);self.service.settings=settings;self.addCleanup(self.service.close)

    def wait(self,job):
        for _ in range(500):
            current=self.service.public_job(job['id'])
            if current['status'] not in ('queued','running'):return current
            time.sleep(.01)
        self.fail('Timed out')

    def action(self,sid,kind,**kw):return self.store.action(sid,{'kind':kind,'revision':self.store.view(sid)['revision'],**kw})

    def review(self,sid,row,decision='met',blocks=None):
        v=self.store.view(sid)
        return self.action(sid,'requirement_review',requirement=row['id'],decision=decision,blocks=['recovery'] if blocks is None else blocks,snapshot_hash=snapshot(v['task'],v['state'])['hash'])

    def test_context_depends_on_actual_input_and_materials_not_selected_direction(self):
        g=guide();p=prepare(g,[{'name':'资料','text':'联系方式不得公开'}]);self.assertEqual(0,p['paid_calls'])
        self.assertTrue(any(b['text']=='联系方式不得公开' for b in p['basis']))
        self.assertTrue(any('校园失物招领' in r['preview'] for r in p['local_directions']))
        self.assertEqual(p['context_hash'],prepare({**g,'confirmed':False,'answers':{**g['answers'],'direction':'任意方向'}},[{'name':'资料','text':'联系方式不得公开'}])['context_hash'])
        for changed in [{**g,'goal':'不同项目'},{**g,'keep':'新的保留项'},{**g,'answers':{'audience':'新的使用者'}}]:
            self.assertNotEqual(p['context_hash'],prepare(changed,[{'name':'资料','text':'联系方式不得公开'}])['context_hash'])
        self.assertNotEqual(p['context_hash'],prepare(g,[{'name':'资料','text':'新的材料'}])['context_hash'])

    def test_inspiration_single_attempt_no_session_and_selection_frozen_in_generation(self):
        before=self.store.sessions();g=guide();materials=[{'name':'资料','text':'校园失物招领需发布搜索，不公开联系方式'}]
        body={'guidance':g,'materials':materials,'request_id':'inspire-idempotent-0001'}
        j=self.wait(self.service.submit('inspire',body));self.assertEqual('completed',j['status'],j['error'])
        self.assertEqual(before,self.store.sessions());self.assertEqual(1,len(j['result']['attempts']));self.assertEqual(1,j['result']['call_limit'])
        self.assertEqual(j['id'],self.service.submit('inspire',body)['id']);self.assertEqual(1,len(self.prompts))
        chosen=j['result']['directions'][0]
        selected={**g,'answers':{**g['answers'],'direction':chosen['instruction']},'inspiration':{'job':j['id'],'choice':chosen['id'],'context_hash':j['result']['context_hash']}}
        for wrong in [{**selected,'keep':'换了保留要求'},selected]:
            payload={'goal':wrong['goal'],'task_type':'project','guidance':wrong,'materials':materials if wrong is not selected else []}
            with self.assertRaises(Invalid):self.service.submit('generate',payload)
        generated=self.wait(self.service.submit('generate',{'goal':selected['goal'],'task_type':'project','guidance':selected,'materials':materials}))
        self.assertEqual('completed',generated['status'],generated['error'])
        v=self.store.view(generated['result']['session_id']);self.assertEqual(selected['inspiration'],v['task']['intent_brief']['inspiration']);self.assertEqual(0,v['pair_count'])

    def test_invented_quote_rejected_after_one_request_without_retry(self):
        before=self.store.sessions()
        def transport(path,payload=None):
            value=fixture_transport(path,payload)
            if payload:
                output=json.loads(value['choices'][0]['message']['content']);output['directions'][0]['basis_quotes'][0]['quote']='输入中没有的捏造原文'
                value['choices'][0]['message']['content']=json.dumps(output)
            return value
        self.provider.transport=transport
        j=self.wait(self.service.submit('inspire',{'guidance':guide()}));self.assertEqual('error',j['status']);self.assertIn('原文不一致',j['error']);self.assertEqual(1,len(j['result']['attempts']));self.assertEqual(before,self.store.sessions())

    def test_updated_card_can_explicitly_reconfirm_historical_direction(self):
        g=guide();j=self.wait(self.service.submit('inspire',{'guidance':g}));chosen=j['result']['directions'][0]
        updated={**g,'criteria':'补充新的验收标准','answers':{**g['answers'],'direction':chosen['instruction'],'done':'完整实施方案'}}
        updated['inspiration']={'job':j['id'],'choice':chosen['id'],'context_hash':j['result']['context_hash'],'confirmed_context_hash':prepare(updated,[])['context_hash']}
        job=self.wait(self.service.submit('generate',{'goal':updated['goal'],'task_type':'project','guidance':updated}))
        self.assertEqual('completed',job['status'],job['error']);saved=self.store.view(job['result']['session_id'])['task']['intent_brief']['inspiration']
        self.assertNotEqual(saved['context_hash'],saved['confirmed_context_hash'])
        with self.assertRaises(Invalid):self.service.submit('generate',{'goal':updated['goal'],'task_type':'project','guidance':{**updated,'keep':'确认后再次改动'}})

    def test_trace_lexical_matches_and_negation_never_automatically_pass(self):
        sid=self.store.create(task());v=self.store.view(sid);before=self.store.audit(sid);before.pop('exported_at')
        r=report(v['task'],v['state']);positive=r['rows'][1];negative=r['rows'][0]
        self.assertEqual('needs_review',positive['status']);self.assertEqual('needs_review',negative['status'])
        self.assertIn('不支持',negative['evidence'][0]['quote']);self.assertEqual('search',negative['evidence'][0]['block'])
        self.assertEqual('recovery',positive['evidence'][0]['block']);self.assertEqual('needs_input',r['rows'][2]['status'])
        for row in r['rows']:
            for e in row['evidence']:
                text=next(b for b in v['task']['blocks'] if b['id']==e['block'])['variants'][0]['template'];self.assertIn(e['quote'],text)
        after=self.store.audit(sid);after.pop('exported_at');self.assertEqual(before,after)

    def test_reviews_validate_evidence_and_cannot_confirm_unknown_or_wrong_snapshot(self):
        sid=self.store.create(task());v=self.store.view(sid);rows=report(v['task'],v['state'])['rows']
        for row,blocks in [(rows[0],[]),(rows[2],['intro'])]:
            with self.assertRaises(Invalid):self.review(sid,row,blocks=blocks)
        with self.assertRaises(Invalid):self.action(sid,'requirement_review',requirement=rows[0]['id'],decision='met',blocks=['intro'],snapshot_hash='stale')
        self.review(sid,rows[1]);v=self.store.view(sid);self.assertEqual('user_met',report(v['task'],v['state'])['rows'][1]['status']);self.assertEqual(0,v['pair_count'])

    def test_gap_prevents_usable_claim_and_changes_expire_confirmations(self):
        sid=self.store.create(task());v=self.store.view(sid);rows=report(v['task'],v['state'])['rows']
        self.review(sid,rows[1]);self.review(sid,rows[0],'gap',[])
        with self.assertRaises(Invalid):self.action(sid,'review',checks={'read_through':True,'facts_checked':True,'usable':True})
        v=self.store.view(sid);self.assertEqual('user_met',report(v['task'],v['state'])['rows'][1]['status'])
        blocks=copy.deepcopy(v['task']['blocks']);blocks[2]['variants'][0]['template']+=' 补充一个恢复动作。';self.action(sid,'edit',blocks=blocks)
        v=self.store.view(sid);r=report(v['task'],v['state']);self.assertTrue(r['rows'][1]['stale_review']);self.assertNotEqual('user_met',r['rows'][1]['status'])
        self.action(sid,'undo');v=self.store.view(sid);self.assertEqual('user_met',report(v['task'],v['state'])['rows'][1]['status'])

    def test_material_or_title_change_expires_reviews_and_zip_contains_current_evidence(self):
        sid=self.store.create(task());v=self.store.view(sid);row=report(v['task'],v['state'])['rows'][1];self.review(sid,row)
        self.service.update_materials(sid,{'revision':self.store.view(sid)['revision'],'materials':[{'name':'资料','text':'新增资料'}]})
        v=self.store.view(sid);self.assertTrue(report(v['task'],v['state'])['rows'][1]['stale_review']);self.review(sid,row)
        blocks=copy.deepcopy(self.store.view(sid)['task']['blocks']);blocks[2]['title']='恢复新标题';self.action(sid,'edit',blocks=blocks)
        v=self.store.view(sid);self.assertTrue(report(v['task'],v['state'])['rows'][1]['stale_review']);self.review(sid,row)
        v=self.store.view(sid);output=self.service.export(sid,v['revision'],'zip')
        with zipfile.ZipFile(output['path']) as z:
            exported=json.loads(z.read('需求逐项核对.json'));self.assertEqual('user_met',exported['rows'][1]['status']);self.assertEqual(report(v['task'],v['state'])['snapshot_hash'],exported['snapshot_hash'])

    def test_real_local_semantic_lookup_is_read_only_and_not_acceptance(self):
        try:
            from research.semantic import availability
        except ImportError:self.skipTest('optional semantic dependencies unavailable')
        if not availability()['available']:self.skipTest('optional local semantic files unavailable')
        sid=self.store.create(task());v=self.store.view(sid);r=report(v['task'],v['state']);before=self.store.audit(sid);before.pop('exported_at')
        result=self.store.requirement_evidence(sid,{'revision':v['revision'],'snapshot_hash':r['snapshot_hash'],'requirement':r['rows'][1]['id']})
        self.assertFalse(result['automatic_pass']);self.assertTrue(result['model']['frozen']);self.assertTrue(result['evidence']);self.assertLessEqual(result['examined_chunks'],60)
        after=self.store.audit(sid);after.pop('exported_at');self.assertEqual(before,after)
        self.assertEqual('needs_review',report(v['task'],v['state'])['rows'][1]['status'])

    def test_semantic_lookup_rejects_stale_input_and_midflight_content_changes(self):
        sid=self.store.create(task());v=self.store.view(sid);r=report(v['task'],v['state'])
        payload={'revision':v['revision'],'snapshot_hash':r['snapshot_hash'],'requirement':r['rows'][1]['id']}
        with self.assertRaises(Conflict):self.store.requirement_evidence(sid,{**payload,'revision':-1})
        def update(*args):
            self.action(sid,'select',block='intro',variant='v1');return {'evidence':[]}
        with patch('ai.requirement_trace.semantic_evidence',side_effect=update):
            with self.assertRaises(Conflict):self.store.requirement_evidence(sid,payload)

    def test_semantic_long_document_budget_is_bounded_and_disclosed(self):
        try:
            import research.semantic
        except ImportError:self.skipTest('optional semantic dependencies unavailable')
        from types import SimpleNamespace
        from ai.requirement_trace import semantic_evidence
        class Vector:
            def __matmul__(self,other):return .5
        fake=SimpleNamespace(metadata={'frozen':True},fingerprint='fixture',encode=lambda texts:[Vector() for _ in texts])
        with patch('research.semantic.encoder',return_value=fake):
            r=semantic_evidence('恢复步骤',[{'block':'b'+str(i),'title':'章节','text':'甲'*40000} for i in range(6)])
        self.assertEqual(60,r['examined_chunks']);self.assertTrue(r['sampled']);self.assertGreater(r['total_chunks'],60)
        self.assertFalse(r['automatic_pass'])

    def test_unknown_answer_updates_requirements_without_changing_body_or_labels_and_undo_restores(self):
        sid=self.store.create(task());v=self.store.view(sid);r=report(v['task'],v['state']);unknown=next(r for r in r['rows'] if r['kind']=='unknown')
        self.action(sid,'requirement_answer',requirement=unknown['id'],snapshot_hash=r['snapshot_hash'],answer='由项目负责人维护')
        after=self.store.view(sid);trace=report(after['task'],after['state'])
        self.assertEqual(v['text'],after['text']);self.assertEqual(0,after['pair_count']);self.assertEqual(0,trace['counts'].get('needs_input',0));self.assertTrue(any(r['text']=='由项目负责人维护' and r['kind']=='intent' for r in trace['rows']))
        self.action(sid,'undo');self.assertEqual(v['task']['intent_brief'],self.store.view(sid)['task']['intent_brief'])

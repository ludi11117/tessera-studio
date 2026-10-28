import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.acceptance import evaluate, suggest, validate
from ai.provider import Settings, SiliconFlow
from ai.service import AIService
from core import Invalid, feasible
from store import Conflict, Store
from ai_fixture import fixture_transport


def task():
    return {'title':'组合验收样本','brief':'按资料写建议','source':'generated','category':'analysis','facts':{},
            'blocks':[{'id':bid,'title':bid,'variants':[{'id':bid+str(i),'template':char*n} for i,n in enumerate([10,30,50])]}
                      for bid,char in [('left','甲'),('right','乙')]]}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/CodexWork/temp/intent-acceptance-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'qa.sqlite3')
        self.env=patch.dict(os.environ,{'INTENT_SILICONFLOW_API_KEY':'test-only'});self.env.start();self.addCleanup(self.env.stop)
        self.settings=Settings(Path(self.temp.name)/'private');self.settings.save({'model':'test/fixture'})
        self.provider=SiliconFlow(self.settings,transport=fixture_transport)
        self.service=AIService(self.store,self.provider);self.service.settings=self.settings;self.addCleanup(self.service.close)
        self.sid=self.store.create(task())

    def action(self,kind,**body):
        return self.store.action(self.sid,{'revision':self.store.view(self.sid)['revision'],'kind':kind,**body})

    def wait(self,job):
        for _ in range(200):
            result=self.service.public_job(job['id'])
            if result['status'] not in ('queued','running'):return result
            time.sleep(.01)
        self.fail('job timeout')

    def confirm(self,**kwargs):
        self.action('acceptance',contract={'length':None,'days':None,'required':[],'forbidden':[],'manual':[],**kwargs})

    def test_composition_search_filters_before_preference_and_preserves_labels(self):
        # Feedback is recorded through the same explicit offer/compare path as the UI.
        offer=self.store.offer(self.sid,0);self.action('compare',offer=offer['id'],choice='b')
        self.confirm(length={'min':40,'max':40})
        view=self.store.view(self.sid)
        self.assertEqual(1,view['pair_count']);self.assertEqual(2,view['feasible_count'])
        self.assertEqual(9,view['optimization']['searched'])
        for rank in view['ranking']:
            self.assertTrue(evaluate(view['task'],rank['combo'],view['state']['acceptance'])['machine_passed'])
            self.assertNotEqual(rank['combo']['left'][-1],rank['combo']['right'][-1])
        with self.assertRaises(Invalid):self.action('apply',combo={'left':'left2','right':'right2'})
        self.action('apply',combo=view['ranking'][0]['combo'])
        self.assertEqual(1,self.store.view(self.sid)['pair_count'])
        self.action('undo');self.action('undo')
        self.assertNotIn('acceptance',self.store.view(self.sid)['state'])

    def test_no_solution_and_locked_conflict_are_explicit(self):
        self.action('lock',block='left');self.action('lock',block='right')
        self.confirm(length={'min':40,'max':40});view=self.store.view(self.sid)
        self.assertEqual([],view['ranking']);self.assertEqual(0,view['feasible_count'])
        with self.assertRaises(Invalid):self.service.export(self.sid,view['revision'],'zip')
        with self.assertRaises(Invalid):self.service.submit('repair',{'revision':view['revision']},self.sid)

    def test_contract_validates_phrases_and_does_not_infer_semantics(self):
        with self.assertRaises(Invalid):validate({'required':['x'],'forbidden':['x']})
        with self.assertRaises(Invalid):validate({'days':True})
        t=task();t['brief']='写160–220字邮件';self.assertEqual({'min':160,'max':220},suggest(t)['length'])
        c=validate({'days':7});t['blocks'][0]['variants'][0]['template']='第1–7天学习'
        r=evaluate(t,{'left':'left0','right':'right0'},c)
        self.assertFalse(r['machine_passed']);self.assertIn(1,r['failures'][0]['actual']['missing'])

    def test_repair_then_independent_recheck_is_proposal_and_roundtrip(self):
        self.action('lock',block='right');self.confirm(required=['尚未确认'])
        before=self.store.view(self.sid)
        job=self.wait(self.service.submit('repair',{'revision':before['revision']},self.sid))
        self.assertEqual('completed',job['status'],job['error']);result=job['result']
        self.assertEqual(3,len(result['attempts']));self.assertEqual(2,len(result['quality_rounds']))
        self.assertFalse(result['quality_rounds'][0]['machine']['machine_passed'])
        self.assertTrue(result['quality_rounds'][1]['machine']['machine_passed'])
        self.assertTrue(result['can_apply']);self.assertEqual(before['text'],self.store.view(self.sid)['text'])
        self.assertEqual(['left'],[d['block'] for d in result['diffs']])
        self.service.apply(job['id'],{'revision':before['revision']});after=self.store.view(self.sid)
        self.assertEqual(0,after['pair_count']);self.assertEqual(before['state']['locks'],after['state']['locks'])
        self.assertTrue(after['task']['ai']['revisions'][-1]['quality_rounds'])
        self.action('undo');self.assertEqual(before['text'],self.store.view(self.sid)['text'])

    def test_invalid_review_keeps_raw_attempts_and_never_becomes_pass(self):
        self.confirm(required=['尚未确认'])
        def transport(path,payload=None):
            r=fixture_transport(path,payload)
            if payload:r['choices'][0]['message']['content']=json.dumps({'findings':[{'block':'left','quote':'不存在原文','reason':'错误引用'}],'uncertain':[]})
            return r
        self.provider.transport=transport;before=self.store.view(self.sid)
        job=self.wait(self.service.submit('repair',{'revision':before['revision']},self.sid))
        self.assertEqual('error',job['status']);self.assertEqual(1,len(job['result']['attempts']))
        self.assertIn('output',job['result']['attempts'][0]);self.assertEqual(before['text'],self.store.view(self.sid)['text'])

    def test_semantic_failures_block_adoption_even_when_machine_passes(self):
        self.confirm(required=['尚未确认']);original=self.provider.transport
        def transport(path,payload=None):
            r=original(path,payload)
            if payload:
                request=json.loads(payload['messages'][-1]['content'])
                if request['operation']=='独立验收当前文稿':
                    r['choices'][0]['message']['content']=json.dumps({'findings':[{'block':'right','quote':'乙','reason':'开发模拟语义问题未解决','evidence_ids':[]}],'uncertain':[]})
            return r
        self.provider.transport=transport;self.action('lock',block='right');before=self.store.view(self.sid)
        job=self.wait(self.service.submit('repair',{'revision':before['revision']},self.sid))
        self.assertEqual('completed',job['status'],job['error']);self.assertFalse(job['result']['can_apply'])
        self.assertEqual('issues_remain',job['result']['quality_status']);self.assertEqual(3,len(job['result']['attempts']))
        self.assertTrue(job['result']['blocked_findings'])
        with self.assertRaises(Invalid):self.service.apply(job['id'],{'revision':before['revision']})

    def test_repair_uses_frozen_state_and_rejects_stale_adoption(self):
        self.confirm(required=['尚未确认']);before=self.store.view(self.sid)
        job=self.wait(self.service.submit('repair',{'revision':before['revision']},self.sid))
        self.confirm(required=['另一个要求'])
        with self.assertRaises(Conflict):self.service.apply(job['id'],{'revision':before['revision']})
        self.assertEqual(['尚未确认'],self.service.job(job['id'])['input']['view']['state']['acceptance']['required'])

    def test_generation_rechecks_numeric_failures_and_retains_both_outputs(self):
        original=self.provider.transport;count=[0]
        def transport(path,payload=None):
            if not payload:return original(path,payload)
            count[0]+=1
            texts=['甲'*20,'乙'*21,'丙'*22] if count[0]==1 else ['甲'*45,'乙'*46,'丙'*47]
            return {'choices':[{'message':{'content':json.dumps({'title':'短写作','artifact_type':'writing','blocks':[{'title':'正文','variants':texts}]})},'finish_reason':'stop'}]}
        self.provider.transport=transport
        job=self.wait(self.service.submit('generate',{'goal':'请写40–50字的简短邀请说明','task_type':'writing'}))
        self.assertEqual('completed',job['status'],job['error']);r=job['result']
        self.assertEqual(2,len(r['attempts']));self.assertEqual(2,len(r['quality_rounds']))
        self.assertTrue(all(c['machine_passed'] for c in r['quality_rounds'][-1]['candidates']))
        self.assertFalse(r['quality_rounds'][0]['candidates'][0]['machine_passed'])
        self.assertEqual(3,r['call_limit'])

    def test_closed_source_number_rule_is_optional_and_not_a_fact_checker(self):
        t=task();t['materials']=[{'id':'M1','name':'原记录','text':'首次导入80秒，峰值420MB。'}]
        t['blocks'][0]['variants'][0]['template']='总大小50MB；首次80秒；假定90秒。'
        combo={'left':'left0','right':'right0'}
        self.assertTrue(evaluate(t,combo,validate({}))['machine_passed'])
        r=evaluate(t,combo,validate({'source_numbers':True}))
        self.assertFalse(r['machine_passed'])
        self.assertEqual(['50MB','90秒'],[m['literal'] for m in r['failures'][0]['actual']])
        # Same numeric wording, wrong relation: intentionally outside this predicate.
        t['blocks'][0]['variants'][0]['template']='峰值80秒。'
        self.assertTrue(evaluate(t,combo,validate({'source_numbers':True}))['machine_passed'])

    def test_failed_budget_and_unchanged_review_are_not_silently_retried(self):
        self.confirm(required=['尚未确认']);before=self.store.view(self.sid)
        job=self.wait(self.service.submit('repair',{'revision':before['revision']},self.sid))
        inputs=self.service.job(job['id'])['input']
        with self.assertRaises(Invalid):self.service.ask(job['id'],inputs,{'operation':'预算后不允许调用'})
        self.assertEqual(3,len(self.service.job(job['id'])['result']['attempts']))

    def test_length_plan_allocates_only_unlocked_text_and_joins_emitted_sentences(self):
        from ai.quality_loop import correction_plan
        from ai.service_helpers import normalize_changes
        t=task();state={'combo':{'left':'left0','right':'right0'},'locks':{'right':'right0'},'acceptance':validate({'length':{'min':50,'max':70}})}
        p=correction_plan(t,state,['left'])
        self.assertEqual(10,p['protected_characters']);self.assertEqual(50,p['allocations'][0]['target_characters'])
        blocks,_=normalize_changes(t,state,[{'block':'left','sentences':['一句。','二句。']}],['left'],[])
        self.assertEqual('一句。二句。',blocks[0]['variants'][0]['template'])
        self.assertEqual(t['blocks'][1],blocks[1])

    def test_malformed_response_is_preserved_without_headers(self):
        self.confirm()
        def transport(path,payload=None):
            return {'choices':[{'message':{'content':'{broken-json'},'finish_reason':'stop'}],'usage':{'total_tokens':5},'authorization':'should-not-be-recorded'}
        self.provider.transport=transport
        job=self.wait(self.service.submit('repair',{'revision':self.store.view(self.sid)['revision']},self.sid))
        self.assertEqual('error',job['status'])
        raw=job['result']['attempts'][0]['raw_response']
        self.assertEqual('{broken-json',raw['choices'][0]['message']['content']);self.assertNotIn('authorization',raw)

    def test_uncertainty_suggestions_are_literal_and_reviews_expire_on_edit(self):
        t=task();t['materials']=[{'id':'M1','name':'安排','text':'预计开放。最终人数尚未确认，未约定费用。'}]
        self.assertEqual(['最终人数尚未确认','未约定费用'],suggest(t)['required'])
        self.confirm(required=['尚未确认']);v=self.store.view(self.sid)
        job=self.wait(self.service.submit('repair',{'revision':v['revision']},self.sid))
        self.service.apply(job['id'],{'revision':v['revision']})
        self.assertTrue(self.service.delivery(self.sid)['acceptance']['latest_review']['current'])
        self.confirm(required=['尚未确认'],manual=['需要新增核对'])
        self.assertFalse(self.service.delivery(self.sid)['acceptance']['latest_review']['current'])

    def test_preference_dataset_preserves_confirmed_acceptance_context(self):
        from research.dataset import build_dataset
        self.confirm(length={'min':20,'max':65});v=self.store.view(self.sid)
        offer=self.store.offer(self.sid,v['revision'])
        self.assertEqual(v['state']['acceptance'],offer['snapshot']['acceptance'])
        self.action('compare',offer=offer['id'],choice='b')
        labels,_=build_dataset(self.store.audit(self.sid))
        self.assertEqual(v['state']['acceptance'],labels[0]['constraint']['acceptance'])

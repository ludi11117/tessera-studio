import copy
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ai.guidance import CATALOG, context, normalize
from ai.provider import Settings, SiliconFlow
from ai.service import AIService
from ai_fixture import fixture_transport
from core import Invalid, enumerate_feasible, render_variant, variant_for
from store import Conflict, Store


def brief():
    return {'version':'guided-intent-v1','confirmed':True,'category':'writing','goal':'写邮件',
            'answers':{'audience':'合作对象','outcome':None,'direction':'语气温和，留出协商空间'},
            'keep':'保留未确认的信息','change':'不要新增承诺','criteria':'给出完整正文','api_key':'must-not-store'}


def task():
    return {'title':'局部保留开发样本','source':'example','category':'writing','brief':'测试原文保留','facts':{},
            'blocks':[{'id':'intro','title':'来意','variants':[{'id':'v'+str(i),'template':s} for i,s in enumerate(['保留这句。其他内容可改。','另一个来意。','保留这句。换一种后续。'])]},
                      {'id':'end','title':'结尾','variants':[{'id':'v'+str(i),'template':s} for i,s in enumerate(['请回复。','保留这句。放在别章不算。','期待交流。'])]}]}


class JourneyTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/CodexWork/temp/intent-journey-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.store=Store(self.folder/'qa.sqlite3')
        env=patch.dict(os.environ,{'INTENT_SILICONFLOW_API_KEY':'journey-fixture-not-real'});env.start();self.addCleanup(env.stop)
        self.settings=Settings(self.folder/'private');self.settings.save({'model':'test/fixture-model'})
        self.prompts=[]
        def transport(path,payload=None):
            if payload:self.prompts.append(json.loads(payload['messages'][-1]['content']))
            return fixture_transport(path,payload)
        self.provider=SiliconFlow(self.settings,transport=transport);self.service=AIService(self.store,self.provider);self.service.settings=self.settings;self.addCleanup(self.service.close)

    def wait(self,job):
        for _ in range(500):
            j=self.service.public_job(job['id'])
            if j['status'] not in ('queued','running'):return j
            time.sleep(.01)
        self.fail('Timed out')

    def action(self,sid,kind,**kw):return self.store.action(sid,{'kind':kind,'revision':self.store.view(sid)['revision'],**kw})

    def test_guidance_validation_unknowns_and_all_project_catalogs(self):
        clean=normalize(brief(),'写邮件');self.assertNotIn('api_key',clean)
        c=context(clean);self.assertEqual(2,len(c['explicit_answers']));self.assertEqual(2,len(c['unresolved']))
        self.assertNotIn('回复或确认',json.dumps(c,ensure_ascii=False))
        for category,item in CATALOG.items():
            self.assertEqual(4,len(item['questions']));self.assertTrue(any(q.get('examples') for q in item['questions']))
            self.assertEqual(category,normalize({**brief(),'category':category,'answers':{}})['category'])
        for value in [{**brief(),'answers':{'unknown':'abc'}},{**brief(),'confirmed':'yes'},{**brief(),'keep':'a'*1001}]:
            with self.assertRaises(Invalid):normalize(value)
        with self.assertRaises(Invalid):normalize(brief(),'完全不同的目标')

    def test_guidance_draft_roundtrip_and_generation_provenance(self):
        value={'goal':'写邮件','task_type':'writing','guidance':brief()}
        saved=self.service.draft({'revision':0,'input':value})
        self.assertNotIn('api_key',saved['input']['guidance'])
        self.assertEqual(saved,self.service.draft())
        for guidance in [{**brief(),'confirmed':False},{**brief(),'goal':'旧目标'}]:
            with self.assertRaises(Invalid):self.service.submit('generate',{**value,'guidance':guidance})
        with self.assertRaises(Invalid):self.service.submit('generate',{**value,'task_type':'study'})
        j=self.wait(self.service.submit('generate',value));self.assertEqual('completed',j['status'],j['error'])
        sid=j['result']['session_id'];view=self.store.view(sid)
        self.assertEqual(context(normalize(brief())),self.prompts[0]['intent_brief'])
        self.assertEqual(self.prompts[0]['intent_brief'],view['task']['intent_brief'])
        self.assertEqual(0,view['pair_count'])
        exported=self.service.export(sid,view['revision'],'zip')
        with zipfile.ZipFile(exported['path']) as z:
            record=json.loads(z.read('需求与局部保留.json'));self.assertEqual(view['task']['intent_brief'],record['intent_brief'])

    def test_fragment_search_is_exact_chapter_local_and_not_training(self):
        sid=self.store.create(task());before=self.store.view(sid)
        self.action(sid,'preserve_fragment',block='intro',text='保留这句。')
        v=self.store.view(sid);self.assertEqual(before['text'],v['text']);self.assertEqual(0,v['pair_count']);self.assertNotIn('intro',v['state']['locks'])
        expected=[c for c in enumerate_feasible(v['task'],{**v['state'],'preserved_fragments':[]}) if '保留这句。' in render_variant(v['task'],variant_for(v['task'],'intro',c['intro']))]
        self.assertEqual(expected,enumerate_feasible(v['task'],v['state']));self.assertEqual(6,len(expected))
        d=self.store.decision(sid,v['revision']);self.assertEqual(6,d['eligible']);self.assertTrue(any(c['kind']=='fragment' for c in d['constraints']))
        with self.assertRaises(Invalid):self.action(sid,'apply',combo={'intro':'v1','end':'v1'})
        self.action(sid,'select',block='intro',variant='v2')
        self.action(sid,'preserve_fragment',block='intro',text='保留这句。',remove=True)
        self.assertEqual(9,len(enumerate_feasible(task(),self.store.view(sid)['state'])))
        self.action(sid,'undo');self.assertEqual(1,len(self.store.view(sid)['state']['preserved_fragments']))

    def test_fragment_manual_edit_atomicity_validation_and_stale_requests(self):
        sid=self.store.create(task());rev=self.store.view(sid)['revision']
        for block,text in [('intro','不存在'),('missing','保留这句。'),('intro','')]:
            with self.assertRaises(Invalid):self.action(sid,'preserve_fragment',block=block,text=text)
        self.action(sid,'preserve_fragment',block='intro',text='保留这句。')
        with self.assertRaises(Conflict):self.store.action(sid,{'kind':'preserve_fragment','revision':rev,'block':'intro','text':'其他内容'})
        before=self.store.view(sid);blocks=copy.deepcopy(before['task']['blocks']);blocks[0]['variants'][0]['template']='删掉喜欢的内容。'
        with self.assertRaises(Invalid):self.action(sid,'edit',blocks=blocks)
        self.assertEqual(before['text'],self.store.view(sid)['text'])
        blocks[0]['variants'][0]['template']='重写开头。保留这句。其他句子有调整。'
        self.action(sid,'edit',blocks=blocks);self.assertIn('重写开头',self.store.view(sid)['text'])
        self.assertEqual(0,self.store.view(sid)['pair_count'])

    def test_ai_proposal_cannot_drop_fragment_but_can_rewrite_remainder(self):
        sid=self.store.create(task());self.action(sid,'preserve_fragment',block='intro',text='保留这句。')
        def transport(path,payload=None):
            if payload:
                prompt=json.loads(payload['messages'][-1]['content']);self.prompts.append(prompt)
                text='新内容，删掉了原文。' if len(self.prompts)==1 else '保留这句。其他文字重新组织。'
                return {'choices':[{'message':{'content':json.dumps({'summary':'修改','changes':[{'block':'intro','text':text}]})}}]}
            return fixture_transport(path,payload)
        self.provider.transport=transport;v=self.store.view(sid)
        body={'revision':v['revision'],'instruction':'调整其余文字','scope':['intro']}
        bad=self.wait(self.service.submit('revise',body,sid));self.assertEqual('completed',bad['status'],bad['error'])
        self.assertFalse(bad['result']['can_apply']);self.assertIn('局部原文',bad['result']['validation_message'])
        with self.assertRaises(Invalid):self.service.apply(bad['id'],{'revision':v['revision']})
        good=self.wait(self.service.submit('revise',body,sid));self.assertTrue(good['result']['can_apply'],good['error'])
        self.assertEqual(v['state']['preserved_fragments'],self.prompts[0]['preserved_fragments'])
        self.assertEqual(v['text'],self.store.view(sid)['text'])
        self.service.apply(good['id'],{'revision':v['revision']});self.assertIn('其他文字重新组织',self.store.view(sid)['text'])
        self.assertEqual(0,self.store.view(sid)['pair_count'])

    def test_repair_helper_and_conflicts_honor_partial_preservation(self):
        from ai.service_helpers import normalize_changes
        sid=self.store.create(task());self.action(sid,'preserve_fragment',block='intro',text='保留这句。')
        v=self.store.view(sid)
        with self.assertRaises(Invalid):normalize_changes(v['task'],v['state'],[{'block':'intro','text':'删除了保留句。'}],['intro'],[])
        blocks,_=normalize_changes(v['task'],v['state'],[{'block':'intro','text':'保留这句。其余内容改写。'}],['intro'],[])
        self.assertTrue(blocks[0]['variants'][0]['template'].endswith('其余内容改写。'))
        # A contradictory acceptance condition must expose the literal and the
        # acceptance predicate, with no automatic relaxation or state mutation.
        self.action(sid,'acceptance',contract={'forbidden':['保留这句。']})
        v=self.store.view(sid);d=self.store.decision(sid,v['revision'])
        self.assertEqual(0,d['eligible']);self.assertEqual({'fragment','acceptance'},{c['kind'] for c in d['conflict_core']})
        self.assertEqual(2,d['correction_count']);self.assertTrue(all(not c['adoptable_under_current_conditions'] for c in d['corrections']))

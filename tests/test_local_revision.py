import copy
import json
import unittest
from unittest.mock import patch
import test_context_trace as helpers
from ai.local_revision import prepare
from core import Invalid, render_variant, variant_for
from store import Conflict


def task(facts=False):
    text='开头🙂。重复句。重复句。结尾。'
    if facts:text='{{person}}，'+text
    return {'title':'局部替换开发样本','source':'example','category':'writing','brief':'仅改所选的一处','facts':{'person':'林老师'} if facts else {},
            'blocks':[{'id':'intro','title':'来意','variants':[{'id':'v'+str(i),'template':text+str(i)} for i in range(3)]},
                      {'id':'end','title':'结尾','variants':[{'id':'v'+str(i),'template':'其他章节保持原样。'+str(i)} for i in range(3)]}]}


class LocalRevisionTests(unittest.TestCase):
    setUp=helpers.ContextTraceTests.setUp
    wait=helpers.ContextTraceTests.wait
    action=helpers.ContextTraceTests.action

    def payload(self,sid,text='重复句。',action='alternatives',last=True):
        v=self.store.view(sid);whole=render_variant(v['task'],variant_for(v['task'],'intro',v['state']['combo']['intro']))
        start=whole.rfind(text) if last else whole.find(text)
        return {'revision':v['revision'],'selection':{'block':'intro','variant':v['state']['combo']['intro'],'start':start,'end':start+len(text),'text':text},'action':action}

    def test_exact_second_occurrence_and_unicode_selection_changes_only_that_range(self):
        sid=self.store.create(task());before=self.store.view(sid);body=self.payload(sid)
        j=self.wait(self.service.submit('local_revise',body,sid));self.assertEqual('completed',j['status'],j['error'])
        self.assertEqual(1,j['result']['call_limit']);self.assertEqual(1,len(j['result']['attempts']));self.assertEqual(2,len(j['result']['options']))
        target=j['result']['target'];chosen=j['result']['options'][1]
        expected=target['before'][:target['start']]+chosen['replacement']+target['before'][target['end']:]
        self.assertEqual(expected,chosen['after']);self.assertTrue(chosen['outside_unchanged'])
        self.assertEqual(before['text'],self.store.view(sid)['text'])
        self.service.apply(j['id'],{'revision':body['revision'],'option':'option-1'})
        after=self.store.view(sid);self.assertEqual(expected,render_variant(after['task'],variant_for(after['task'],'intro',after['state']['combo']['intro'])))
        self.assertEqual(before['state']['combo']['end'],after['state']['combo']['end']);self.assertEqual(0,after['pair_count'])
        self.action(sid,'undo');self.assertEqual(before['text'],self.store.view(sid)['text'])

    def test_invalid_anchor_locked_section_and_stale_variant_rejected_before_call(self):
        sid=self.store.create(task());body=self.payload(sid)
        for selection in [{**body['selection'],'start':True},{**body['selection'],'text':'不存在'},{**body['selection'],'end':9999}]:
            with self.assertRaises(Invalid):self.service.submit('local_revise',{**body,'selection':selection},sid)
        with self.assertRaises(Conflict):self.service.submit('local_revise',{**body,'selection':{**body['selection'],'variant':'old'}},sid)
        self.action(sid,'lock',block='intro');locked=self.payload(sid)
        with self.assertRaises(Invalid):self.service.submit('local_revise',locked,sid)
        self.assertEqual([],self.prompts)

    def test_losing_preserved_fragment_cannot_apply_and_does_not_retry(self):
        sid=self.store.create(task());self.action(sid,'preserve_fragment',block='intro',text='开头🙂。')
        def transport(path,payload=None):return {'choices':[{'message':{'content':json.dumps({'options':[{'label':'不保留原文','replacement':'不同的开头'}]})}}]}
        self.provider.transport=transport;body=self.payload(sid,'开头🙂。','concise')
        j=self.wait(self.service.submit('local_revise',body,sid));self.assertEqual('completed',j['status'],j['error']);self.assertFalse(j['result']['options'][0]['can_apply'])
        with self.assertRaises(Invalid):self.service.apply(j['id'],{'revision':body['revision'],'option':'option-0'})
        self.assertEqual(1,len(j['result']['attempts']));self.assertIn('开头🙂。',self.store.view(sid)['text'])

    def test_fact_values_and_outside_text_are_not_silently_rewritten(self):
        sid=self.store.create(task(True));body=self.payload(sid,'重复句。','detail')
        j=self.wait(self.service.submit('local_revise',body,sid));self.assertTrue(j['result']['options'][0]['can_apply'],j['error'])
        before=self.store.view(sid)['text'];self.service.apply(j['id'],{'revision':body['revision'],'option':'option-0'})
        self.assertTrue(self.store.view(sid)['text'].startswith('林老师，开头🙂。'))
        body=self.payload(sid,'林老师','tone')
        self.provider.transport=lambda *args,**kwargs:{'choices':[{'message':{'content':json.dumps({'options':[{'label':'改事实','replacement':'王老师'}]})}}]}
        j=self.wait(self.service.submit('local_revise',body,sid));self.assertFalse(j['result']['options'][0]['can_apply'])

    def test_state_change_after_proposal_blocks_apply(self):
        sid=self.store.create(task());body=self.payload(sid)
        j=self.wait(self.service.submit('local_revise',body,sid));self.action(sid,'lock',block='end')
        with self.assertRaises(Conflict):self.service.apply(j['id'],{'revision':body['revision'],'option':'option-0'})
        self.assertEqual(0,self.store.view(sid)['pair_count'])

    def test_model_cannot_supply_other_chapter_changes_and_wrong_count_fails_once(self):
        sid=self.store.create(task());body=self.payload(sid,action='concise')
        self.provider.transport=lambda *args,**kwargs:{'choices':[{'message':{'content':json.dumps({'options':[{'label':'一版','replacement':'替换文字','blocks':[{'id':'end','text':'越界'}]}]})}}]}
        j=self.wait(self.service.submit('local_revise',body,sid));self.assertTrue(j['result']['options'][0]['can_apply']);self.assertNotIn('越界',j['result']['options'][0]['after'])
        self.provider.transport=lambda *args,**kwargs:{'choices':[{'message':{'content':json.dumps({'options':[]})}}]}
        j=self.wait(self.service.submit('local_revise',body,sid));self.assertEqual('error',j['status']);self.assertEqual(1,len(j['result']['attempts']))
        with self.assertRaises(Invalid):self.service.retry(j['id'],{})

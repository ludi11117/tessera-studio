import json
import unittest
from pathlib import Path
import test_context_trace as helpers
from test_webcraft import brief
from webcraft.store import WebStore
from core import Invalid
from store import Conflict

class WebCopyTests(unittest.TestCase):
    setUp=helpers.ContextTraceTests.setUp
    wait=helpers.ContextTraceTests.wait
    def page(self):
        self.pages=WebStore(Path(self.store.path).parent/'websites.sqlite3');return self.pages.create(brief())
    def body(self,v):return {'site_id':v['id'],'revision':v['revision'],'component':'hero','instruction':'表达更具体，保留事实'}
    def test_one_call_two_options_preview_no_mutation_and_atomic_apply(self):
        v=self.page();body=self.body(v);j=self.wait(self.service.submit('web_copy',body));self.assertEqual('completed',j['status'],j['error']);self.assertEqual(1,len(j['result']['attempts']));self.assertEqual(1,j['result']['call_limit']);self.assertEqual(v,self.pages.view(v['id']))
        self.service.apply(j['id'],{'revision':0,'option':'0'});after=self.pages.view(v['id']);self.assertEqual(1,after['revision']);self.assertEqual(j['id'],after['history'][0]['evidence']['job_id']);self.assertTrue(after['history'][0]['evidence']['outside_unchanged'])
        with self.assertRaises(Invalid):self.service.apply(j['id'],{'revision':0,'option':'0'})
    def test_protected_before_call_and_concurrent_edit_rejects_adoption(self):
        v=self.page();j=self.wait(self.service.submit('web_copy',self.body(v)));v=self.pages.action(v['id'],{'revision':0,'kind':'protect','component':'hero','field':'content','enabled':True})
        with self.assertRaises(Conflict):self.service.apply(j['id'],{'revision':0,'option':'0'})
        n=len(self.prompts)
        with self.assertRaises(Invalid):self.service.submit('web_copy',self.body(v))
        self.assertEqual(n,len(self.prompts))
    def test_model_cannot_change_schema_or_contact_url(self):
        v=self.page();body={**self.body(v),'component':'contact'}
        content=v['document']['components']['contact']['content']
        self.provider.transport=lambda *a,**kw:{'choices':[{'message':{'content':json.dumps({'options':[{'label':'a','content':{**content,'url':'https://example.com'}},{'label':'b','content':{**content,'script':'bad'}}]})}}]}
        j=self.wait(self.service.submit('web_copy',body));self.assertEqual('completed',j['status'],j['error']);self.assertTrue(all(not o['can_apply'] for o in j['result']['options']));self.assertEqual(0,self.pages.view(v['id'])['revision'])
    def test_invalid_output_single_failure_no_retry(self):
        v=self.page();self.provider.transport=lambda *a,**kw:{'choices':[{'message':{'content':'{"options": []}'}}]}
        j=self.wait(self.service.submit('web_copy',self.body(v)));self.assertEqual('error',j['status']);self.assertEqual(1,len(j['result']['attempts']))
        with self.assertRaises(Invalid):self.service.retry(j['id'],{})

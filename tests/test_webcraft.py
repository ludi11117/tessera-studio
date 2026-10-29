import copy
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from webcraft.model import create,patch,digest,receipt
from webcraft.render import render
from webcraft.store import WebStore
from core import Invalid
from store import Conflict

def brief():return {'name':'测试作品','title':'把想法变成作品','brief':'用于明确标注的开发测试。','projects':'地图｜找到教室\n札记｜整理想法'}

class WebcraftTests(unittest.TestCase):
    def setUp(self):
        folder=Path(os.environ.get('TESSERA_TEST_TEMP','D:/CodexWork/temp/tessera-web-tests') if os.name=='nt' else os.environ.get('TESSERA_TEST_TEMP',tempfile.gettempdir()));folder.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.tmp.cleanup);self.repo=WebStore(Path(self.tmp.name)/'websites.sqlite3');self.v=self.repo.create(brief());self.pid=self.v['id']
    def act(self,kind,**kw):self.v=self.repo.action(self.pid,{'revision':self.v['revision'],'kind':kind,**kw});return self.v
    def edit(self,cid='hero',field='layout',value='editorial'):return [{'component':cid,'field':field,'value':value}]
    def test_protected_property_not_other_properties_and_receipt(self):
        self.act('protect',component='hero',field='layout',enabled=True);before=copy.deepcopy(self.v)
        with self.assertRaises(Invalid):self.act('patch',patches=self.edit())
        self.act('patch',patches=self.edit(field='palette',value='sage'))
        self.assertEqual('quiet',self.v['document']['components']['hero']['layout']);r=self.v['history'][0]['evidence'];self.assertTrue(r['outside_unchanged']);self.assertEqual(11,len(r['outside_patch']));self.assertEqual(['hero.palette'],r['changed_paths']);self.assertEqual(before['document']['components']['nav'],self.v['document']['components']['nav'])
    def test_preview_readonly_stale_patch_atomic_rejection_and_undo(self):
        p=self.repo.preview(self.pid,{'revision':0,'patches':self.edit()});self.assertIn('layout-editorial',p['html']);self.assertEqual(0,self.repo.view(self.pid)['revision'])
        self.act('patch',patches=self.edit());self.assertEqual('editorial',self.v['document']['components']['hero']['layout'])
        with self.assertRaises(Conflict):self.repo.action(self.pid,{'revision':0,'kind':'patch','patches':self.edit(value='compact')})
        before=self.v['document'];bad=self.edit(value='compact')+[{'component':'nav','field':'palette','value':'arbitrary CSS'}]
        with self.assertRaises(Invalid):self.act('patch',patches=bad)
        self.assertEqual(before,self.repo.view(self.pid)['document']);self.act('undo');self.assertEqual('quiet',self.v['document']['components']['hero']['layout'])
    def test_untrusted_text_never_becomes_code_and_links_allowlisted(self):
        b=brief();b['title']='<script>alert(1)</script>';b['name']='"><img src=x onerror=alert(1)>'
        html=render(create(b));self.assertNotIn('<script>',html);self.assertNotIn('<img',html);self.assertIn('&lt;script&gt;',html)
        for url in ['javascript:alert(1)','http://host/x','https://user:pass@example.com','mailto:a@b?body=secret','https://example.com\nfoo']:
            with self.assertRaises(Invalid):create({**brief(),'url':url})
        for url in ['https://example.com/work','mailto:me@example.com']:self.assertIn(url,render(create({**brief(),'url':url})))
    def test_review_snapshot_expiry_export_hashes_and_offline_bundle(self):
        with self.assertRaises(Invalid):self.repo.export(self.pid,{'revision':0})
        self.act('review',confirmed=True,document_hash=digest(self.v['document']));bundle=self.repo.export(self.pid,{'revision':self.v['revision']})
        with zipfile.ZipFile(io.BytesIO(bundle)) as z:
            self.assertEqual({'index.html','project.json','evidence.json','README.txt'},set(z.namelist()));html=z.read('index.html');e=json.loads(z.read('evidence.json'));self.assertEqual(__import__('hashlib').sha256(html).hexdigest(),e['html_sha256']);self.assertNotIn(b'<script',html);self.assertNotIn(b'href="/web-render.css"',html)
        self.act('patch',patches=self.edit());self.assertFalse(self.v['ready'])
        with self.assertRaises(Invalid):self.repo.export(self.pid,{'revision':self.v['revision']})
        self.act('undo');self.assertTrue(self.v['ready'])
    def test_many_patches_preserve_all_untouched_fields(self):
        # Independent field comparison across every layout/palette and component.
        from itertools import product
        from webcraft.model import IDS,LAYOUTS,PALETTES
        original=create(brief())
        for cid,l,p in product(IDS,LAYOUTS,PALETTES):
            if (l,p)==('quiet','paper'):continue
            after,changes=patch(original,[{'component':cid,'field':'layout','value':l},{'component':cid,'field':'palette','value':p}],{})
            for other in IDS:
                self.assertEqual(original['components'][other]['content'],after['components'][other]['content'])
                if other!=cid:self.assertEqual(original['components'][other],after['components'][other])
            self.assertTrue(receipt(original,after,changes)['outside_unchanged'])
    def test_export_requires_exact_revision_and_review_hash(self):
        with self.assertRaises(Conflict):self.act('review',confirmed=True,document_hash='old')
        with self.assertRaises(Conflict):self.repo.preview(self.pid,{'revision':False,'patches':self.edit()})
        self.act('review',confirmed=True,document_hash=digest(self.v['document']))
        with self.assertRaises(Conflict):self.repo.export(self.pid,{'revision':0})

if __name__=='__main__':unittest.main()

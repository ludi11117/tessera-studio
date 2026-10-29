"""Independent artifact database, CAS revisions, append-only audit, exact undo."""
import copy
import io
import json
import sqlite3
import uuid
import zipfile
from contextlib import closing,contextmanager
from pathlib import Path
from core import Invalid
from store import Conflict,now
from webcraft import model
from webcraft.render import render,evidence

def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)

class WebStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db:db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL); CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT, page TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL, evidence TEXT NOT NULL, created TEXT NOT NULL);')
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15,isolation_level=None);db.row_factory=sqlite3.Row;return db
    @contextmanager
    def tx(self):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:yield db;db.commit()
            except Exception:db.rollback();raise
    def load(self,db,pid):
        row=db.execute('SELECT * FROM pages WHERE id=?',(pid,)).fetchone()
        if row is None:raise Invalid('网页项目不存在')
        return row,json.loads(row['state'])
    def create(self,body):
        doc=model.create(body);pid=uuid.uuid4().hex
        with self.tx() as db:db.execute('INSERT INTO pages VALUES(?,?,?,?)',(pid,0,encode({'document':doc,'locks':{},'reviewed':None}),now()))
        return self.view(pid)
    def listing(self):
        with closing(self.connect()) as db:return [{'id':r['id'],'revision':r['revision'],'title':json.loads(r['state'])['document']['components']['nav']['content']['title'],'created':r['created']} for r in db.execute('SELECT * FROM pages ORDER BY created DESC')]
    def view(self,pid):
        with closing(self.connect()) as db:
            row,state=self.load(db,pid);history=[dict(r) for r in db.execute('SELECT revision,kind,evidence,created FROM history WHERE page=? ORDER BY seq DESC LIMIT 30',(pid,))]
        for r in history:r['evidence']=json.loads(r['evidence'])
        return {'id':pid,'revision':row['revision'],**state,'html':render(state['document'],True),'checks':evidence(state['document']),'history':history,'ready':state['reviewed']==model.digest(state['document'])}
    def checked(self,db,pid,revision):
        row,state=self.load(db,pid)
        if type(revision) is not int or revision!=row['revision']:raise Conflict('网页已更新，请刷新后重新预览')
        return state
    def preview(self,pid,body):
        with closing(self.connect()) as db:state=self.checked(db,pid,body.get('revision'))
        after,changes=model.patch(state['document'],body.get('patches'),state['locks'])
        return {'revision':body['revision'],'document':after,'changes':changes,'receipt':model.receipt(state['document'],after,changes),'html':render(after,True)}
    def action(self,pid,body):
        kind=body.get('kind')
        with self.tx() as db:
            before=self.checked(db,pid,body.get('revision'));after=copy.deepcopy(before);proof={}
            if kind=='patch':
                doc,changes=model.patch(before['document'],body.get('patches'),before['locks']);after['document']=doc;after['reviewed']=None;proof=model.receipt(before['document'],doc,changes)
                if body.get('job_id'):proof['job_id']=body['job_id']
            elif kind=='compare':
                from webcraft.preference import feedback
                proof=feedback(after,body)
            elif kind=='protect':
                cid,field=body.get('component'),body.get('field');enabled=body.get('enabled')
                if cid not in model.IDS or field not in ('layout','palette','content') or type(enabled) is not bool:raise Invalid('保留范围无效')
                key=cid+'.'+field
                if enabled:after['locks'][key]=model.digest(before['document']['components'][cid][field])
                else:after['locks'].pop(key,None)
                proof={'path':key,'enabled':enabled}
            elif kind=='review':
                if body.get('document_hash')!=model.digest(before['document']) or body.get('confirmed') is not True:raise Conflict('请核对当前版本的内容和联系地址')
                after['reviewed']=model.digest(before['document']);proof={'document_hash':after['reviewed'],'human_confirmed':True}
            elif kind=='undo':
                events=list(db.execute('SELECT * FROM history WHERE page=? ORDER BY seq DESC',(pid,)))
                undone={json.loads(e['evidence']).get('target') for e in events if e['kind']=='undo'}
                target=next((e for e in events if e['kind']!='undo' and e['seq'] not in undone),None)
                if target is None:raise Invalid('没有可撤回的操作')
                after=json.loads(target['before_state']);proof={'target':target['seq']}
            else:raise Invalid('未知网页操作')
            rev=body['revision']+1
            db.execute('UPDATE pages SET state=?,revision=? WHERE id=?',(encode(after),rev,pid))
            db.execute('INSERT INTO history(page,revision,kind,before_state,after_state,evidence,created) VALUES(?,?,?,?,?,?,?)',(pid,rev,kind,encode(before),encode(after),encode(proof),now()))
        return self.view(pid)
    def preference(self,pid,body):
        from webcraft.preference import analyze,patches
        with closing(self.connect()) as db:state=self.checked(db,pid,body.get('revision'))
        result=analyze(state);result['revision']=body['revision']
        if result['query']:
            for side in ('a','b'):
                doc=copy.deepcopy(state['document'])
                for p in patches(doc,result['query'][side]):doc['components'][p['component']][p['field']]=p['value']
                result['query'][side+'_html']=render(doc,True)
        return result
    def export(self,pid,body):
        with closing(self.connect()) as db:
            db.execute('BEGIN');state=self.checked(db,pid,body.get('revision'));events=[dict(r) for r in db.execute('SELECT revision,kind,evidence,created FROM history WHERE page=? ORDER BY seq',(pid,))]
        if state['reviewed']!=model.digest(state['document']):raise Invalid('请先核对当前网页并确认交付')
        content=render(state['document']);output=io.BytesIO()
        proof={**evidence(state['document']),'revision':body['revision'],'human_confirmed_hash':state['reviewed'],'protected_properties':state['locks'],'events':events}
        from webcraft.preference import analyze
        proof['preference']=analyze(state)
        proof['explicit_comparisons']=state.get('preferences',[])
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            for name,text in [('index.html',content),('project.json',encode(state['document'])),('evidence.json',encode(proof)),('README.txt','双击 index.html 可离线打开，无构建步骤或外部依赖。\nproject.json 为结构化源文件；evidence.json 为当前版本校验记录。\n静态展示页不含表单后端、网站托管或自动事实核验。')]:z.writestr(name,text)
        return output.getvalue()

"""Explicit local training runs and immutable checkpoint registry; no paid calls."""
import copy
import importlib.util
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from core import Invalid,enumerate_feasible,render
from store import Conflict,now

REASONS={'clarity':'表达更清楚','effort':'实施负担更合适','detail':'细节程度更合适','coherence':'整体搭配更协调'}


def availability():
    try:
        from research.semantic import availability as available
        return available()
    except ImportError:return {'available':False,'files_ready':False,'packages_ready':False,'paid_calls':0}


class LearningService:
    def __init__(self,store):
        self.store=store;self.folder=Path(store.path).resolve().parent/'learning';self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder.parent/'learning.sqlite3';self.lock=threading.RLock();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='intent-local-train')
        self.cancelled=set();self.models={}
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session TEXT,status TEXT,input TEXT,report TEXT,error TEXT,progress TEXT,created TEXT,updated TEXT)')
            db.execute("UPDATE runs SET status='interrupted',error='服务停止，本地训练已中断；未启用不完整模型' WHERE status IN ('queued','running')")
            for row in db.execute("SELECT id,report FROM runs WHERE status='completed' AND report IS NOT NULL").fetchall():
                report=json.loads(row['report'])
                if report.get('activation')=='pending':
                    report['activation']='service_stopped_during_activation'
                    db.execute('UPDATE runs SET report=? WHERE id=?',(json.dumps(report,ensure_ascii=False),row['id']))

    def connect(self):
        db=sqlite3.connect(self.path,timeout=20,isolation_level=None);db.row_factory=sqlite3.Row;return db

    def close(self):
        with closing(self.connect()) as db:self.cancelled.update(r[0] for r in db.execute("SELECT id FROM runs WHERE status IN ('queued','running')"))
        self.pool.shutdown(wait=False,cancel_futures=True)

    def snapshot(self,sid):
        with closing(self.store.connect()) as db:
            db.execute('BEGIN');task,state,revision=self.store.load(db,sid);events=self.store.events(db,sid)
        active=self.store.active(events);labels=[e for e in active if e['kind']=='compare']
        return {'task':task,'state':state,'revision':revision,'pairs':[e['payload'] for e in labels],'label_ids':[e['id'] for e in labels]},events

    def run(self,rid):
        with closing(self.connect()) as db:row=db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not row:raise Invalid('训练版本不存在')
        result=dict(row);result['input']=json.loads(result['input']);result['report']=json.loads(result['report']) if result['report'] else None;return result

    def public(self,rid):return {k:v for k,v in self.run(rid).items() if k!='input'}

    def summary(self,sid):
        snapshot,events=self.snapshot(sid);state=snapshot['state'];active_ids=set(snapshot['label_ids']);task=snapshot['task']
        signatures=None
        if importlib.util.find_spec('numpy'):
            from research.deep_preference import training_hash
            signatures=training_hash(task,snapshot['pairs'])
        with closing(self.connect()) as db:ids=[r[0] for r in db.execute('SELECT id FROM runs WHERE session=? ORDER BY created DESC LIMIT 12',(sid,))]
        if state.get('learning_active') and state['learning_active'] not in ids:ids.append(state['learning_active'])
        runs=[]
        for rid in ids:
            value=self.public(rid);report=value.get('report') or {};value['compatible']=value['status']=='completed' and report.get('label_hash')==signatures
            value['active']=state.get('learning_active')==rid and value['compatible'];runs.append(value)
        feedback=[]
        for e in events:
            if e['kind']=='compare':
                p=e['payload'];feedback.append({'id':e['id'],'time':e['created'],'active':e['id'] in active_ids,'reasons':p.get('reasons',[]),
                    'winner':render(task,p['winner'])[:260],'loser':render(task,p['loser'])[:260],'note':p.get('reason_note','')})
        active_run=next((r for r in runs if r['active']),None)
        return {'availability':availability(),'pair_count':len(snapshot['pairs']),'runs':runs,'feedback':feedback[-40:],
                'active_run':active_run['id'] if active_run else None,'active_kind':state.get('learning_kind','semantic_deep') if active_run else None,'stale':bool(state.get('learning_active') and not active_run),
                'priorities':state.get('learning_priorities',{}),'reasons':REASONS,'paid_calls':0,
                'note':'只有未撤回的明确比较参与训练；模型预测、收藏与勾选不生成标签。旧权重不用于已撤回或新发生的反馈集合。'}

    def submit(self,sid,body):
        if not availability()['available']:raise Invalid('本地语义编码器尚未准备好；训练不会自动下载模型')
        snapshot,_=self.snapshot(sid)
        if type(body.get('revision')) is not int or body['revision']!=snapshot['revision']:raise Conflict('任务已更新，请重新发起本地训练')
        from research.deep_preference import partition
        if partition(snapshot['task'],snapshot['pairs'])['groups']<2:raise Invalid('至少需要两组不同的明确比较；重复或反向比较只算同一组')
        steps=body.get('steps',180)
        if type(steps) is not int or not 40<=steps<=500:raise Invalid('训练步数需为40–500的整数')
        rid=uuid.uuid4().hex;snapshot['steps']=steps;snapshot['activate']=body.get('activate',True) is True
        with self.lock,closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]>=2:raise Invalid('已有本地训练任务，请等待完成')
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)',(rid,sid,'queued',json.dumps(snapshot,ensure_ascii=False),None,None,'等待本地训练',now(),now()));db.commit()
        self.pool.submit(self.train,rid);return self.public(rid)

    def progress(self,rid,text):
        if rid in self.cancelled:raise Invalid('本地训练已取消')
        with closing(self.connect()) as db:db.execute("UPDATE runs SET progress=?,updated=? WHERE id=? AND status IN ('queued','running')",(text,now(),rid))

    def train(self,rid):
        try:
            row=self.run(rid);data=row['input'];sid=row['session']
            with closing(self.connect()) as db:db.execute("UPDATE runs SET status='running',updated=? WHERE id=?",(now(),rid))
            self.progress(rid,'正在本机编码文字；不发送目标或素材到API')
            from research.deep_preference import DeepPreferenceModel
            from research.semantic import encoder
            model=DeepPreferenceModel(data['task'],encoder()).fit(data['pairs'],steps=data['steps'],progress=lambda member,step,loss:self.progress(rid,f'偏好网络 {member+1}/3 · 第{step}步'))
            folder=self.folder/sid/rid;model.save(folder);self.progress(rid,'正在保存权重与独立评估记录')
            report=copy.deepcopy(model.report);combos=enumerate_feasible(data['task'],data['state'])
            best=max(zip(combos,model.scores(combos)),key=lambda c:float(c[1]))[0] if combos else None
            report['effect']={'current_combo':data['state']['combo'],'recommended_combo':best,'changed_sections':[b['title'] for b in data['task']['blocks'] if best and best[b['id']]!=data['state']['combo'][b['id']]],
                              'note':'这是模型预测，不是用户标签或事实正确率；无可行组合时不推荐。'}
            report['data_origin']=data['state'].get('research',{}).get('data_origin','example_task' if data['task'].get('source')=='example' else 'unclassified')
            report['label_ids']=data['label_ids'];report['base_revision']=data['revision'];report['paid_calls']=0
            report['activation']='pending' if data['activate'] else 'not_requested'
            with closing(self.connect()) as db:db.execute("UPDATE runs SET status='completed',report=?,progress='本地训练完成',updated=? WHERE id=?",(json.dumps(report,ensure_ascii=False),now(),rid))
            if data['activate']:
                try:
                    self.store.action(sid,{'kind':'learning_activate','revision':data['revision'],'run':rid})
                    report['activation']='activated'
                except (Conflict,Invalid) as exc:
                    report['activation']='inputs_changed_not_activated';report['activation_error']=str(exc)
                with closing(self.connect()) as db:db.execute('UPDATE runs SET report=?,updated=? WHERE id=?',(json.dumps(report,ensure_ascii=False),now(),rid))
        except Exception as exc:
            error=str(exc) if isinstance(exc,Invalid) else '本地训练失败；当前文稿和已启用模型未更改'
            with closing(self.connect()) as db:db.execute('UPDATE runs SET status=?,error=?,updated=? WHERE id=?',('cancelled' if rid in self.cancelled else 'error',error,now(),rid))

    def cancel(self,rid):
        row=self.run(rid)
        if row['status'] in ('queued','running'):
            self.cancelled.add(rid)
            with closing(self.connect()) as db:db.execute("UPDATE runs SET status='cancelled',error='已请求取消本地训练',updated=? WHERE id=?",(now(),rid))
        return self.public(rid)

    def validate_activation(self,sid,rid,task,pairs):
        from research.deep_preference import training_hash
        row=self.run(rid)
        if row['session']!=sid or row['status']!='completed' or not row['report'] or row['report']['label_hash']!=training_hash(task,pairs):raise Invalid('此训练版本与当前任务或有效反馈不一致，请重新训练')
        if not (self.folder/sid/rid/'model.json').is_file():raise Invalid('训练权重文件不存在')
        return row

    def model_for(self,sid,task,state,pairs):
        rid=state.get('learning_active')
        if not rid:return None
        try:
            row=self.validate_activation(sid,rid,task,pairs)
            from research.deep_preference import DeepPreferenceModel,SemanticLinearModel
            from research.model import digest
            from research.semantic import encoder
            key=digest({'run':rid,'blocks':task['blocks'],'priorities':state.get('learning_priorities',{}),'kind':state.get('learning_kind','semantic_deep')})
            with self.lock:
                if key not in self.models:
                    if len(self.models)>=8:self.models.pop(next(iter(self.models)))
                    self.models[key]=DeepPreferenceModel.load(task,encoder(),self.folder/sid/rid,state.get('learning_priorities',{}))
                    if state.get('learning_kind')=='semantic_linear':self.models[key]=SemanticLinearModel(self.models[key])
                return self.models[key]
        except (Invalid,ImportError,OSError,ValueError,KeyError,TypeError):return None

    def offer(self,sid,task,state,pairs,seen):
        from core import pair_key
        from research.model import digest
        from research.decision_value import select, risk
        model=self.model_for(sid,task,state,pairs)
        if model is None:return None
        combos=enumerate_feasible(task,state)
        if len(combos)<2:return None
        scores=model.score_heads(combos)@model.head_weights()
        selected=select(scores,allowed=lambda i,j:pair_key('__whole__',combos[i],combos[j]) not in seen)
        if selected is None:return None
        i,j=selected['pair'];key=pair_key('__whole__',combos[i],combos[j])
        changed=[b['id'] for b in task['blocks'] if combos[i][b['id']]!=combos[j][b['id']]]
        # Keep the two forecast branches aligned with randomized presentation sides.
        swap=int(digest({'revision':state.get('_revision',0),'key':key})[:8],16)%2
        if swap:
            i,j=j,i;selected['probability_a']=1-selected['probability_a']
            for branch in selected['branches']:branch['response']='b' if branch['response']=='a' else 'a'
        for branch in selected['branches']:branch['recommended_combo']=combos[branch.pop('action')]
        selected['pair']=[i,j]
        return {'block':'__whole__','comparison_kind':'whole_plan','title':'两份可行方案的取舍','a':combos[i],'b':combos[j],
                'context':{k:v for k,v in combos[i].items() if k not in changed},'changed_blocks':changed,'alternative_context':True,
                'key':key,'probability_a':selected['probability_a'],'response_mode':'evaluate_only',
                'planning':{**selected,'model_snapshot':model.metadata()['snapshot_hash'],'scores_hash':risk(scores)['scores_hash'],
                            'uncertainty':'initialization hypotheses, uncalibrated',
                            'note':'按有限假设集的一步预期后悔值下降选题；模拟分支不作为标签，不保证真实用户收益。'}}

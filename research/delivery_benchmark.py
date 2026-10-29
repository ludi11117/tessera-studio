"""Prospective paired delivery evaluation. Empty observations remain pending."""
import copy
import hashlib
import json
import math
import random
from datetime import datetime
from pathlib import Path

VERSION='delivery-crossover-v1'
ARMS=('tessera','chat')
DEFAULT_BUDGET={'time_seconds':900,'cost_usd':1.0,'model_calls':8}


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def exact(value,keys,label):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError(label+' fields do not match the declared schema')


def number(value,label,integer=False):
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or value<0:raise ValueError(label+' must be a nonnegative finite number')
    return value


def text(value,label):
    if not isinstance(value,str) or not value.strip():raise ValueError(label+' must be nonempty text')
    return value


def validate_budget(budget):
    exact(budget,DEFAULT_BUDGET,'budget')
    for key in budget:
        number(budget[key],key,key!='cost_usd')
        if budget[key]<=0:raise ValueError('Budget limits must be positive')


def load_tasks(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('origin')!='designed_tasks_not_real_user_results' or len(data.get('tasks',[]))!=20:raise ValueError('Expected the declared 20 designed tasks')
    ids=set()
    for task in data['tasks']:
        if task['id'] in ids:raise ValueError('Duplicate task id')
        ids.add(task['id']);rubric=task['rubric']
        if not rubric or len({r['id'] for r in rubric})!=len(rubric):raise ValueError('Invalid rubric')
    return data['tasks']


def build_plan(tasks,model=None,participants=10,seed=101,budget=None):
    if type(participants) is not int or participants not in (1,2,5,10):raise ValueError('Use 1, 2, 5 or 10 planned participants so every participant has balanced order')
    if model is not None:text(model,'model')
    budget=copy.deepcopy(budget or DEFAULT_BUDGET);validate_budget(budget)
    order=list(range(len(tasks)));random.Random(seed).shuffle(order)
    assignments=[]
    for n,index in enumerate(order):
        task=tasks[index];person=n%participants;block=n//participants;pair=f'pair-{n+1:02d}'
        arms=ARMS if (person+block)%2==0 else tuple(reversed(ARMS))
        for position,arm in enumerate(arms,1):
            row={'trial_id':pair+'-'+arm,'pair_id':pair,'participant_id':f'planned-{person+1:02d}','task_id':task['id'],
                 'arm':arm,'order':position,'materials_hash':digest(task['materials']),'rubric_hash':digest(task['rubric'])}
            row['assignment_hash']=digest(row);assignments.append(row)
    return {'version':VERSION,'origin':'prospective_plan_not_enrolled_participants','model':model,'budget':budget,'seed':seed,
            'tasks':copy.deepcopy(tasks),'assignments':assignments,'notes':['Model and budget fields are planned settings, not permission to spend or evidence of execution.',
                'Both arms receive identical initial artifact/materials and the same tasks; randomize task order and balance system order.',
                'Crossover does not eliminate learning/carryover; record deviations and report this limitation.',
                'No participant or outcome exists merely because a planned ID was allocated.']}


def empty_records(plan):
    tasks={t['id']:t for t in plan['tasks']}
    return {'version':VERSION,'plan_hash':digest(plan),'records':[{**copy.deepcopy(a),'status':'pending','execution':None,
        'events':None,'capture_complete':None,'observer_id':None,'artifact':None,
        'rubric':{r['id']:{'passed':None,'evidence':None} for r in tasks[a['task_id']]['rubric']},'notes':''} for a in plan['assignments']]}


def timestamp(value):
    text(value,'event timestamp')
    try:result=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('Use ISO timestamps with an explicit timezone')
    if result.tzinfo is None:raise ValueError('Event timestamp requires timezone')
    return result


def evidence(ref,root):
    if ref is None:return False
    exact(ref,('path','sha256'),'evidence');text(ref['path'],'evidence path');text(ref['sha256'],'evidence SHA-256')
    if root is None:raise ValueError('Recorded evidence requires --evidence-root')
    folder=Path(root).resolve();path=(folder/ref['path']).resolve()
    if Path(ref['path']).is_absolute() or path==folder or folder not in path.parents:raise ValueError('Evidence must stay under the selected directory')
    if not path.is_file():raise ValueError('Referenced evidence file is missing: '+ref['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('Evidence hash mismatch: '+ref['path'])
    return True


def score_record(plan,assignment,task,record,root):
    fields=(*assignment,'status','execution','events','capture_complete','observer_id','artifact','rubric','notes')
    exact(record,fields,'record')
    if any(record[k]!=v for k,v in assignment.items()):raise ValueError('Record assignment changed')
    if record['status'] not in ('pending','recorded'):raise ValueError('Status must be pending or recorded')
    if not isinstance(record['notes'],str):raise ValueError('Notes must be text')
    exact(record['rubric'],[r['id'] for r in task['rubric']],'rubric')
    missing=[]
    for rid,value in record['rubric'].items():
        exact(value,('passed','evidence'),'rubric item')
        if value['passed'] is not None and type(value['passed']) is not bool:raise ValueError('Rubric passed must be a boolean or null')
        if value['passed'] is None or not evidence(value['evidence'],root):missing.append('rubric:'+rid)
    if record['execution'] is None:missing.append('execution')
    else:
        execution=record['execution'];exact(execution,('model','budget','materials_hash','system_version'),'execution')
        text(execution['model'],'executed model');text(execution['system_version'],'system version');validate_budget(execution['budget'])
        if execution['model']!=plan['model'] or execution['budget']!=plan['budget'] or execution['materials_hash']!=assignment['materials_hash']:raise ValueError('Model, materials or budget differ from the paired protocol')
    if record['capture_complete'] is not None and type(record['capture_complete']) is not bool:raise ValueError('Capture completeness must be boolean or null')
    if record['capture_complete'] is not True:missing.append('capture_complete')
    if record['observer_id'] is None:missing.append('observer_id')
    else:text(record['observer_id'],'observer id')
    if not evidence(record['artifact'],root):missing.append('artifact')
    events=record['events'];cost=0.;calls=0;corrections=0;mis_edits=0;duration=None
    if events is None:missing.append('events')
    else:
        if not isinstance(events,list):raise ValueError('Events must be a list')
        times=[];kinds=[]
        for event in events:
            if not isinstance(event,dict):raise ValueError('Event must be an object')
            kind=event.get('kind')
            if kind not in ('start','finish','correction','model_call','preservation_violation'):raise ValueError('Unknown event kind')
            exact(event,('kind','at','evidence','cost_usd') if kind=='model_call' else ('kind','at','evidence'),'event')
            times.append(timestamp(event['at']));kinds.append(kind)
            if not evidence(event['evidence'],root):missing.append('event evidence')
            if kind=='model_call':cost+=number(event['cost_usd'],'model call cost');calls+=1
            corrections+=int(kind=='correction');mis_edits+=int(kind=='preservation_violation')
        if len(events)<2:missing.append('start/finish')
        elif kinds.count('start')!=1 or kinds.count('finish')!=1 or kinds[0]!='start' or kinds[-1]!='finish' or times!=sorted(times):raise ValueError('Require one ordered start and finish enclosing every event')
        else:duration=(times[-1]-times[0]).total_seconds()
    if plan['model'] is None:missing.append('configured model')
    if record['status']=='pending':missing.append('record not submitted')
    if missing:return {'trial_id':assignment['trial_id'],'status':'pending','missing':sorted(set(missing))}
    exceeded=[k for k,v in {'time_seconds':duration,'cost_usd':cost,'model_calls':calls}.items() if v>plan['budget'][k]]
    if exceeded:return {'trial_id':assignment['trial_id'],'status':'protocol_deviation','exceeded':exceeded}
    return {'trial_id':assignment['trial_id'],'status':'observed','metrics':{'completed':all(v['passed'] for v in record['rubric'].values()),
            'rubric_pass_fraction':sum(v['passed'] for v in record['rubric'].values())/len(record['rubric']),
            'preservation_violations':mis_edits,'corrections':corrections,'time_seconds':duration,'cost_usd':cost,'model_calls':calls}}


def assess(plan,log,root=None):
    if plan.get('version')!=VERSION:raise ValueError('Unknown protocol version')
    validate_budget(plan['budget'])
    exact(log,('version','plan_hash','records'),'log')
    if log['version']!=VERSION or log['plan_hash']!=digest(plan):raise ValueError('Plan binding differs')
    if not isinstance(log['records'],list):raise ValueError('Records must be a list')
    assignments={a['trial_id']:a for a in plan['assignments']};tasks={t['id']:t for t in plan['tasks']};records={};results={}
    for row in log['records']:
        if not isinstance(row,dict) or row.get('trial_id') not in assignments or row['trial_id'] in records:raise ValueError('Unknown or duplicate trial')
        records[row['trial_id']]=row
    for tid,a in assignments.items():
        results[tid]=score_record(plan,a,tasks[a['task_id']],records[tid],root) if tid in records else {'trial_id':tid,'status':'pending','missing':['record']}
    pairs=[];observations={a:[] for a in ARMS}
    for pid in sorted({a['pair_id'] for a in assignments.values()}):
        bound=[a for a in assignments.values() if a['pair_id']==pid]
        if len(bound)!=2 or {a['arm'] for a in bound}!=set(ARMS) or len({(a['task_id'],a['participant_id'],a['materials_hash'],a['rubric_hash']) for a in bound})!=1:raise ValueError('Unmatched paired assignment')
        selected={a['arm']:results[a['trial_id']] for a in bound}
        valid=all(v['status']=='observed' for v in selected.values())
        pairs.append({'pair_id':pid,'status':'observed' if valid else 'pending_or_deviated','arms':{k:v['status'] for k,v in selected.items()}})
        if valid:
            for arm in ARMS:observations[arm].append(selected[arm]['metrics'])
    n=len(observations['tessera']);means={};deltas={}
    if n:
        for arm,rows in observations.items():means[arm]={k:sum(r[k] for r in rows)/n for k in rows[0]}
        deltas={k:means['tessera'][k]-means['chat'][k] for k in means['tessera']}
    return {'version':VERSION,'status':'pending' if not n else 'partial' if n<len(pairs) else 'complete',
            'planned_pairs':len(pairs),'complete_pairs':n,'pending_or_deviated_pairs':len(pairs)-n,
            'paired_arm_means':means or None,'paired_difference_tessera_minus_chat':deltas or None,'trials':list(results.values()),'pairs':pairs,
            'plan_hash':digest(plan),'log_hash':digest(log),'note':'Only complete protocol-compliant pairs enter means. Evidence hashes verify file identity, not the truth of observer judgements or provider billing.'}

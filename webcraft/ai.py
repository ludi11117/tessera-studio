"""One-call component-copy proposals through the existing frozen job transport."""
import copy
from pathlib import Path
from core import Invalid
from store import Conflict
from webcraft.store import WebStore
from webcraft.model import IDS,patch
from webcraft.render import render

def repository(service):return WebStore(Path(service.store.path).parent/'websites.sqlite3')

def prepare(service,body):
    view=repository(service).view(body.get('site_id'));cid=body.get('component');instruction=body.get('instruction','')
    if type(body.get('revision')) is not int or body['revision']!=view['revision']:raise Conflict('网页版本变化，请重新选取组件')
    if cid not in IDS or cid+'.content' in view['locks']:raise Invalid('组件文案已保留或不存在')
    if not isinstance(instruction,str) or not 2<=len(instruction.strip())<=800:raise Invalid('请用2–800字说明调整要求')
    return {'site_id':view['id'],'base_revision':view['revision'],'document':view['document'],'locks':view['locks'],'component':cid,'instruction':instruction.strip()}

def run(service,jid,inputs):
    cid=inputs['component'];content=inputs['document']['components'][cid]['content']
    service.progress(jid,'为这一组件准备两份文案，布局和色调保持')
    output,meta=service.ask(jid,inputs,{'operation':'网页组件文案','brief':inputs['document']['brief'],'current_content':content,'instruction':inputs['instruction'],'requirements':'只基于给定内容改写，不编造经历、指标或身份。返回两个不同的完整content对象，字段必须与current_content完全一致。url原样保留；projects的body每行一个项目，标题与说明用｜分隔。每字段最多1600字符，title最多120。只返回JSON。','output_schema':{'options':[{'label':'表达特点','content':content}]}},3000)
    if not isinstance(output,dict) or not isinstance(output.get('options'),list) or len(output['options'])!=2:raise Invalid('网页文案需要两个候选，本次未自动重试')
    options=[];seen=set()
    for i,o in enumerate(output['options']):
        if not isinstance(o,dict) or not isinstance(o.get('label'),str) or not 1<=len(o['label'])<=60 or not isinstance(o.get('content'),dict):raise Invalid('文案候选格式无效')
        patches=[{'component':cid,'field':'content','value':o['content']}];reason=None;html=None
        try:
            after,_=patch(inputs['document'],patches,inputs['locks'])
            if 'url' in content and o['content'].get('url')!=content['url']:raise Invalid('联系地址必须保持原样')
            key=__import__('json').dumps(o['content'],sort_keys=True)
            if key in seen:raise Invalid('两个候选重复')
            seen.add(key);html=render(after,True)
        except Invalid as exc:reason=str(exc)
        options.append({'id':str(i),'label':o['label'],'patches':patches,'html':html,'can_apply':reason is None,'reason':reason})
    return {'site_id':inputs['site_id'],'base_revision':inputs['base_revision'],'options':options,'calls':[meta],'applied':False,'summary':'两个网页文案草案已准备好，采用后才改变网页。'}

def apply(service,job,body):
    r=job['result'] or {};chosen=next((o for o in r.get('options',[]) if o['id']==body.get('option')),None)
    if job['status']!='completed' or r.get('applied') or not chosen or not chosen['can_apply']:raise Invalid('网页草案不可采用')
    if body.get('revision')!=r['base_revision']:raise Conflict('网页版本变化，请重新生成')
    return repository(service).action(r['site_id'],{'kind':'patch','revision':body['revision'],'patches':chosen['patches'],'job_id':job['id']})

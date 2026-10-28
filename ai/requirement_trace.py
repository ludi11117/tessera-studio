"""Revision-bound requirement-to-content evidence; lexical matches never pass semantics."""
import math
import re
from collections import Counter
from ai.acceptance import digest, evaluate, suggest
from ai.retrieval import tokens
from core import Invalid, render_variant, variant_for


def sections(task,state):
    return [{'block':b['id'],'title':b['title'],'text':render_variant(task,variant_for(task,b['id'],state['combo'][b['id']]))}
            for b in task['blocks'] if not b.get('fixed')]


def requirements(task,state):
    rows=[]
    def add(kind,text,label=None,**extra):
        rows.append({'id':digest({'kind':kind,'text':text,'label':label or text,**extra}), 'kind':kind,'text':text,'label':label or text,**extra})
    brief=task.get('intent_brief') or {}
    if isinstance(brief,dict):
        for a in brief.get('explicit_answers',[]) if isinstance(brief.get('explicit_answers',[]),list) else []:
            if isinstance(a,dict) and isinstance(a.get('answer'),str) and isinstance(a.get('question'),str):add('intent',a['answer'],a['question'])
        for k,label in [('keep','希望保留'),('change','希望调整'),('user_acceptance','完成标准')]:
            if isinstance(brief.get(k),str) and brief[k]:
                for line in brief[k].splitlines():
                    if line.strip():add('intent',line.strip(),label)
        for q in brief.get('unresolved',[]) if isinstance(brief.get('unresolved',[]),list) else []:
            if isinstance(q,str):add('unknown',q,'仍待确认')
    add('intent',str(task.get('brief') or task['title']),'本次目标')
    for c in state.get('preserved_fragments',[]):add('literal',c['text'],'局部原文保留',block=c['block'])
    contract=state.get('acceptance') or {}
    if contract.get('confirmed'):
        for c in evaluate(task,state['combo'],contract)['checks']:add('machine',c['label'],'已确认机器条件',check_id=c['id'])
        for text in contract.get('manual',[]):add('intent',text,'人工验收要求')
    # Same requirement may be repeated in prose; keep stable unique IDs.
    return list({r['id']:r for r in rows}.values())


def snapshot(task,state,materials=None):
    content=sections(task,state);rows=requirements(task,state)
    return {'hash':digest({'requirements':rows,'sections':content,'materials':task.get('materials',task.get('ai',{}).get('sources',[]))}),
            'sections':content,'requirements':rows}


def evidence_for(text, content):
    paragraphs=[]
    for s in content:
        for i,p in enumerate(re.split(r'\n\s*\n|\n',s['text'])):
            if p.strip():paragraphs.append({'block':s['block'],'title':s['title'],'paragraph':i,'quote':p.strip()})
    bags=[set(tokens(p['quote'])) for p in paragraphs];q=set(tokens(text))
    frequency=Counter(t for bag in bags for t in bag);weights={t:math.log(1+(len(bags)+1)/(frequency[t]+1)) for t in q}
    denominator=sum(weights.values()) or 1
    found=[]
    for p,bag in zip(paragraphs,bags):
        overlap=q&bag
        score=sum(weights[t] for t in overlap)/denominator
        exact=text in p['quote']
        if not exact and (len(overlap)<2 or score<.12):continue
        quote=p['quote']
        if len(quote)>400:
            position=quote.find(text) if exact else next((quote.lower().find(t) for t in sorted(overlap) if t in quote.lower()),0)
            start=max(0,position-80);quote=quote[start:start+400]
        found.append({**p,'quote':quote,'score':round(score,6),'literal_match':exact})
    return sorted(found,key=lambda p:(-p['literal_match'],-p['score'],p['block'],p['paragraph']))[:3]


def semantic_evidence(text,content):
    """Explicit, bounded frozen-encoder lookup; never a satisfaction decision."""
    try:
        from research.semantic import encoder
        model=encoder()
    except ImportError:
        raise Invalid('本机语义模型依赖未就绪；可继续按文字线索或手动选择章节核对') from None
    pieces=[];total=0;per_section=max(1,60//max(1,len(content)))
    for s in content:
        starts=list(range(0,len(s['text']),320));total+=len(starts)
        if len(starts)>per_section:
            starts=[starts[round(i*(len(starts)-1)/max(1,per_section-1))] for i in range(per_section)]
        for start in starts:
            pieces.append({'block':s['block'],'title':s['title'],'quote':s['text'][start:start+400],'start':start})
    if not pieces:return {'evidence':[],'method':'frozen-semantic-cosine-v1','model':model.metadata,'automatic_pass':False}
    vectors=model.encode([text]+[p['title']+'\n'+p['quote'] for p in pieces])
    ranked=[{**p,'score':float(vectors[0]@v),'literal_match':text in p['quote']} for p,v in zip(pieces,vectors[1:])]
    return {'evidence':sorted(ranked,key=lambda p:(-p['score'],p['block'],p['start']))[:3],
            'method':'frozen-semantic-cosine-v1','model':model.metadata,'model_fingerprint':model.fingerprint,'examined_chunks':len(pieces),'total_chunks':total,'sampled':len(pieces)<total,
            'automatic_pass':False,'note':'语义相近的候选片段，可能包含否定或遗漏。相似度不是满足概率，请核对原文。'}


def report(task,state,materials=None):
    snap=snapshot(task,state,materials);contract=state.get('acceptance') or suggest(task)
    machine={c['id']:c for c in evaluate(task,state['combo'],contract)['checks']}
    rows=[];reviews=state.get('requirement_reviews',{})
    for requirement in snap['requirements']:
        r={**requirement,'evidence':[],'status':'needs_review','review':None,'stale_review':None}
        if r['kind']=='unknown':r['status']='needs_input'
        elif r['kind']=='literal':
            s=next(s for s in snap['sections'] if s['block']==r['block']);passed=r['text'] in s['text']
            r['status']='machine_passed' if passed else 'machine_failed'
            if passed:r['evidence']=[{'block':s['block'],'title':s['title'],'quote':r['text'],'literal_match':True}]
        elif r['kind']=='machine':
            check=machine[r['check_id']];r['status']='machine_passed' if check['passed'] else 'machine_failed';r['machine_check']=check
        else:
            r['evidence']=evidence_for(r['text'],snap['sections'])
            if not r['evidence']:r['status']='no_evidence'
            review=reviews.get(r['id'])
            if review:
                if review.get('snapshot_hash')==snap['hash']:
                    r['review']=review;r['status']='user_met' if review['decision']=='met' else 'user_gap'
                    r['selected_sections']=[s for s in snap['sections'] if s['block'] in review['blocks']]
                else:r['stale_review']=review
        rows.append(r)
    counts=Counter(r['status'] for r in rows)
    return {'version':'requirement-trace-v1','snapshot_hash':snap['hash'],'rows':rows,'counts':dict(counts),
            'sections':[{'block':s['block'],'title':s['title']} for s in snap['sections']],
            'paid_calls':0,'note':'文字线索只帮助定位，不自动证明需求已满足；人工确认绑定当前正文、需求与素材。'}


def review(task,state,body):
    snap=snapshot(task,state)
    if body.get('snapshot_hash')!=snap['hash']:raise Invalid('正文、需求或素材已变化，请重新核对')
    row=next((r for r in snap['requirements'] if r['id']==body.get('requirement')),None)
    if not row or row['kind']!='intent':raise Invalid('只能人工核对当前明确需求；未知项仍需补充，机器条件由程序检查')
    decision=body.get('decision');blocks=body.get('blocks',[]);note=body.get('note','')
    if decision not in ('met','gap','clear') or not isinstance(blocks,list) or len(blocks)>6 or any(not isinstance(b,str) or b not in {s['block'] for s in snap['sections']} for b in blocks) or len(set(blocks))!=len(blocks):raise Invalid('需求核对选项无效')
    if decision=='met' and not blocks:raise Invalid('确认满足前，请选择体现这项需求的章节')
    if not isinstance(note,str) or len(note)>500:raise Invalid('补充说明最多500字')
    reviews=dict(state.get('requirement_reviews',{}))
    if decision=='clear':reviews.pop(row['id'],None)
    else:reviews[row['id']]={'decision':decision,'blocks':blocks,'note':note.strip(),'snapshot_hash':snap['hash']}
    return reviews

"""Compile model replacement text into one immutable character range."""
import copy
import re
from ai.acceptance import digest
from ai.retrieval import retrieve
from core import Invalid, feasible, render_variant, variant_for, validate_task
from store import Conflict

ACTIONS={'concise':'更简洁，保留必要信息','detail':'补充有依据的细节，不编造事实','tone':'调整表达方式，让语言自然、清楚','alternatives':'给出两种有真实表达差别的替换版本'}


def prepare(view,body):
    task,state=view['task'],view['state'];selected=body.get('selection')
    if not isinstance(selected,dict):raise Invalid('请先选中一段想调整的正文')
    block=next((b for b in task['blocks'] if b['id']==selected.get('block') and not b.get('fixed')),None)
    if not block or block['id'] in state['locks']:raise Invalid('选中的章节不存在或已锁定')
    if selected.get('variant')!=state['combo'][block['id']]:raise Conflict('这一章的版本已变化，请重新选取')
    text=render_variant(task,variant_for(task,block['id'],state['combo'][block['id']]))
    start,end=selected.get('start'),selected.get('end')
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or end-start>1500 or text[start:end]!=selected.get('text'):
        raise Invalid('选取位置与当前原文不一致；请重新选择1–1500字的连续正文')
    action=body.get('action');note=body.get('note','')
    if action not in ACTIONS or not isinstance(note,str) or len(note)>500:raise Invalid('局部调整方式或补充要求无效')
    return {'block':block['id'],'title':block['title'],'variant':selected['variant'],'start':start,'end':end,
            'text':text[start:end],'before':text,'text_hash':digest(text),'action':action,'note':note.strip(),
            'instruction':ACTIONS[action]}


def run(service,jid,inputs):
    from ai.service import align_references,validate_citations
    view=inputs['view'];task,state=view['task'],view['state'];target=inputs['local_target'];bid=target['block']
    sources=retrieve(target['text']+' '+inputs['instruction'],inputs['materials'])
    active={m['id'] for m in inputs['materials']}
    sources=list({s['id']:s for s in task.get('ai',{}).get('sources',[])+sources if s['id'].split('#')[0] in active}.values())
    service.progress(jid,'只为选中的文字起草替换，其他原文由程序保留')
    count=2 if target['action']=='alternatives' else 1
    output,meta=service.ask(jid,inputs,{'operation':'仅改写选中的文字','goal':task['brief'],'instruction':inputs['instruction'],
        'selected_text':target['text'],'context_before':target['before'][max(0,target['start']-200):target['start']],
        'context_after':target['before'][target['end']:target['end']+200],'facts':task['facts'],'sources':sources,
        'preserved_fragments':state.get('preserved_fragments',[]),'intent_brief':task.get('intent_brief'),
        'requirements':f'只返回选中范围的replacement，不重复上下文或整章。恰好{count}个不同版本；每版非空且最多3000字符。保留必要事实、引用和明确保留的原文，不虚构效果、费用或经历。未选中的上下文仅供理解，不能写入替换范围。',
        'output_schema':{'options':[{'label':'版本特点','replacement':'仅替换选中文字的正文'}]}},3000)
    raw=output.get('options') if isinstance(output,dict) else None
    if not isinstance(raw,list) or len(raw)!=count:raise Invalid('局部改写版本数量或格式不正确，本次不自动重试')
    options=[];seen=set()
    old=variant_for(task,bid,state['combo'][bid]);expected=re.findall(r'\{\{(.*?)\}\}',old['template'])
    for i,item in enumerate(raw):
        if not isinstance(item,dict) or not isinstance(item.get('replacement'),str) or not item['replacement'].strip() or len(item['replacement'])>3000:
            raise Invalid('局部替换为空或过长，原文保持不变')
        replacement=item['replacement'];label=item.get('label','版本'+str(i+1))
        if not isinstance(label,str) or not 1<=len(label)<=60 or replacement in seen:raise Invalid('局部版本名称无效或内容重复')
        seen.add(replacement)
        after=target['before'][:target['start']]+replacement+target['before'][target['end']:]
        blocks=copy.deepcopy(task['blocks']);error=None
        try:
            template=align_references(after,task['facts'],expected)
            validate_citations(replacement,sources)
            if render_variant(task,{'template':template})!=after:raise Invalid('事实规范化改变了替换范围之外的文字')
            for b in blocks:
                if b['id']==bid:
                    for v in b['variants']:
                        if v['id']==state['combo'][bid]:v['template']=template
            candidate={**task,'blocks':blocks};validate_task(candidate)
            if not feasible(candidate,state['combo'],state):raise Invalid('这个版本未满足验收、局部保留、锁定或长度要求')
        except Invalid as exc:error=str(exc)
        changed=after!=target['before']
        options.append({'id':'option-'+str(i),'label':label,'replacement':replacement,'blocks':blocks,
                        'after':after,'can_apply':error is None and changed,'validation_message':error or (None if changed else '与原文相同，无需替换'),
                        'outside_unchanged':True,'prefix_hash':digest(target['before'][:target['start']]),'suffix_hash':digest(target['before'][target['end']:])})
    return {'session_id':inputs['session_id'],'base_revision':view['revision'],'target':target,'options':options,
            'summary':'局部替换已准备好；选择后才改动正文。','calls':[meta],'sources':sources,'applied':False,'can_apply':any(o['can_apply'] for o in options)}


def apply(service,job,body):
    result=job['result']
    if not isinstance(result,dict):raise Invalid('局部草案尚未完成')
    chosen=next((o for o in result.get('options',[]) if o['id']==body.get('option')),None)
    if job['status']!='completed' or result.get('applied') or not chosen or not chosen['can_apply']:raise Invalid('这个局部版本不可采用或已采用')
    current=service.store.view(job['session'])
    if type(body.get('revision')) is not int or body['revision']!=result['base_revision'] or current['revision']!=result['base_revision']:raise Conflict('正文已变化，请重新选取要改的文字')
    target=result['target'];text=render_variant(current['task'],variant_for(current['task'],target['block'],current['state']['combo'][target['block']]))
    if digest(text)!=target['text_hash']:raise Conflict('局部原文与草案不一致，请重新选取')
    if not feasible({**current['task'],'blocks':chosen['blocks']},current['state']['combo'],current['state']):raise Invalid('当前条件不允许采用这个版本')
    service.store.action(job['session'],{'kind':'edit','revision':body['revision'],'blocks':chosen['blocks']},ai_metadata={
        'job_id':job['id'],'summary':result['summary'],'calls':result['calls'],'sources':result['sources'],
        'local_target':{k:target[k] for k in ('block','variant','start','end','text','text_hash','action')},'selected_option':chosen['id'],
        'checks':{'outside_selected_range_unchanged':True,'prefix_hash':chosen['prefix_hash'],'suffix_hash':chosen['suffix_hash']}})

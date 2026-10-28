"""Task-bound exploration with exact provenance; suggestions are not user facts."""
import re
from ai.acceptance import digest
from ai.guidance import CATALOG, normalize, context
from ai.materials import initial
from ai.retrieval import retrieve
from core import Invalid


def prepare(guidance, materials):
    guide=normalize(guidance)
    if not guide or len(guide['goal'])<2:raise Invalid('先简单说一句想做什么，再看本次灵感')
    # Choosing an exploration direction must not invalidate its own input snapshot.
    base={k:v for k,v in guide.items() if k not in ('confirmed','inspiration')}
    base['answers']={k:v for k,v in guide['answers'].items() if k!='direction'}
    library=initial(materials)
    fingerprint=digest({'guidance':base,'materials':library})
    brief=context({**base,'confirmed':False})
    basis=[{'id':'goal','label':'这次想法','text':guide['goal']}]
    for q in CATALOG[guide['category']]['questions']:
        answer=base['answers'].get(q['id'])
        if answer:basis.append({'id':'answer:'+q['id'],'label':q['title'],'text':answer})
    for k,label in [('keep','希望保留'),('change','希望调整'),('criteria','完成标准')]:
        if base[k]:basis.append({'id':k,'label':label,'text':base[k]})
    for chunk in retrieve(guide['goal']+' '+' '.join(v for v in base['answers'].values() if v),library,limit=3):
        basis.append({'id':chunk['id'],'label':chunk['name'],'text':chunk['text']})
    examples=next(q['examples'] for q in CATALOG[guide['category']]['questions'] if q.get('examples'))
    local=[]
    for i,e in enumerate(examples):
        local.append({'id':'local-'+str(i),'name':e['name'],'instruction':e['value'],
                      'preview':'围绕“'+guide['goal'][:100]+'”：'+e['text'],
                      'tradeoff':'这是基于本次输入组织的探索建议，具体内容需要生成后核对。',
                      'basis_quotes':[{'id':b['id'],'quote':b['text'][:160]} for b in basis[:3]]})
    return {'version':'contextual-inspiration-v1','context_hash':fingerprint,'brief':brief,'basis':basis,
            'local_directions':local,'materials':library,'paid_calls':0}


def validate_output(value, prepared):
    rows=value.get('directions') if isinstance(value,dict) else None
    if not isinstance(rows,list) or not 2<=len(rows)<=3:raise Invalid('灵感需返回2–3个具体方向，本次不自动重试')
    known={b['id']:b['text'] for b in prepared['basis']};clean=[]
    for i,row in enumerate(rows):
        if not isinstance(row,dict):raise Invalid('灵感方向格式无效')
        item={'id':'direction-'+str(i)}
        for key,limit in [('name',40),('instruction',500),('preview',1200),('tradeoff',500)]:
            text=row.get(key)
            if not isinstance(text,str) or not 2<=len(text.strip())<=limit:raise Invalid('灵感方向内容为空或超出长度')
            item[key]=text.strip()
        quotes=row.get('basis_quotes')
        if not isinstance(quotes,list) or not 1<=len(quotes)<=6:raise Invalid('灵感方向缺少可核对的输入依据')
        item['basis_quotes']=[]
        for q in quotes:
            if not isinstance(q,dict) or q.get('id') not in known or not isinstance(q.get('quote'),str) or not q['quote'].strip() or len(q['quote'])>300 or q['quote'] not in known[q['id']]:
                raise Invalid('灵感引用与本次输入原文不一致，结果未采用；本次不自动重试')
            item['basis_quotes'].append({'id':q['id'],'quote':q['quote']})
        clean.append(item)
    if len({d['instruction'] for d in clean})!=len(clean) or len({d['name'] for d in clean})!=len(clean):raise Invalid('灵感方向重复，本次不自动重试')
    return clean


def run(service,jid,inputs):
    prepared=inputs['inspiration_context'];service.progress(jid,'结合本次想法、明确回答与素材探索方向')
    value,meta=service.ask(jid,inputs,{'operation':'围绕当前需求探索具体灵感','intent_brief':prepared['brief'],'input_basis':prepared['basis'],
        'requirements':'返回2–3个围绕本次目标的具体方向和短内容示例，说明取舍，不只换标题。依据只能引用input_basis的id和连续原文。未知保持待确认；不编造用户事实、费用、效果或实施结果。引用原文仅说明输入依据，不证明生成内容正确。所有方向遵守同一保留/调整/完成标准。instruction供用户选择后继续生成，最多500字。',
        'output_schema':{'directions':[{'name':'方向名称','instruction':'具体探索要求','preview':'本次目标的短样稿或具体实施示意','tradeoff':'这个方向重视与暂缓什么','basis_quotes':[{'id':'输入依据id','quote':'连续原文'}]}]}},3200)
    return {'version':prepared['version'],'context_hash':prepared['context_hash'],'directions':validate_output(value,prepared),
            'basis':prepared['basis'],'calls':[meta],'summary':'已探索本次需求的具体方向，选择后才纳入需求卡。','suggestions_only':True}


def validate_selection(service, guide, materials):
    reference=guide.get('inspiration')
    if not reference:return
    job=service.job(reference['job']);result=job.get('result') or {}
    current=prepare(guide,materials)['context_hash']
    if job['kind']!='inspire' or job['status']!='completed' or current!=reference.get('confirmed_context_hash',result.get('context_hash')) or reference['context_hash']!=result.get('context_hash'):
        raise Invalid('所选灵感的想法、回答或素材已变化，请重新探索或改为自己填写方向')
    chosen=next((d for d in result.get('directions',[]) if d['id']==reference['choice']),None)
    if not chosen or guide['answers'].get('direction')!=chosen['instruction']:raise Invalid('所选灵感与当前方向不一致，请重新选择')

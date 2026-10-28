"""Bounded review/repair/review over a frozen document, always a proposal."""
import copy
import re

from ai.acceptance import digest, evaluate
from ai.service_helpers import normalize_changes
from ai.requirements import characters
from core import Invalid, feasible, render_variant, validate_task, variant_for


def document(task, combo):
    return [{'id': b['id'], 'title': b['title'], 'text': render_variant(task, variant_for(task, b['id'], combo[b['id']])),
             'template': variant_for(task, b['id'], combo[b['id']])['template']}
            for b in task['blocks'] if not b.get('fixed')]


def correction_plan(task, state, allowed):
    """Compute total residual budget, never pad or truncate a model response."""
    sections=document(task,state['combo']);length=state['acceptance'].get('length')
    if not length:return None
    protected=sum(characters(b['text']) for b in sections if b['id'] not in allowed)
    lo=max(0,length['min']-protected);hi=length['max']-protected
    target=(lo+hi)//2;editable=[b for b in sections if b['id'] in allowed]
    weight=sum(characters(b['text']) for b in editable) or 1;remaining=target;allocations=[]
    for index,b in enumerate(editable):
        count=characters(b['text']);wanted=remaining if index==len(editable)-1 else round(target*count/weight);remaining-=wanted
        allocations.append({'block':b['id'],'current_characters':count,'target_characters':wanted,'suggested_change':wanted-count,
                            'suggested_sentence_count':max(1,round(wanted/24)),'characters_per_sentence':24})
    return {'protected_characters':protected,'editable_min_characters':lo,'editable_max_characters':hi,
            'allocations':allocations,'instruction':'这是程序计算的正文预算。按target_characters重写各章，尽量接近目标而不是仅替换几个字。可补充邀请目的、已有安排或执行细节，但不得新增无依据的事实、承诺或凑字填充。总长度以独立字符计数复验为准。'}


def grounding_observations(task, state, sources):
    from ai.evidence import literals,aligned
    basis=[{'id':'goal','text':task['brief']}]+[{'id':'fact:'+k,'text':v} for k,v in task['facts'].items()]+sources
    result=[]
    for b in document(task,state['combo']):
        for line in b['text'].splitlines():
            for claim in literals(line):
                matches=[s['id'] for s in basis if aligned(claim,s['text'])]
                if not matches:result.append({'block':b['id'],'quote':line,'literal':claim['text'],'status':'not_in_any_supplied_text_not_necessarily_false'})
    return result[:100]


def review(service, jid, inputs, task, state, sources):
    service.progress(jid, '独立核对目标、来源与验收条件')
    current = document(task, state['combo'])
    value, meta = service.ask(jid, inputs, {
        'operation': '独立验收当前文稿', 'goal': task['brief'], 'facts': task['facts'], 'contract': state['acceptance'],
        'document': current, 'sources': sources,'literal_observations':grounding_observations(task,state,sources),
        'requirements': '你是独立审阅者，只检查当前选中的一份文稿，不沿用生成器自评。findings只允许确实违反目标或来源的内容，符合要求的陈述绝对不要放入findings；没有违例返回空数组。对比分析中解释未选方案为什么不满足条件属于正确分析，不是文稿违例。逐项检查目标、必要事项、数字归属、未确认信息、来源忠实与逻辑。旧稿不是事实来源；只有goal、facts、sources是依据。特别核查literal_observations：没有相同文字不等于错误，但无来源的既有测量值、时间上限、总大小、测试阈值不得沿用为既定条件。建议可明确标待执行。quote逐字摘取正文，遗漏可留空；reason必须写出应该怎样、当前怎样、违反在哪里，不能只复述正确内容。evidence_ids只列提供的素材编号。无法判断列uncertain，不能捏造冲突。这不是用户最终确认。',
        'output_schema': {'findings': [{'block': '违例章节id', 'quote': '违例原文或空字符串', 'violated': True, 'reason': '目标或来源要求X，但正文是Y，冲突为Z；不要把正确陈述列为问题', 'evidence_ids': ['M1#1']}],
                          'uncertain': ['无法核实的事项']}
    }, 3500)
    findings = value.get('findings'); uncertain = value.get('uncertain')
    if not isinstance(findings, list) or len(findings) > 30 or not isinstance(uncertain, list) or len(uncertain) > 20:
        raise Invalid('验收模型未返回有效检查列表；不能将此轮视为通过')
    by_id = {b['id']: b['text'] for b in current}; known = {s['id'] for s in sources}
    clean = []
    for f in findings:
        if not isinstance(f, dict) or f.get('block') not in by_id or not isinstance(f.get('quote'), str) or not isinstance(f.get('reason'), str) or not f['reason'].strip():
            raise Invalid('验收意见没有有效原文定位，未判定通过')
        if f['quote'] and f['quote'] not in by_id[f['block']]: raise Invalid('验收意见引用了正文不存在的文字')
        ids = f.get('evidence_ids', [])
        if not isinstance(ids, list) or any(not isinstance(s, str) or s not in known for s in ids): raise Invalid('验收意见引用了不存在的来源')
        if f.get('violated') is False:continue
        clean.append({'block': f['block'], 'quote': f['quote'], 'reason': f['reason'][:1500], 'evidence_ids': ids})
    if any(not isinstance(s, str) or len(s) > 1500 for s in uncertain): raise Invalid('验收不确定事项格式无效')
    return {'method': 'independent-model-review-v1', 'findings': clean, 'uncertain': uncertain,
            'document_hash': digest(current), 'sources_hash': digest(sources), 'contract_hash': digest(state['acceptance']),
            'status': 'issues_found' if clean else 'uncertain' if uncertain else 'no_issue_found',
            'note': '同一上游模型的独立请求，可能漏检或误判；不等于外部事实验证或人工验收。'}, meta


def run(service, jid, sid, inputs):
    view = inputs['view']; original = view['task']; task = copy.deepcopy(original); state = view['state']
    from ai.retrieval import prepare
    sources = prepare(inputs['materials'])
    contract = state['acceptance']; rounds = []; calls = []
    first, meta = review(service, jid, inputs, task, state, sources); calls.append(meta)
    before = evaluate(task, state['combo'], contract)
    rounds.append({'phase': 'before', 'machine': before, 'review': first})
    service.checkpoint(jid, 'quality_rounds', rounds)
    targets = set(b for f in before['failures'] for b in f['blocks']) | {f['block'] for f in first['findings']}
    allowed = [bid for bid in inputs['scope'] if bid in targets]
    if allowed:
        service.progress(jid, '只修正未通过且未锁定的部分')
        plan=correction_plan(task,state,allowed)
        use_sentences=bool(plan and any(a['suggested_change']>30 for a in plan['allocations']))
        schema={'block':'允许的id','sentences':['完整句子，句数采用suggested_sentence_count，每句约characters_per_sentence字；各句直接连接成正文，不写编号']} if use_sentences else {'block':'允许的id','text':'完整章节正文'}
        result, meta = service.ask(jid, inputs, {
            'operation': '按验收失败项修正文稿', 'goal': task['brief'], 'facts': task['facts'], 'contract': contract,
            'current_document': document(task, state['combo']), 'allowed_blocks': allowed, 'preserved_fragments':state.get('preserved_fragments',[]),
            'machine_failures': before['failures'], 'review_findings': first['findings'], 'sources': sources,
            'computed_correction_plan':plan,
            'explicit_literal_corrections':[{'block':m['block'],'remove_or_rephrase_without_literal':m['literal'],'original_sentence':m['quote']}
                                            for f in before['failures'] if f['id']=='source_numbers' for m in f['actual']],
            'literal_observations':grounding_observations(task,state,sources),
            'learned_preference_context': inputs.get('learned_preference_context'),
            'explicit_local_preferences': inputs.get('explicit_local_preferences', []),
            'requirements': 'preserved_fragments的text必须在对应章节原样连续保留，其他文字可以改。重新撰写allowed_blocks中需要修正的章节，直接替换错误表述，不要保留错误后再追加纠错说明。其他章节原文保持。computed_correction_plan给出程序计算的各章字数目标，必须落实；不能只微调语气而忽略长度失败。字数是整份正文，不含标题和固定事实章节。保持原{{key}}集合。旧稿不是事实依据，无出处的总大小、时间上限、阈值、优势结论应删去或明确待确认；不要从旧稿反向编造来源。先满足目标、素材与验收条件，再参考偏好预测；预测不是事实或用户确认。保留尚未确认的限制，不补造数字。返回每个改动章节的完整正文。',
            'output_schema': {'summary': '修正内容', 'changes': [schema]}
        }, 6500); calls.append(meta)
        task['blocks'], removed = normalize_changes(task, state, result.get('changes'), allowed, sources)
        validate_task(task)
        after_review, meta = review(service, jid, inputs, task, state, sources); calls.append(meta)
        rounds.append({'phase': 'after', 'machine': evaluate(task, state['combo'], contract), 'review': after_review,
                       'unsupported_citations_removed': removed})
        service.checkpoint(jid, 'quality_rounds', rounds)
    else:
        after_review = first
    final = rounds[-1]['machine']
    diffs = [{'block': a['id'], 'title': a['title'], 'before': a['text'], 'after': b['text']}
             for a, b in zip(document(original, state['combo']), document(task, state['combo'])) if a['text'] != b['text']]
    possible = feasible(task, state['combo'], state) and not after_review['findings']
    blockers = [f for f in first['findings'] if f['block'] not in inputs['scope']]
    status = 'issues_remain' if not final['machine_passed'] or after_review['findings'] else 'manual_review_required'
    return {'session_id': sid, 'base_revision': view['revision'], 'blocks': task['blocks'], 'diffs': diffs,
            'summary': '验收修正已保存为草案，仍需人工核对。' if diffs else '验收已完成，当前没有可自动采用的改动。',
            'quality_rounds': rounds, 'quality_status': status, 'blocked_findings': blockers,
            'calls': calls, 'sources': sources, 'applied': False, 'preference_context': inputs.get('learned_preference_context'),
            'can_apply': possible and bool(diffs), 'checks': {'semantic_fact_check': 'model_review_not_verified'},
            'validation_message': ('机器条件通过；模型仍有待核实事项，请人工核对后决定。' if after_review['uncertain'] else '机器条件通过；独立模型复验未发现问题，仍需人工确认。') if possible else '仍有未通过项或受锁定限制；草案保留，不能采用。'}

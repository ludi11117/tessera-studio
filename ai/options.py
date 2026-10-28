"""Finite, inspectable customization. No model calls and no inferred labels."""
import copy

from ai.acceptance import digest, evaluate, suggest
from ai.requirements import characters
from core import Invalid, feasible, render_variant, variant_for


def validate_combo(task, combo):
    blocks={b['id']:b for b in task['blocks']}
    if not isinstance(combo,dict) or set(combo)!=set(blocks) or any(not isinstance(v,str) or v not in {x['id'] for x in blocks[k]['variants']} for k,v in combo.items()):
        raise Invalid('方案必须为每章选择一个当前可用版本；旧版本请先核对')
    return dict(combo)


def anchors_for(task, anchors):
    if not isinstance(anchors,dict):raise Invalid('保留章节格式无效')
    known={b['id']:b for b in task['blocks'] if not b.get('fixed')}
    if any(k not in known or not isinstance(v,str) or v not in {x['id'] for x in known[k]['variants']} for k,v in anchors.items()):raise Invalid('保留章节或版本已失效')
    return dict(anchors)


def distance(task, a, b):
    return sum(a[block['id']]!=b[block['id']] for block in task['blocks'] if not block.get('fixed'))


def describe(task, state, combo):
    combo=validate_combo(task,combo);sections=[];violations=[]
    for block in task['blocks']:
        bid=block['id']
        if bid in state['locks'] and state['locks'][bid]!=combo[bid]:violations.append('已锁定：'+block['title'])
        if block.get('fixed'):continue
        variant=variant_for(task,bid,combo[bid]);j=next(i for i,v in enumerate(block['variants']) if v['id']==variant['id'])
        sections.append({'block':bid,'title':block['title'],'text':render_variant(task,variant),'choice':'ABC'[j],
                         'locked':bid in state['locks'],'changed':combo[bid]!=state['combo'][bid]})
    if state.get('max_chars') is not None:
        from core import render
        if len(render(task,combo))>state['max_chars']:violations.append('超过原长度上限')
    contract=state.get('acceptance') or suggest(task);report=evaluate(task,combo,contract)
    if contract.get('confirmed'):violations += [f['label'] for f in report['failures']]
    from ai.preservation import checks as preservation_checks
    violations += [c['label'] for c in preservation_checks(task,combo,state) if not c['passed']]
    return {'combo':dict(combo),'sections':sections,'body_characters':characters('\n\n'.join(b['text'] for b in sections)),
            'changes':[b['title'] for b in sections if b['changed']], 'mix':' / '.join(b['choice'] for b in sections),
            'can_apply':feasible(task,combo,state),'violations':violations,'acceptance':report,
            'contract_confirmed':bool(contract.get('confirmed')),'human_review_required':True}


def portfolio(task, state, ranks, pairs=0, limit=3):
    if not ranks:return []
    selected=[]
    def add(rank, reason, label):
        key=digest(rank['combo'])
        existing=next((s for s in selected if s['id']==key),None)
        if existing:
            if reason not in existing['reasons']:existing['reasons'].append(reason)
            return
        selected.append({'id':key,'label':label,'reasons':[reason],'score':rank['score'],**describe(task,state,rank['combo'])})
    add(ranks[0], f'按{pairs}次明确比较的偏好得分排序' if pairs else '尚无偏好反馈，按最少改动排序', '偏好优先' if pairs else '合格起点')
    nearest=min(ranks,key=lambda r:(distance(task,r['combo'],state['combo']),-r['score'],tuple(r['combo'].values())))
    add(nearest,'在合格组合中尽量保留当前章节','少改动')
    while len(selected)<min(limit,len(ranks)):
        remaining=[r for r in ranks if digest(r['combo']) not in {s['id'] for s in selected}]
        if not remaining:break
        diverse=max(remaining,key=lambda r:(min(distance(task,r['combo'],s['combo']) for s in selected),r['score'],-distance(task,r['combo'],state['combo'])))
        add(diverse,'优先展示与已展示方案采用不同章节版本的合格组合','不同搭配')
    return selected


def board(task, state, ranks, pairs=0):
    initials=[]
    for j in range(3):
        combo={b['id']:state['locks'].get(b['id'],b['variants'][j]['id']) for b in task['blocks']}
        initials.append(describe(task,state,combo))
    saved=[]
    for option in state.get('saved_options',[]):
        item=copy.deepcopy(option)
        try:
            current=describe(task,state,item['combo'])
            item['available']=True;item['can_apply']=current['can_apply'];item['violations']=current['violations']
            content=lambda sections:[{k:b[k] for k in ('block','title','text','choice')} for b in sections]
            item['changed_since_saved']=content(item['sections'])!=content(current['sections']) or item['contract_hash']!=current['acceptance']['contract_hash'] or item.get('materials_hash')!=digest(task.get('materials',[]))
        except Invalid:item.update(available=False,can_apply=False,changed_since_saved=True,violations=['包含已归档版本；保留原文供查看'])
        saved.append(item)
    return {'version':'choice-board-v1','portfolio':portfolio(task,state,ranks,pairs),'initials':initials,'saved':saved,
            'eligible':len(ranks),'paid_calls':0,'note':'只组合已有文字，不调用AI。差异按章节版本计算，不代表语义多样性或事实已核实。'}


def inspect(task, state, ranks, combo, anchors, pairs=0):
    combo=validate_combo(task,combo);anchors=anchors_for(task,anchors)
    selected=describe(task,state,combo)
    candidates=[r for r in ranks if all(r['combo'][k]==v for k,v in anchors.items())]
    closest=None
    if not candidates and ranks:
        rank=min(ranks,key=lambda r:(sum(r['combo'][k]!=v for k,v in anchors.items()),distance(task,r['combo'],combo),-r['score']))
        closest={'changes_needed':[next(b['title'] for b in task['blocks'] if b['id']==k) for k,v in anchors.items() if rank['combo'][k]!=v],
                 **describe(task,state,rank['combo'])}
    # Remaining chapters are filled with the smallest change from this draft.
    draft_state={**state,'combo':combo}
    completion=min(candidates,key=lambda r:(distance(task,r['combo'],combo),-r['score'],tuple(r['combo'].values()))) if candidates else None
    return {'selection':selected,'anchors':anchors,'eligible':len(candidates),'total_eligible':len(ranks),
            'alternatives':portfolio(task,draft_state,candidates,pairs),'completion':describe(task,draft_state,completion['combo']) if completion else None,'closest_without_anchors':closest,'paid_calls':0,
            'note':'保留项只用于本次搜索。采用并固定后才写入锁定；无解时不会自动放宽保留项。'}

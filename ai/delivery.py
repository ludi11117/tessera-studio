"""Transparent delivery checks. Structural signals never claim factual verification."""
import re
from core import render_variant,variant_for
from ai.evidence import audit
from ai.requirements import check as requirement_check
from ai.acceptance import delivery_report


def check(view,materials):
    task,state=view['task'],view['state']
    texts=[render_variant(task,variant_for(task,b['id'],state['combo'][b['id']])) for b in task['blocks'] if not b.get('fixed')]
    text='\n\n'.join(texts);warnings=[]
    known={s['id'] for s in task.get('ai',{}).get('sources',[])}
    citations=set(re.findall(r'\[(M\d+#\d+)\]',text))
    retired=sorted(c for c in citations if c.split('#')[0] not in {m['id'] for m in materials})
    if retired:warnings.append('正文仍引用已移除素材：'+', '.join(retired)+'。请检查后更新相关章节。')
    if citations-known:warnings.append('正文存在未记录的素材引用，请核查来源。')
    if len(text)<500 and task.get('category') in ('project','study','analysis'):warnings.append('当前正文较短，请检查实施细节和验收是否足够。')
    assumptions=task.get('ai',{}).get('blueprint',{}).get('assumptions',[])
    if assumptions:warnings.append(f'初稿列出{len(assumptions)}项假设，请在交付前确认。')
    if materials and not citations:warnings.append('正文未标记素材引用；请核对是否已体现关键材料。')
    evidence=audit(view,materials)
    from ai.preservation import checks as preservation_checks
    preservation=preservation_checks(task,state['combo'],state)
    warnings += [c['label']+'未通过' for c in preservation if not c['passed']]
    requirements=requirement_check(task,text)
    warnings+=requirements['warnings']
    from ai.requirement_trace import report as trace_report
    trace=trace_report(task,state)
    if trace['counts'].get('user_gap'):warnings.append('还有'+str(trace['counts']['user_gap'])+'项明确需求被标记为缺口，请先处理或重新核对。')
    return {'revision':view['revision'],'characters':len(text),'sections':len(texts),'materials':len(materials),'evidence':evidence,'requirements':requirements,'acceptance':delivery_report(view),'preservation':preservation,
            'citation_count':len(citations),'warnings':warnings,'review':state.get('review',{}),'requirement_trace':trace,
            'semantic_fact_check':'not_performed','note':'自动检查仅报告结构与来源状态；勾选项由你确认。'}

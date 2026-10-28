"""Explicit chapter-local literal preservation, separate from preference labels."""
from core import Invalid, render_variant, variant_for


def checks(task, combo, state):
    return [{'id': 'fragment:'+str(i), 'kind': 'fragment', 'block': p['block'], 'text': p['text'],
             'label': '保留局部原文：'+p['text'],
             'passed': p['text'] in render_variant(task, variant_for(task, p['block'], combo[p['block']]))}
            for i, p in enumerate(state.get('preserved_fragments', []))]


def update(task, state, block, text, remove=False):
    known = {b['id']: b for b in task['blocks'] if not b.get('fixed')}
    if block not in known or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise Invalid('请选择当前章节中1–500字的原文')
    text = text.strip();item = {'block': block, 'text': text}
    existing = list(state.get('preserved_fragments', []))
    if remove:
        if item not in existing:raise Invalid('这条局部保留已变化，请重新载入')
        existing.remove(item)
    else:
        current = render_variant(task, variant_for(task, block, state['combo'][block]))
        if text not in current:raise Invalid('保留内容必须是该章当前正文中的连续原文')
        if item in existing:raise Invalid('这段原文已保留')
        if len(existing) >= 12:raise Invalid('本任务最多保留12处局部原文')
        existing.append(item)
    return existing

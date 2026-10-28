"""Validate model changes without allowing protected sections to change."""
import copy
import re
from core import Invalid, variant_for


def normalize_changes(task, state, changes, scope, sources):
    from ai.service import align_references, clean_citations
    if not isinstance(changes, list) or len(changes) > len(scope): raise Invalid('修正范围格式无效')
    blocks = copy.deepcopy(task['blocks']); seen = set(); removed = set()
    for change in changes:
        bid = change.get('block') if isinstance(change, dict) else None
        if bid not in scope or bid in state['locks'] or bid in seen: raise Invalid('修正试图改动范围外或已锁定章节')
        seen.add(bid); text = change.get('text')
        if text is None and isinstance(change.get('sentences'),list) and 1<=len(change['sentences'])<=100 and all(isinstance(s,str) and s.strip() for s in change['sentences']):
            text=''.join(change['sentences'])
        if not isinstance(text, str) or not text.strip(): raise Invalid('修正正文为空')
        old = variant_for(task, bid, state['combo'][bid])
        text = align_references(text, task['facts'], re.findall(r'\{\{(.*?)\}\}', old['template']))
        text, dropped = clean_citations(text, sources); removed.update(dropped)
        for block in blocks:
            if block['id'] == bid:
                for variant in block['variants']:
                    if variant['id'] == old['id']: variant['template'] = text
    from ai.preservation import checks
    if any(not c['passed'] for c in checks({**task,'blocks':blocks},state['combo'],state)):
        raise Invalid('修正未保留指定章节中的局部原文，草案已拒绝，成稿保持不变')
    return blocks, sorted(removed)

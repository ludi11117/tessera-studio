"""Reproducible literal alignment to local evidence. Never a truth classifier."""
import hashlib
import re
import unicodedata

from core import render_variant, variant_for
from ai.retrieval import prepare

CITATION = re.compile(r'\[(M\d+#\d+)\]')
QUOTED = re.compile(r'“([^”\n]{2,60})”|「([^」\n]{2,60})」|`([^`\n]{2,100})`')
NUMBER = re.compile(r'(?<![A-Za-z0-9_#])(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d+(?:[.,]\d+)*(?:%|％|亿元|万元|元|个月|小时|分钟|秒|天|周|月|年|GB|MB|KB|px)?)', re.I)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold()


def literals(line):
    # Keep spans stable while excluding citations, URLs, and Markdown list numbers.
    masked = CITATION.sub(lambda m: ' ' * len(m[0]), line)
    masked = re.sub(r'https?://\S+', lambda m: ' ' * len(m[0]), masked)
    masked = re.sub(r'^\s*(?:[-*+]\s+|\d+[.、)]\s+)', lambda m: ' ' * len(m[0]), masked)
    result = []
    for match in QUOTED.finditer(masked):
        value = next(g for g in match.groups() if g is not None)
        result.append({'text': value, 'kind': 'quoted_text', 'start': match.start(), 'end': match.end()})
        masked = masked[:match.start()] + ' ' * (match.end()-match.start()) + masked[match.end():]
    for match in NUMBER.finditer(masked):
        result.append({'text': match[0], 'kind': 'number', 'start': match.start(), 'end': match.end()})
    return sorted(result, key=lambda item: item['start'])


def aligned(literal, evidence):
    needle, haystack = normalize(literal['text']), normalize(evidence)
    if literal['kind'] == 'number':
        # 30 is not supported by 130, nor 5 by 5.5 or 50.
        return bool(re.search(r'(?<![\d.])'+re.escape(needle)+r'(?![\d.])', haystack))
    return needle in haystack


def audit(view, materials):
    task, state = view['task'], view['state']
    canonical = {s['id']: s for s in prepare(materials)}
    recorded = {s['id']: s for s in task.get('ai', {}).get('sources', [])}
    active = {m['id'] for m in materials}
    basis = [{'id': 'goal', 'name': '目标说明', 'text': task.get('brief', '')}]
    basis += [{'id': 'fact:'+k, 'name': '固定条件', 'text': v} for k, v in task['facts'].items()]
    sections = []
    for block in task['blocks']:
        if block.get('fixed'): continue
        text = render_variant(task, variant_for(task, block['id'], state['combo'][block['id']]))
        source_ids = sorted(set(CITATION.findall(text)))
        sources = []
        for cid in source_ids:
            old, current = recorded.get(cid), canonical.get(cid)
            status = 'unknown' if old is None else 'removed' if cid.split('#')[0] not in active else 'changed' if current is None or old.get('text') != current['text'] else 'current'
            source = old or current or {}
            sources.append({'id': cid, 'status': status, 'name': source.get('name', '未记录的素材'), 'text': source.get('text', ''), 'sha256': digest(source.get('text', ''))})
        paragraphs, code = [], False
        by_id = {s['id']: s for s in sources}
        for index, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith('```'): code = not code; continue
            if code or not line.strip(): continue
            ids = sorted(set(CITATION.findall(line)))
            references = [by_id[cid] for cid in ids if by_id[cid]['status'] == 'current']
            claims = literals(line)
            for claim in claims:
                matches = [s['id'] for s in basis+references if aligned(claim, s['text'])]
                claim['matches'] = matches
                claim['status'] = 'literal_present' if matches else 'not_found' if references else 'no_reference'
            if ids or claims:
                paragraphs.append({'line': index, 'text': line, 'source_ids': ids, 'literals': claims})
        count = sum(c['status'] != 'literal_present' for p in paragraphs for c in p['literals'])
        unavailable = sum(s['status'] != 'current' for s in sources)
        sections.append({'block': block['id'], 'title': block['title'], 'text_sha256': digest(text), 'sources': sources, 'paragraphs': paragraphs, 'review_items': count+unavailable})
    return {'schema_version': 1, 'method': 'local-literal-alignment-v1', 'revision': view['revision'],
            'semantic_fact_check': 'not_performed', 'sections': sections,
            'summary': {'review_items': sum(s['review_items'] for s in sections), 'cited_sections': sum(bool(s['sources']) for s in sections),
                        'literal_count': sum(len(p['literals']) for s in sections for p in s['paragraphs'])},
            'note': '只对照本地原文中的数字和引号措辞；相同文字不代表语义正确，缺少对应也不代表事实错误。代码块不参与逐字检查。'}

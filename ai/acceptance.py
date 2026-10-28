"""Versioned, user-confirmed predicates; semantic review is separate evidence."""
import hashlib
import json
import re

from ai.requirements import characters, check as legacy_check

VERSION = 'acceptance-contract-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def suggest(task):
    old = legacy_check(task, '')
    uncertainty=[]
    for material in task.get('materials',[]):
        for phrase in re.split(r'[。；;，,\n]',material.get('text','')):
            phrase=phrase.strip()
            if 3<=len(phrase)<=60 and re.search(r'尚未|未确认|未约定|暂未|暂时没有',phrase) and phrase not in uncertainty:uncertainty.append(phrase)
    return {'version': VERSION, 'length': {k: old['length'][k] for k in ('min', 'max')} if 'length' in old else None,
            'days': old.get('days', {}).get('requested'), 'required': uncertainty[:6], 'forbidden': [],
            'source_numbers':bool(task.get('category')=='analysis' and re.search(r'只根据|仅根据|只使用|仅使用',task.get('brief',''))),
            'manual': ['核对目标中的必要事项、事实归属和未确认信息；仅按素材判断，不补造已有结果。'],
            'confirmed': False}


def validate(value):
    from core import Invalid
    if not isinstance(value, dict): raise Invalid('验收条件格式错误')
    length, days = value.get('length'), value.get('days')
    if length is not None and (not isinstance(length, dict) or set(length) != {'min', 'max'} or
            any(type(length[k]) is not int for k in ('min', 'max')) or not 1 <= length['min'] <= length['max'] <= 20000):
        raise Invalid('正文字数范围应为1–20000的整数')
    if days is not None and (type(days) is not int or not 1 <= days <= 31): raise Invalid('日序覆盖应为1–31天')
    if type(value.get('source_numbers',False)) is not bool:raise Invalid('来源数字检查选项无效')
    result = {'version': VERSION, 'length': length, 'days': days, 'confirmed': True,'source_numbers':value.get('source_numbers',False)}
    for key in ('required', 'forbidden', 'manual'):
        values = value.get(key, [])
        if not isinstance(values, list) or len(values) > 20 or any(not isinstance(s, str) or not 1 <= len(s.strip()) <= 500 for s in values):
            raise Invalid('每类最多20项非空验收条件，每项最多500字')
        result[key] = list(dict.fromkeys(s.strip() for s in values))
    if set(result['required']) & set(result['forbidden']): raise Invalid('同一短语不能同时要求保留与禁止')
    return result


def evaluate(task, combo, contract):
    from core import render_variant, variant_for
    sections = [{'block': b['id'], 'title': b['title'], 'text': render_variant(task, variant_for(task, b['id'], combo[b['id']]))}
                for b in task['blocks'] if not b.get('fixed')]
    text = '\n\n'.join(s['text'] for s in sections)
    all_ids = [s['block'] for s in sections]
    checks = []
    if contract.get('length'):
        lo, hi = contract['length']['min'], contract['length']['max']; count = characters(text)
        checks.append({'id': 'length', 'label': f'正文{lo}–{hi}字', 'passed': lo <= count <= hi, 'actual': count, 'blocks': all_ids})
    if contract.get('days'):
        # A range heading is not evidence of daily coverage.
        from ai.requirements import number
        marked = '\n'.join(s['title']+'\n'+s['text'] for s in sections)
        coverage = {number(n) for n in re.findall(r'第([一二三四五六七八九十\d]+)天', marked)}
        missing = sorted(set(range(1, contract['days']+1))-coverage)
        checks.append({'id': 'days', 'label': f'第1–{contract["days"]}天逐日标记', 'passed': not missing, 'actual': {'missing': missing}, 'blocks': all_ids})
    for key, wanted in [('required', True), ('forbidden', False)]:
        for index, phrase in enumerate(contract.get(key, [])):
            found = [s['block'] for s in sections if phrase in s['text']]
            checks.append({'id': f'{key}:{index}', 'label': ('包含原文：' if wanted else '不含原文：')+phrase,
                           'passed': bool(found) == wanted, 'actual': found, 'blocks': all_ids if wanted else found})
    if contract.get('source_numbers'):
        from ai.evidence import literals,aligned
        basis=[task.get('brief','')]+list(task['facts'].values())
        basis += [m['text'] for m in task.get('materials',task.get('ai',{}).get('sources',[]))]
        missing=[]
        for section in sections:
            code=False
            for line in section['text'].splitlines():
                if line.lstrip().startswith('```'):code=not code;continue
                if code:continue
                for literal in literals(line):
                    if literal['kind']=='number' and not any(aligned(literal,source) for source in basis):
                        missing.append({'block':section['block'],'literal':literal['text'],'quote':line})
        checks.append({'id':'source_numbers','label':'数字措辞在目标、固定条件或素材中有相同原文','passed':not missing,
                       'actual':missing,'blocks':sorted({m['block'] for m in missing})})
    return {'method': VERSION, 'contract_hash': digest(contract), 'document_hash': digest(sections),
            'machine_passed': all(c['passed'] for c in checks), 'machine_check_count': len(checks), 'checks': checks,
            'failures': [c for c in checks if not c['passed']], 'manual': contract.get('manual', []),
            'note': '字数按去空白与引用编号的字符计；短语为逐字检查，日序仅核对标记。通过不代表事实、时长或方案正确。'}


def satisfied(task, combo, state):
    contract = state.get('acceptance')
    return not contract or not contract.get('confirmed') or evaluate(task, combo, contract)['machine_passed']


def delivery_report(view):
    contract = view['state'].get('acceptance') or suggest(view['task'])
    result={'contract': contract, **evaluate(view['task'], view['state']['combo'], contract)}
    from ai.retrieval import prepare
    sources=prepare(view['task'].get('materials',[]))
    rounds=next((r['quality_rounds'] for r in reversed(view['task'].get('ai',{}).get('revisions',[])) if r.get('quality_rounds')),[])
    if rounds:
        last=rounds[-1]
        result['latest_review']={'current':last['machine']['document_hash']==result['document_hash'] and last['machine']['contract_hash']==result['contract_hash'] and last['review']['sources_hash']==digest(sources),
                                 'rounds':rounds}
    return result

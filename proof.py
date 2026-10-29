"""Live engineering evidence: isolated sandbox, chain verification, exact splice, constraint analysis."""
import copy
import hashlib
import time
from contextlib import closing

from ai.acceptance import digest, validate as validate_acceptance
from ai.decision import analyze
from core import Invalid, fit, initial_state, recommendations, render
from samples import SAMPLES
from store import Conflict

DEMO_TITLE = '提交协议沙盒'
DEMO_SOURCE = 'proof'
SOLVER_SAMPLE = 'profile'
SOLVER_REQUIRED = '无需付费API'
SPLICE_TEXT = '第一句保持不变。😀 这是要替换的句子。中间不变。这是要替换的句子。最后一句保持不变。'
SPLICE_QUERY = '这是要替换的句子。'


def text_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def utf16_units(value):
    return len(value.encode('utf-16-le')) // 2


def utf16_offset(value, index):
    return utf16_units(value[:index])


def occurrences(text, query):
    if not isinstance(text, str) or not isinstance(query, str) or not query:
        raise Invalid('原文或查找短语无效')
    found = []
    start = text.find(query)
    while start >= 0:
        end = start + len(query)
        found.append({'start': start, 'end': end, 'utf16_start': utf16_offset(text, start), 'utf16_end': utf16_offset(text, end)})
        start = text.find(query, start + 1)
    return found


def splice(text, start, end, replacement):
    if not isinstance(text, str) or not text:
        raise Invalid('原文为空')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise Invalid('选区必须是原文内的有效码点范围')
    if not isinstance(replacement, str) or not 1 <= len(replacement) <= 3000:
        raise Invalid('替换文本应为1–3000字符')
    selected = text[start:end]
    after = text[:start] + replacement + text[end:]
    return {
        'selected': selected,
        'replacement': replacement,
        'after': after,
        'start': start,
        'end': end,
        'selection_codepoints': end - start,
        'selection_utf16_units': utf16_units(selected),
        'utf16_start': utf16_offset(text, start),
        'utf16_end': utf16_offset(text, end),
        'prefix_hash': text_hash(text[:start]),
        'suffix_hash': text_hash(text[end:]),
        'before_hash': text_hash(text),
        'after_hash': text_hash(after),
        'outside_unchanged': after[:start] == text[:start] and after[start + len(replacement):] == text[end:],
        'before_chars': len(text),
        'after_chars': len(after),
    }


def splice_demo():
    return {
        'text': SPLICE_TEXT,
        'query': SPLICE_QUERY,
        'occurrences': occurrences(SPLICE_TEXT, SPLICE_QUERY),
        'note': '同一句话出现两次；服务端按 Unicode 码点定位，浏览器传入 UTF-16 下标，emoji 之后会相差 1。',
    }


def splice_preview(text, query, occurrence=1):
    if not isinstance(text, str) or not 1 <= len(text) <= 20000:
        raise Invalid('原文应为1–20000字符')
    found = occurrences(text, query)
    if not found:
        raise Invalid('原文中没有找到这个短语')
    if type(occurrence) is not int or not 1 <= occurrence <= len(found):
        raise Invalid('出现位置应为有效序号')
    chosen = found[occurrence - 1]
    selected = text[chosen['start']:chosen['end']]
    return {'text': text, 'query': query, 'occurrence': occurrence, 'count': len(found), 'range': chosen,
            'selection': selected,
            'prefix_hash': text_hash(text[:chosen['start']]), 'suffix_hash': text_hash(text[chosen['end']:]),
            'selection_hash': text_hash(selected), 'occurrences': found}


def _demo_task():
    task = copy.deepcopy(next(s for s in SAMPLES if s['id'] == SOLVER_SAMPLE))
    task['title'] = DEMO_TITLE
    task['source'] = DEMO_SOURCE
    task['brief'] = '验证提交协议与并发控制的隔离沙盒；内容为示例数据。'
    return task


def demo_session(store):
    for item in store.sessions():
        if item.get('source') == DEMO_SOURCE:
            return item['id']
    return store.create(_demo_task())


def new_demo_session(store):
    task = _demo_task()
    task['title'] = DEMO_TITLE + ' ' + time.strftime('%H:%M:%S')
    return store.create(task)


def _event_summary(event, titles=None):
    payload = event.get('payload') or {}
    titles = titles or {}
    kind = event['kind']
    if kind == 'created':
        text = '创建会话'
    elif kind == 'lock':
        text = ('锁定 ' if payload.get('locked') else '解锁 ') + str(titles.get(payload.get('block'), payload.get('block', '')))
    elif kind == 'select':
        text = '选择 ' + str(titles.get(payload.get('block'), payload.get('block', ''))) + ' → ' + str(payload.get('variant', ''))
    elif kind == 'undo':
        text = '撤回 ' + str(payload.get('kind', ''))
    elif kind == 'export':
        text = '导出正文'
    elif kind == 'audit_export':
        text = '导出审计包'
    elif kind == 'compare':
        text = '明确比较：' + str(payload.get('choice', ''))
    elif kind == 'skip':
        text = '跳过比较'
    else:
        text = kind
    return {'kind': kind, 'text': text, 'training_label': payload.get('training_label') is True}


def _snapshot_hashes(events, titles=None):
    result = []
    for event in events:
        before = event.get('before_state')
        after = event.get('after_state')
        result.append({**{k: event[k] for k in ('seq', 'id', 'kind', 'revision', 'created')},
                       'summary': _event_summary(event, titles),
                       'before_hash': digest(before) if before is not None else None,
                       'after_hash': digest(after) if after is not None else None})
    return result


def chain_report(store, sid):
    with closing(store.connect()) as db:
        task, state, revision = store.load(db, sid)
        events = store.events(db, sid)
    active = store.active(events)
    active_ids = {e['id'] for e in active}
    checks = []
    mutations = [e for e in events if e.get('before_state') is not None or e.get('after_state') is not None]
    previous_after = None
    previous_revision = None
    chain_ok = True
    revision_ok = True
    for event in mutations:
        if previous_after is not None and event.get('before_state') != previous_after:
            chain_ok = False
        if previous_revision is not None and event['revision'] != previous_revision + 1:
            revision_ok = False
        previous_after = event.get('after_state')
        previous_revision = event['revision']
    if mutations:
        chain_ok = chain_ok and mutations[-1].get('after_state') == state
        revision_ok = revision_ok and mutations[-1]['revision'] == revision
    else:
        chain_ok = revision == 0
        revision_ok = revision == 0
    seq_ok = all(a['seq'] < b['seq'] for a, b in zip(events, events[1:]))
    labels_ok = all((e.get('payload') or {}).get('training_label') is not True or e['kind'] == 'compare' for e in events)
    undo_ok = all(any(candidate['id'] == e['payload'].get('target') for candidate in events) and e['payload'].get('target') not in active_ids
                  for e in events if e['kind'] == 'undo')
    checks.extend([
        {'id': 'snapshot_chain', 'label': '事件前后快照首尾相接，最后快照等于当前存储状态', 'passed': chain_ok},
        {'id': 'revision_monotonic', 'label': '可变更事件按 +1 递增，当前 revision 与最后事件一致', 'passed': revision_ok},
        {'id': 'sequence', 'label': '事件顺序严格递增', 'passed': seq_ok},
        {'id': 'labels', 'label': '只有明确 compare 事件带训练标签', 'passed': labels_ok},
        {'id': 'undo_target', 'label': '撤回目标存在且不再处于活动事件中', 'passed': undo_ok},
    ])
    return {
        'ok': all(c['passed'] for c in checks),
        'checks': checks,
        'session': {'id': sid, 'title': task['title'], 'source': task.get('source'), 'revision': revision},
        'state': state,
        'task': {'title': task['title'], 'blocks': [{'id': b['id'], 'title': b['title']} for b in task['blocks']]},
        'hashes': {'state': digest(state), 'document': digest(render(task, state['combo'])), 'first_state': digest(mutations[0]['before_state']) if mutations else None},
        'events_total': len(events),
        'mutations': len(mutations),
        'active_events': len(active),
        'labels': sum(1 for e in active if e['kind'] == 'compare'),
        'events': _snapshot_hashes(events, {b['id']: b['title'] for b in task['blocks']}),
        'note': '这里做的是本地快照一致性校验，不是密码学不可篡改证明。',
    }


def toggle_lock(store, sid, revision, locked=True):
    with closing(store.connect()) as db:
        task, state, current = store.load(db, sid)
    if task.get('source') != DEMO_SOURCE:
        raise Invalid('提交协议沙盒只允许操作 proof 来源的隔离会话')
    if type(revision) is not int or revision != current:
        raise Conflict('旧 revision 已被拒绝；当前版本是 v' + str(current))
    block = next((b['id'] for b in task['blocks'] if not b.get('fixed')), None)
    if not block:
        raise Invalid('沙盒任务没有可锁定章节')
    if type(locked) is not bool:
        raise Invalid('锁定状态应为布尔值')
    if (block in state['locks']) == locked:
        raise Invalid('章节已处于该锁定状态，无需重复提交')
    store.action(sid, {'kind': 'lock', 'block': block, 'revision': revision})
    return block


def _solver_task():
    return copy.deepcopy(next(s for s in SAMPLES if s['id'] == SOLVER_SAMPLE))


def _combo_mix(task, combo):
    letters = []
    for block in task['blocks']:
        ids = [v['id'] for v in block['variants']]
        letters.append('ABC'[ids.index(combo[block['id']])] if combo.get(block['id']) in ids else '?')
    return ' / '.join(letters)


def solver_report(lock=False, require_phrase=False, max_chars=None):
    task = _solver_task()
    state = initial_state(task)
    if lock:
        state['locks']['technical'] = 'technical-1'
    if max_chars is not None:
        if type(max_chars) is not int or not 1 <= max_chars <= 20000:
            raise Invalid('字数上限应为1–20000的整数')
        state['max_chars'] = max_chars
    if require_phrase:
        state['acceptance'] = validate_acceptance({'length': None, 'days': None, 'required': [SOLVER_REQUIRED],
                                                   'forbidden': [], 'manual': [], 'source_numbers': False})
    started = time.perf_counter()
    ranks, count = recommendations(task, state, fit(task, []))
    report = analyze(task, state, ranks, 0)
    elapsed_ms = (time.perf_counter() - started) * 1000
    corrections = []
    for item in report['corrections']:
        corrections.append({'relax': [c['label'] for c in item['relax']],
                            'witness': _combo_mix(task, item['witness_combo']),
                            'witness_changes': item['witness_changes'],
                            'adoptable_under_current_conditions': item['adoptable_under_current_conditions']})
    frontier = [{k: p[k] for k in ('id', 'score', 'change_count', 'equivalent_count')} for p in report['frontier']]
    return {
        'inputs': {'lock_technical': bool(lock), 'require_phrase': bool(require_phrase), 'max_chars': max_chars},
        'task': {'title': task['title'], 'blocks': [{'id': b['id'], 'title': b['title']} for b in task['blocks']],
                 'required_phrase': SOLVER_REQUIRED if require_phrase else None},
        'universe': report['universe'],
        'eligible': report['eligible'],
        'elapsed_ms': round(elapsed_ms, 2),
        'paid_calls': 0,
        'constraints': report['constraints'],
        'conflict_core': report['conflict_core'],
        'corrections': corrections,
        'correction_count': report['correction_count'],
        'sensitivity': report['sensitivity'],
        'frontier': frontier,
        'method': report['method'],
        'limits': report['limits'],
        'space_hash': report['space']['hash'],
        'note': '纯本地枚举与位集运算；不含 HTTP、模型调用或人工核对。',
    }


def apply_splice(text, start, end, replacement, prefix_hash, suffix_hash, selection_hash):
    if not isinstance(text, str) or not text:
        raise Invalid('原文为空')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise Invalid('选区必须是原文内的有效码点范围')
    if not isinstance(replacement, str) or not 1 <= len(replacement) <= 3000:
        raise Invalid('替换文本应为1–3000字符')
    if text_hash(text[:start]) != prefix_hash or text_hash(text[end:]) != suffix_hash or text_hash(text[start:end]) != selection_hash:
        raise Conflict('原文已变化，过期的替换请求被拒绝；请重新定位选区')
    receipt = splice(text, start, end, replacement)
    receipt['receipt_hash'] = digest({k: receipt[k] for k in ('before_hash', 'after_hash', 'prefix_hash', 'suffix_hash', 'start', 'end')})
    return receipt


def state_report(store, service=None):
    sid = demo_session(store)
    report = chain_report(store, sid)
    return {
        'chain': report,
        'ledger': job_ledger(service),
        'splice': splice_demo(),
        'sandbox': {'database': 'proof.sqlite3', 'production_untouched': True,
                    'note': '本页所有写入只发生在隔离的 proof.sqlite3；示例正文来自自带的 profile 模板。'},
        'capabilities': ['revision-cas', 'snapshot-chain', 'exact-splice', 'constraint-core', 'job-ledger'],
    }


def job_ledger(service, limit=10):
    if service is None:
        return []
    rows = []
    for job in service.jobs()[:limit]:
        try:
            raw = service.job(job['id'])
        except Invalid:
            continue
        inputs = raw.get('input') or {}
        result = raw.get('result') or {}
        attempts = result.get('attempts') if isinstance(result, dict) else None
        rows.append({
            'id': job['id'][:10],
            'kind': job['kind'],
            'status': job['status'],
            'session': (job.get('session') or '')[:10],
            'created': job.get('created'),
            'updated': job.get('updated'),
            'progress': job.get('progress'),
            'retry': bool(inputs.get('retry_of')),
            'model': inputs.get('model'),
            'provider': (inputs.get('connection') or {}).get('provider'),
            'call_limit': inputs.get('call_limit'),
            'attempts': len(attempts) if isinstance(attempts, list) else 0,
            'input_hash': digest(inputs)[:16],
            'config_hash': digest(inputs.get('connection') or {})[:16],
        })
    return rows

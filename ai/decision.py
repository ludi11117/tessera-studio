"""Exact task-local decision analysis. No generation, mutation, or new labels.

The universe is bounded by the validated task (at most 3**6 combinations).
Fixed content is part of the universe, never a suggested relaxation.
"""
import itertools
import math

from ai.acceptance import digest, evaluate
from ai.options import describe, distance
from ai.requirements import characters
from core import render


def analyze(task, state, ranks, pairs=0, model_config=None):
    keys = [b['id'] for b in task['blocks']]
    universe = [dict(zip(keys, values)) for values in itertools.product(*[
        [state['locks'][b['id']]] if b.get('fixed') else [v['id'] for v in b['variants']]
        for b in task['blocks']])]
    contract = state.get('acceptance') or {}
    constraints = []
    for block in task['blocks']:
        if not block.get('fixed') and block['id'] in state['locks']:
            constraints.append({'id': 'lock:'+block['id'], 'label': '锁定：'+block['title'], 'kind': 'lock', 'block': block['id']})
    if state.get('max_chars') is not None:
        constraints.append({'id': 'max_chars', 'label': '原全文长度上限：'+str(state['max_chars']), 'kind': 'max_chars'})
    reports = [evaluate(task, c, contract) for c in universe] if contract.get('confirmed') else []
    if reports:
        constraints += [{'id': c['id'], 'label': c['label'], 'kind': 'acceptance'} for c in reports[0]['checks']]
    from ai.preservation import checks as preservation_checks
    fragment_reports = [preservation_checks(task, c, state) for c in universe]
    if fragment_reports:
        constraints += [{k:c[k] for k in ('id','label','kind','block','text')} for c in fragment_reports[0]]
    # One bit per candidate document; conjunction is a bitwise intersection.
    masks = []
    failures = []
    for i, combo in enumerate(universe):
        passed = {c['id']: c['passed'] for c in reports[i]['checks']} if reports else {}
        passed.update({c['id']:c['passed'] for c in fragment_reports[i]})
        failed = set()
        for j, condition in enumerate(constraints):
            kind, cid = condition['kind'], condition['id']
            ok = (combo[condition['block']] == state['locks'][condition['block']] if kind == 'lock'
                  else len(render(task, combo)) <= state['max_chars'] if kind == 'max_chars' else passed[cid])
            if not ok: failed.add(j)
        failures.append(frozenset(failed))
    for j in range(len(constraints)):
        masks.append(sum(1 << i for i, failed in enumerate(failures) if j not in failed))
    all_bits = (1 << len(universe)) - 1

    def intersection(indices):
        bits = all_bits
        for j in indices: bits &= masks[j]
        return bits

    eligible_bits = intersection(range(len(constraints)))
    eligible = eligible_bits.bit_count()
    # Fail closed if solver and decision analyzer ever disagree.
    rank_keys = {digest(r['combo']) for r in ranks}
    expected = {digest(c) for i, c in enumerate(universe) if eligible_bits & (1 << i)}
    if rank_keys != expected or len(ranks) != eligible:
        from core import Invalid
        raise Invalid('组合搜索与决策分析结果不一致，请重新载入')
    if any(not math.isfinite(r['score']) for r in ranks):
        from core import Invalid
        raise Invalid('偏好得分无效，无法生成决策证据')
    max_changes = sum(not b.get('fixed') for b in task['blocks'])
    ranked = sorted(ranks, key=lambda r: (-r['score'], distance(task, r['combo'], state['combo']), tuple(r['combo'].values())))
    points, budget_curve = [], []
    for budget in range(max_changes+1):
        pool = [r for r in ranked if distance(task, r['combo'], state['combo']) <= budget]
        best = pool[0] if pool else None
        budget_curve.append({'budget': budget, 'eligible': len(pool), 'best_id': digest(best['combo']) if best else None})
        # A non-dominated representative for each (change count, score) point.
        if best:
            changes = distance(task, best['combo'], state['combo'])
            if not points or best['score'] > points[-1]['score']:
                points.append({'id': digest(best['combo']), 'score': best['score'], 'change_count': changes,
                               'equivalent_count': sum(distance(task, r['combo'], state['combo']) == changes and r['score'] == best['score'] for r in ranks),
                               **describe(task, state, best['combo'])})
    conflict, corrections = [], []
    correction_count = 0
    if not eligible:
        # Deletion yields ONE irreducible unsatisfiable subset, not a smallest core.
        core = list(range(len(constraints)))
        for j in list(core):
            reduced = [k for k in core if k != j]
            if not intersection(reduced): core = reduced
        conflict = [constraints[j] for j in core]
        # Every distinct failure set has a witness. Drop strict supersets to obtain
        # ALL inclusion-minimal correction sets over this finite universe.
        minimal = []
        for failed in sorted(set(failures), key=lambda s: (len(s), tuple(sorted(s)))):
            if not any(previous <= failed for previous in minimal): minimal.append(failed)
        correction_count = len(minimal)
        for failed in minimal[:6]:
            candidates = [c for c, f in zip(universe, failures) if f == failed]
            witness = min(candidates, key=lambda c: (distance(task, c, state['combo']), tuple(c.values())))
            corrections.append({'relax': [constraints[j] for j in sorted(failed)], 'witness_combo': witness,
                                'witness_changes': distance(task, witness, state['combo']), 'adoptable_under_current_conditions': False})
    sensitivity = []
    for j, condition in enumerate(constraints):
        count = intersection(k for k in range(len(constraints)) if k != j).bit_count()
        sensitivity.append({**condition, 'eligible_without': count, 'newly_eligible': count-eligible})
    # Compact exact feasible table: no repeated document text and no API calls.
    # Browser indexes this immutable, revision-bound table for interactive queries.
    from core import render_variant, variant_for
    space = {'version': 'configuration-space-v1', 'candidates': [
        {'id': digest(r['combo']), 'combo': r['combo'], 'score': r['score'],
         'change_count': distance(task, r['combo'], state['combo']),
         'body_characters': characters('\n\n'.join(render_variant(task, variant_for(task, b['id'], r['combo'][b['id']]))
                                                  for b in task['blocks'] if not b.get('fixed')))}
        for r in ranked]}
    space['hash'] = digest(space)
    return {'version': 'decision-analysis-v1', 'paid_calls': 0, 'read_only': True,
            'universe': len(universe), 'eligible': eligible, 'constraints': constraints,
            'current_eligible': digest(state['combo']) in expected,
            'pair_count': pairs, 'score_basis': 'learned_preference' if pairs else 'unvalidated_prior',
            'model': model_config or {}, 'frontier': points, 'budget_curve': budget_curve, 'space': space,
            'conflict_core': conflict, 'corrections': corrections, 'correction_count': correction_count,
            'sensitivity': sensitivity, 'hash': digest({'task': digest(task), 'state': digest(state), 'model': model_config,
                                                      'objectives': [{'combo': r['combo'], 'score': r['score']} for r in ranked]}),
            'method': {'search': 'finite exhaustive search', 'frontier': 'maximize preference score / minimize changed chapters',
                       'core': 'deletion-based inclusion-minimal unsatisfiable subset',
                       'corrections': 'inclusion-minimal witnessed failure sets', 'sensitivity': 'leave-one-constraint-out exact counts'},
            'limits': ['只在当前有限候选中精确成立，不是连续文本空间的最优解。',
                       '偏好分数不是正确率；改动章节数不是工时或费用。',
                       '冲突核不可再删条件，但不保证条件数最少；修正建议不会自动放宽条件。',
                       '机器条件通过仍需核对事实、语义和实际可执行性。']}

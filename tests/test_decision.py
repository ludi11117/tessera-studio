import copy
import itertools
import tempfile
import unittest
from pathlib import Path

from ai.acceptance import validate
from ai.decision import analyze
from core import Invalid, enumerate_feasible, fit, initial_state, recommendations
from store import Conflict, Store


def task():
    return {'title': '决策开发样本', 'source': 'example', 'category': 'writing', 'brief': '比较已存在的章节', 'facts': {},
            'blocks': [{'id': bid, 'title': bid, 'variants': [{'id': bid+str(j), 'template': char*n}
                for j, n in enumerate([10, 30, 50])]} for bid, char in [('left', '甲'), ('right', '乙')]]}


class DecisionTests(unittest.TestCase):
    def test_configuration_table_covers_every_feasible_document_without_text_duplication(self):
        from ai.options import describe
        t = task();s = initial_state(t)
        s['locks'] = {'left': 'left1'}
        s['acceptance'] = validate({'length': {'min': 45, 'max': 70}})
        ranks, _ = recommendations(t, s, fit(t, []))
        before = copy.deepcopy((t, s, ranks))
        space = analyze(t, s, ranks)['space']
        self.assertEqual(len(ranks), len(space['candidates']))
        self.assertEqual({tuple(sorted(r['combo'].items())) for r in ranks},
                         {tuple(sorted(c['combo'].items())) for c in space['candidates']})
        for c in space['candidates']:
            detail = describe(t, s, c['combo'])
            self.assertTrue(detail['can_apply'])
            self.assertEqual(detail['body_characters'], c['body_characters'])
            self.assertEqual(len(detail['changes']), c['change_count'])
            self.assertNotIn('sections', c)
        self.assertEqual(before, (t, s, ranks))
        self.assertEqual(space['hash'], analyze(t, s, list(reversed(ranks)))['space']['hash'])

    def test_frontier_and_budget_optima_against_brute_force_oracle(self):
        t = task(); state = initial_state(t)
        ranks = [{'combo': c, 'score': [0, 2, 1][int(c['left'][-1])]+[0, 1, 4][int(c['right'][-1])]}
                 for c in enumerate_feasible(t, state)]
        r = analyze(t, state, ranks, 3)
        expected = [c for c in ranks if not any(
            p['score'] >= c['score'] and sum(p['combo'][k] != state['combo'][k] for k in p['combo']) <= sum(c['combo'][k] != state['combo'][k] for k in c['combo'])
            and (p['score'] > c['score'] or sum(p['combo'][k] != state['combo'][k] for k in p['combo']) < sum(c['combo'][k] != state['combo'][k] for k in c['combo'])) for p in ranks)]
        self.assertEqual({(p['score'], sum(p['combo'][k] != state['combo'][k] for k in p['combo'])) for p in expected}, {(p['score'], p['change_count']) for p in r['frontier']})
        points = {p['id']: p for p in r['frontier']}
        for row in r['budget_curve']:
            pool = [p for p in ranks if sum(p['combo'][k] != state['combo'][k] for k in p['combo']) <= row['budget']]
            self.assertEqual(len(pool), row['eligible'])
            self.assertEqual(max(p['score'] for p in pool), points[row['best_id']]['score'])

    def test_conflict_is_irreducible_and_corrections_have_complete_minimal_witnesses(self):
        t = task(); state = initial_state(t);state['acceptance'] = validate({'length': {'min': 40, 'max': 40}})
        state['locks'] = dict(state['combo'])
        r = analyze(t, state, [])
        self.assertEqual(3, len(r['conflict_core']))
        self.assertEqual(3, r['correction_count'])
        for core in itertools.combinations(r['conflict_core'], 2):
            changed = copy.deepcopy(state)
            for key in list(changed['locks']):
                if 'lock:'+key not in {c['id'] for c in core}: del changed['locks'][key]
            if 'length' not in {c['id'] for c in core}: changed['acceptance'] = None
            self.assertTrue(enumerate_feasible(t, changed))
        for correction in r['corrections']:
            self.assertEqual(1, len(correction['relax']))
            self.assertFalse(correction['adoptable_under_current_conditions'])
            changed = copy.deepcopy(state); condition = correction['relax'][0]
            if condition['kind'] == 'lock': del changed['locks'][condition['block']]
            else: changed['acceptance'] = None
            self.assertIn(correction['witness_combo'], enumerate_feasible(t, changed))
        self.assertEqual([1, 1, 1], [s['newly_eligible'] for s in r['sensitivity']])

    def test_fixed_content_is_not_a_relaxation_and_ties_have_one_representative(self):
        t = task(); fixed = t['blocks'][0];fixed['fixed'] = True
        for v in fixed['variants']: v['template'] = '固定内容'
        state = initial_state(t); ranks, _ = recommendations(t, state, fit(t, []))
        r = analyze(t, state, ranks)
        self.assertEqual(3, r['universe']);self.assertEqual([], r['constraints'])
        self.assertEqual(1, len(r['frontier']));self.assertEqual(0, r['frontier'][0]['change_count'])
        self.assertEqual('unvalidated_prior', r['score_basis'])
        state['acceptance'] = validate({'required': ['候选不存在的内容']})
        r = analyze(t, state, [])
        self.assertEqual(['required:0'], [c['id'] for c in r['conflict_core']])
        self.assertTrue(all(c['kind'] != 'lock' for c in r['corrections'][0]['relax']))

    def test_snapshot_is_read_only_and_stale_or_inconsistent_analysis_fails(self):
        root = Path('D:/CodexWork/temp/intent-decision-tests');root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            store = Store(Path(folder)/'qa.sqlite3');sid = store.create(task())
            before = store.audit(sid);before.pop('exported_at')
            r = store.decision(sid, 0)
            self.assertEqual(9, r['eligible']);self.assertEqual(0, r['paid_calls'])
            after = store.audit(sid);after.pop('exported_at');self.assertEqual(before, after)
            for bad in [True, '0', 1, None]:
                with self.assertRaises(Conflict): store.decision(sid, bad)
            with self.assertRaises(Invalid): analyze(task(), initial_state(task()), [])

    def test_sensitivity_agrees_with_independent_constraint_removal(self):
        t = task();state = initial_state(t);state['locks'] = {'left': 'left0'};state['max_chars'] = 50
        state['acceptance'] = validate({'length': {'min': 40, 'max': 60}})
        ranks, _ = recommendations(t, state, fit(t, []));r = analyze(t, state, ranks)
        for s in r['sensitivity']:
            changed = copy.deepcopy(state)
            if s['kind'] == 'lock': changed['locks'].pop(s['block'])
            elif s['kind'] == 'max_chars': changed['max_chars'] = None
            else: changed['acceptance']['length'] = None
            self.assertEqual(len(enumerate_feasible(t, changed)), s['eligible_without'])

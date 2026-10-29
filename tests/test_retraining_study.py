import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional NumPy environment')
class RetrainingStudyTests(unittest.TestCase):
    def test_all_policies_exclude_seen_and_use_same_candidate_bank(self):
        import numpy as np
        from research.retraining_study import choose_query,POLICIES
        scores=np.array([[2.,0.,1.],[0.,2.,1.]])
        for policy in POLICIES:
            seen={(0,1),(0,2)}
            pair,_=choose_query(scores,seen,policy,np.random.default_rng(1))
            self.assertEqual((1,2),tuple(sorted(pair)))
            with self.assertRaises(ValueError):choose_query(scores,{(0,1),(0,2),(1,2)},policy,np.random.default_rng(1))

    def test_regret_counts_all_optima_and_pairwise_ties(self):
        from research.retraining_study import evaluate
        r=evaluate([0,1,0],[2,2,0]);self.assertEqual(0,r['normalized_regret']);self.assertTrue(r['optimal_hit']);self.assertEqual(.75,r['pair_agreement'])
        r=evaluate([0,0,1],[2,2,0]);self.assertEqual(1,r['normalized_regret']);self.assertFalse(r['optimal_hit'])

    def test_seed_cluster_interval_preserves_profile_pairing(self):
        from research.retraining_study import clustered_interval
        r=clustered_interval([1,-1,2,-2],[1,1,2,2]);self.assertEqual([0.,0.],r['seed_cluster_bootstrap_95_percentile'])
        with self.assertRaises(ValueError):clustered_interval([1],[1,2])

    def test_real_fit_uses_new_feedback_and_enters_full_depth_at_eight(self):
        from test_deep_learning import task,FixtureSemantic,pairs_for
        from research.deep_preference import DeepPreferenceModel,SemanticLinearModel,training_hash
        from core import enumerate_feasible,initial_state
        from research.retraining_study import choose_query
        import numpy as np
        t=task();pairs=pairs_for(t,8);sem=FixtureSemantic()
        initial=DeepPreferenceModel(t,sem).fit(pairs[:4],steps=40)
        updated=DeepPreferenceModel(t,sem).fit(pairs,steps=40)
        self.assertEqual('last_hidden_layer',initial.report['phase']);self.assertEqual('all_preference_layers',updated.report['phase'])
        self.assertEqual(training_hash(t,pairs),updated.report['label_hash']);self.assertNotEqual(initial.metadata()['weights_hash'],updated.metadata()['weights_hash'])
        combos=enumerate_feasible(t,initial_state(t));scores=updated.score_heads(combos)@updated.head_weights()
        pair,_=choose_query(scores,set(),'decision_value',np.random.default_rng(0))
        self.assertEqual(2,len(set(pair)));self.assertEqual(8,SemanticLinearModel(updated).n)

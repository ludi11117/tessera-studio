import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional NumPy environment')
class DecisionValueTests(unittest.TestCase):
    def test_binary_closed_form_and_branch_probability(self):
        import numpy as np
        from research.decision_value import forecast
        r = forecast([[2, 0], [0, 2]], (0, 1))
        self.assertAlmostEqual(1., r['current_regret'])
        self.assertAlmostEqual(.5, r['probability_a'])
        self.assertAlmostEqual(2/(1+np.exp(2)), r['expected_remaining_regret'])
        self.assertAlmostEqual(1., sum(b['probability'] for b in r['branches']))
        self.assertEqual([0, 1], [b['action'] for b in r['branches']])

    def test_information_is_not_identical_to_decision_value(self):
        from research.decision_value import forecast, select
        # Hypotheses disagree strongly about irrelevant options 1/2, yet all
        # prefer option 0. A response cannot improve the decision under this set.
        s = [[10, 5, 0], [10, 0, 5]]
        self.assertAlmostEqual(0., forecast(s, (1, 2))['value'])
        self.assertEqual('entropy_fallback_no_positive_value', select(s)['selection'])

    def test_minimax_differs_from_mean_and_offsets_do_not_change_values(self):
        import numpy as np
        from research.decision_value import risk, forecast
        s = np.array([[10., 6., 0.], [10., 6., 0.], [0., 6., 10.]])
        r = risk(s);self.assertEqual(0, r['mean_action']);self.assertEqual(1, r['minimax_action'])
        self.assertLess(r['minimax_worst_regret'], r['worst_member_regret'])
        shifted = s+np.array([[500.], [-300.], [20.]])
        self.assertAlmostEqual(forecast(s, (0, 2))['value'], forecast(shifted, (0, 2))['value'])

    def test_nonnegative_value_and_total_expectation_against_enumerated_oracle(self):
        import numpy as np
        from research.decision_value import forecast, select
        rng = np.random.default_rng(27);s = rng.normal(size=(5, 7));w = rng.random(5);w /= w.sum()
        values = []
        for i in range(7):
            for j in range(i+1, 7):
                r = forecast(s, (i, j), w);p = 1/(1+np.exp(-(s[:, i]-s[:, j])))
                expected_best = max(s.T@(w*p))+max(s.T@(w*(1-p)))
                exact = expected_best-max(s.T@w)
                self.assertAlmostEqual(max(0., exact), r['value']);self.assertGreaterEqual(r['value'], 0)
                values.append(r['value'])
        self.assertAlmostEqual(max(values), select(s, w)['value'])
        self.assertIsNone(select(s, allowed=lambda i, j: False))

    def test_invalid_input_and_degenerate_support(self):
        from research.decision_value import risk, forecast, select
        for s in [[], [[float('nan')]], [[[1]]]]:
            with self.assertRaises(ValueError): risk(s)
        with self.assertRaises(ValueError): risk([[1], [2]], [0, 0])
        with self.assertRaises(ValueError): forecast([[1, 2]], (0, 0))
        self.assertEqual(0., risk([[1, 2]])['expected_regret'])
        self.assertEqual('entropy_fallback_no_positive_value', select([[1, 2]])['selection'])

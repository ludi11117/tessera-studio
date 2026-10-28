"""Fixed-budget finite-hypothesis acquisition study, not a real-user study.

Independent simulated response oracle; matched feasible pools, response draws,
initial hypotheses, and comparison budgets for all three policies. No API calls.
"""
import itertools
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
import numpy as np
from research.decision_value import select


def run():
    folder = ROOT/'experiments/runs'/('decision-value-'+str(time.time_ns()));folder.mkdir(parents=True)
    records = [];inputs = []
    for track in ['truth_in_hypotheses', 'misspecified_truth']:
        for seed in range(12):
            rng = np.random.default_rng(101+seed)
            x = rng.normal(size=(12, 6));theta = rng.normal(size=(9, 6))
            scores = theta@x.T/2
            truth = scores[seed % 9] if track == 'truth_in_hypotheses' else rng.normal(size=6)@x.T/2
            draws = rng.random(6)
            inputs.append({'track': track, 'seed': seed, 'scores': scores.tolist(), 'truth': truth.tolist(), 'response_uniforms': draws.tolist()})
            for policy in ['random', 'entropy', 'decision_value']:
                w = np.ones(9)/9;seen = set();random = np.random.default_rng(900+seed)
                for step in range(7):
                    means = w@scores;action = int(np.argmax(means))
                    record = {'track': track, 'seed': seed, 'policy': policy, 'comparisons': step, 'recommendation': action,
                              'true_regret': float(truth.max()-truth[action]), 'hit': bool(action == truth.argmax()), 'weights': w.tolist()}
                    records.append(record)
                    if step == 6: break
                    available = [(i, j) for i, j in itertools.combinations(range(12), 2) if (i, j) not in seen]
                    if policy == 'decision_value':
                        r = select(scores, w, lambda i, j: tuple(sorted((i, j))) not in seen);i, j = r['pair'];record['forecast_value'] = r['value']
                    elif policy == 'random': i, j = available[int(random.integers(len(available)))]
                    else:
                        def close(pair):
                            i, j = pair;p = float(w@(1/(1+np.exp(-np.clip(scores[:, i]-scores[:, j], -40, 40)))))
                            return abs(p-.5)
                        i, j = min(available, key=close)
                    seen.add(tuple(sorted((i, j))))
                    probability = float(1/(1+np.exp(-np.clip(truth[i]-truth[j], -40, 40))))
                    answer = bool(draws[step] < probability)
                    likelihood = 1/(1+np.exp(-np.clip(scores[:, i]-scores[:, j], -40, 40)))
                    w *= likelihood if answer else 1-likelihood;w /= w.sum()
                    record.update(query=[i, j], oracle_prefers_a=answer, oracle_probability_a=probability)
    summaries = []
    for track in ['truth_in_hypotheses', 'misspecified_truth']:
        for policy in ['random', 'entropy', 'decision_value']:
            for budget in [0, 2, 4, 6]:
                rows = [r for r in records if r['track'] == track and r['policy'] == policy and r['comparisons'] == budget]
                summaries.append({'track': track, 'policy': policy, 'budget': budget, 'scenarios': len(rows),
                                  'mean_true_regret': float(np.mean([r['true_regret'] for r in rows])),
                                  'winner_hit_rate': float(np.mean([r['hit'] for r in rows]))})
    report = {'result': 'completed', 'paid_calls': 0, 'synthetic': True, 'budgets': [0, 2, 4, 6], 'seeds': list(range(12)),
              'hypotheses': 9, 'feasible_options': 12, 'summary': summaries,
              'limits': ['Small designed synthetic study; no measured user benefit.', 'Fixed hypothesis reweighting, no neural retraining in this study.',
                         'Online neural ensemble has 3 uncalibrated initialization members, not these 9 oracle hypotheses.']}
    for name, data in [('inputs.json', inputs), ('trajectory.json', records), ('report.json', report)]:
        (folder/name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder/'algorithm.py').write_text((ROOT/'research/decision_value.py').read_text(encoding='utf-8'), encoding='utf-8')
    (folder/'experiment.py').write_text(Path(__file__).read_text(encoding='utf-8'), encoding='utf-8')
    print(json.dumps({'folder': str(folder), 'final_budget': [s for s in summaries if s['budget'] == 6]}, indent=2))


if __name__ == '__main__': run()

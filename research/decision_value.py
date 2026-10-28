"""One-step value of binary feedback over a finite, frozen utility hypothesis set.

Exact conditional enumeration within this discrete model, not a calibrated
posterior over neural networks and not a continuous-space qEUBO implementation.
"""
import hashlib
import itertools
import numpy as np


def validated(scores, weights=None):
    s = np.asarray(scores, dtype=float)
    if s.ndim != 2 or min(s.shape) < 1 or not np.isfinite(s).all():
        raise ValueError('Expected finite hypothesis-by-option scores')
    w = np.ones(len(s)) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != (len(s),) or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError('Invalid hypothesis weights')
    # Row offsets have no decision meaning; subtract them for stable arithmetic.
    s = s-s.max(axis=1, keepdims=True)
    return s, w/w.sum()


def risk(scores, weights=None):
    s, w = validated(scores, weights)
    means = w@s; regrets = -s
    action = int(np.argmax(means)); worst = regrets[w>0].max(axis=0);robust = int(np.argmin(worst))
    votes = np.bincount(s.argmax(axis=1), weights=w, minlength=s.shape[1])
    return {'mean_action': action, 'minimax_action': robust,
            'expected_regret': float(-means[action]),
            'worst_member_regret': float(worst[action]),
            'minimax_worst_regret': float(worst[robust]),
            'winner_weight': float(votes[action]), 'hypotheses': len(s),
            'supported_winners': int(np.count_nonzero(votes)),
            'scores_hash': hashlib.sha256(s.astype('<f8').tobytes()+w.astype('<f8').tobytes()).hexdigest()}


def forecast(scores, pair, weights=None, temperature=1.):
    s, w = validated(scores, weights)
    if not np.isfinite(temperature) or temperature <= 0: raise ValueError('Invalid response temperature')
    i, j = pair
    if not (0 <= i < s.shape[1] and 0 <= j < s.shape[1]) or i == j: raise ValueError('Invalid query pair')
    likelihood = 1/(1+np.exp(-np.clip((s[:, i]-s[:, j])/temperature, -40, 40)))
    branches = []; remaining = 0.
    for response, like in [('a', likelihood), ('b', 1-likelihood)]:
        mass = float(w@like)
        if mass <= 1e-15: continue
        posterior = w*like/mass
        means = posterior@s; action = int(np.argmax(means)); regret = float(-means[action])
        remaining += mass*regret
        branches.append({'response': response, 'probability': mass, 'action': action,
                         'expected_regret': regret, 'weights': posterior.tolist()})
    current = float(-np.max(w@s))
    return {'pair': [i, j], 'probability_a': float(w@likelihood),
            'current_regret': current, 'expected_remaining_regret': remaining,
            'value': max(0., current-remaining), 'branches': branches}


def select(scores, weights=None, allowed=None, limit=24):
    s, w = validated(scores, weights)
    # Query pool covers mean leaders, each hypothesis winner and disagreement.
    order = list(np.argsort(-(w@s), kind='stable')[:12])
    order += list(s.argmax(axis=1))
    order += list(np.argsort(-np.var(s, axis=0), kind='stable')[:6])
    order += list(np.argsort(-(w@s), kind='stable'))
    pool = list(dict.fromkeys(map(int, order)))[:limit]
    options = []
    for i, j in itertools.combinations(pool, 2):
        if allowed is not None and not allowed(i, j): continue
        f = forecast(s, (i, j), w)
        p = f['probability_a'];f['entropy'] = float(-p*np.log(max(p, 1e-15))-(1-p)*np.log(max(1-p, 1e-15)))
        options.append(f)
    if not options: return None
    positive = max(o['value'] for o in options) > 1e-10
    best = max(options, key=lambda o: (o['value'] if positive else 0., o['entropy'], -o['pair'][0], -o['pair'][1]))
    return {**best, 'method': 'finite-hypothesis-regret-v1',
            'selection': 'expected_regret_reduction' if positive else 'entropy_fallback_no_positive_value',
            'pool_size': len(pool), 'evaluated_pairs': len(options), 'decision_options': s.shape[1],
            'hypotheses': len(s), 'temperature': 1.,
            'top_queries': [{'pair': o['pair'], 'value': o['value']} for o in sorted(options, key=lambda o: -o['value'])[:5]]}


def model_risk(model, combos):
    if not combos: return None
    scores = model.score_heads(combos)@model.head_weights()
    r = risk(scores)
    r['mean_combo'] = combos[r.pop('mean_action')];r['minimax_combo'] = combos[r.pop('minimax_action')]
    return {**r, 'method': 'finite-hypothesis-regret-v1', 'decision_options': len(combos),
            'note': '以现有网络成员等权构成有限假设集；不是校准后验、置信区间或真实错误概率。单成员或成员一致不证明推荐正确。'}

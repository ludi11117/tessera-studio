"""Controlled acquisition comparison using the deployed training implementation.

The selector sees predictions and past pairs only. Synthetic truth is confined
to the experiment's response oracle and external evaluator.
"""
import itertools
import numpy as np
from research.decision_value import select, forecast

POLICIES=('random','entropy','decision_value')
BUDGETS=(0,2,4,6)


def choose_query(scores, seen, policy, rng):
    scores=np.asarray(scores,dtype=float)
    if scores.ndim!=2 or not np.isfinite(scores).all() or not 2<=scores.shape[1]<=24:
        raise ValueError('Use the same finite candidate bank of 2–24 options')
    available=[(i,j) for i,j in itertools.combinations(range(scores.shape[1]),2) if (i,j) not in seen]
    if not available:raise ValueError('No unseen comparison')
    if policy=='decision_value':
        result=select(scores,allowed=lambda i,j:tuple(sorted((i,j))) not in seen)
        return tuple(result['pair']),result
    if policy=='random':pair=available[int(rng.integers(len(available)))]
    elif policy=='entropy':
        def distance(pair):
            i,j=pair;p=np.mean(1/(1+np.exp(-np.clip(scores[:,i]-scores[:,j],-40,40))))
            return abs(float(p)-.5)
        pair=min(available,key=distance)
    else:raise ValueError('Unknown acquisition policy')
    return pair,{**forecast(scores,pair),'selection':policy,'pool_size':scores.shape[1]}


def evaluate(scores, truth):
    scores=np.asarray(scores,dtype=float);truth=np.asarray(truth,dtype=float)
    if scores.shape!=truth.shape or scores.ndim!=1 or not np.isfinite(scores).all() or not np.isfinite(truth).all():
        raise ValueError('Expected aligned finite predictions and truth')
    chosen=int(np.argmax(scores));regret=float(truth.max()-truth[chosen]);span=float(np.ptp(truth))
    pairs=[(i,j) for i,j in itertools.combinations(range(len(truth)),2) if abs(truth[i]-truth[j])>1e-10]
    agreement=[.5 if abs(scores[i]-scores[j])<1e-10 else float((scores[i]>scores[j])==(truth[i]>truth[j])) for i,j in pairs]
    return {'recommendation':chosen,'true_regret':regret,'normalized_regret':regret/span if span else 0.,
            'optimal_hit':bool(regret<1e-10),'pair_agreement':float(np.mean(agreement)) if agreement else None}


def clustered_interval(values, seeds, draws=4000):
    """Percentile bootstrap resampling seeds, keeping all fixed profiles together.

    This quantifies simulation-seed variation conditional on designed profiles;
    it is not a confidence interval over users or a population of tasks.
    """
    values=np.asarray(values,dtype=float);seeds=np.asarray(seeds)
    if len(values)!=len(seeds) or not len(values):raise ValueError('Aligned nonempty observations required')
    groups=sorted(set(seeds.tolist()));averages=np.array([values[seeds==s].mean() for s in groups])
    samples=np.random.default_rng(8103).choice(averages,size=(draws,len(groups)),replace=True).mean(1)
    return {'mean':float(averages.mean()),'seed_cluster_bootstrap_95_percentile':[float(v) for v in np.quantile(samples,[.025,.975])],
            'seed_clusters':len(groups),'observations':len(values),'bootstrap_draws':draws}


def summarize(records):
    rows=[r for r in records if r['additional_comparisons'] in BUDGETS];summaries=[];deltas=[]
    for budget in BUDGETS:
        for policy in POLICIES:
            selected=[r for r in rows if r['additional_comparisons']==budget and r['policy']==policy]
            for model in ('semantic_deep','semantic_linear'):
                for domain in ('same_wording','new_wording'):
                    summaries.append({'policy':policy,'model':model,'domain':domain,'additional_comparisons':budget,
                        'total_feedback':4+budget,**clustered_interval([r['metrics'][model][domain]['normalized_regret'] for r in selected],[r['seed'] for r in selected]),
                        'optimal_hit_rate':float(np.mean([r['metrics'][model][domain]['optimal_hit'] for r in selected])),
                        'pair_agreement':float(np.mean([r['metrics'][model][domain]['pair_agreement'] for r in selected]))})
        lookup={(r['profile'],r['seed'],r['policy']):r for r in rows if r['additional_comparisons']==budget}
        keys=sorted({(p,s) for p,s,_ in lookup})
        for domain in ('same_wording','new_wording'):
            for baseline in ('random','entropy'):
                differences=[lookup[p,s,'decision_value']['metrics']['semantic_deep'][domain]['normalized_regret']-lookup[p,s,baseline]['metrics']['semantic_deep'][domain]['normalized_regret'] for p,s in keys]
                deltas.append({'contrast':'decision_value minus '+baseline,'domain':domain,'additional_comparisons':budget,
                    **clustered_interval(differences,[s for _,s in keys])})
    return summaries,deltas

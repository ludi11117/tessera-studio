"""Designed response oracle and independent evaluation, never selector inputs."""
import hashlib
import itertools
import random
from webcraft.model import IDS,LAYOUTS,PALETTES,digest

TRACKS=('additive_clean','interaction_clean','interaction_noisy')
POLICIES=('random','entropy','fisher')
SEEDS=tuple(range(12))

def bank(doc,locks):
    domains=[]
    for cid in IDS:
        domains.append([{'layout':l,'palette':p} for l in LAYOUTS for p in PALETTES if (cid+'.layout' not in locks or l==doc['components'][cid]['layout']) and (cid+'.palette' not in locks or p==doc['components'][cid]['palette'])])
    return [dict(zip(IDS,values)) for values in itertools.product(*domains)]

def truth(choice,coefficients,interactions):
    value=sum(coefficients[cid][field][choice[cid][field]] for cid in IDS for field in ('layout','palette'))
    for term in interactions:
        if all(choice[cid][field]==v for cid,field,v in term['when']):value+=term['bonus']
    return value

def oracle(seed,track,a,b,ua,ub):
    # Same unordered pair always receives the same noise, regardless of policy/order.
    aid,bid=digest(a),digest(b);lo,hi=sorted((aid,bid));raw=hashlib.sha256(f'{seed}/{track}/{lo}/{hi}'.encode()).digest()
    draw=int.from_bytes(raw[:8],'big')/2**64
    low_wins=(ua>ub if aid==lo else ub>ua) if ua!=ub else draw<.5
    if track=='interaction_noisy' and draw<.2:low_wins=not low_wins
    return low_wins if aid==lo else not low_wins

def score(rec,utilities,holdouts,weights):
    from webcraft.preference import vector,dot
    values=list(utilities.values());u=utilities[digest(rec)];span=max(values)-min(values)
    agreement=[]
    for a,b in holdouts:
        delta=utilities[digest(a)]-utilities[digest(b)]
        if abs(delta)<1e-10:continue
        predicted=dot(weights,vector(a))-dot(weights,vector(b))
        agreement.append(.5 if abs(predicted)<1e-10 else float((predicted>0)==(delta>0)))
    return {'normalized_regret':(max(values)-u)/span if span else 0.,'optimal_hit':abs(max(values)-u)<1e-10,'heldout_pair_agreement':sum(agreement)/len(agreement) if agreement else None,'heldout_pairs':len(agreement)}

def paired_interval(values,draws=4000):
    rng=random.Random(7103);n=len(values)
    samples=sorted(sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(draws))
    return {'mean':sum(values)/n,'bootstrap_95_percentile':[samples[int(.025*draws)],samples[int(.975*draws)]],'seed_pairs':n}

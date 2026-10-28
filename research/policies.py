"""Shared legal query pools, auditable random/uncertainty/one-step policies."""
import itertools
import math
import random
import time
import numpy as np

from core import enumerate_feasible, pair_key, render, render_variant, variant_for
from research.model import digest, sigmoid


def all_queries(task, state, seen=(), combos=None):
    combos = enumerate_feasible(task, state) if combos is None else combos
    found = {}
    by_combo = {tuple(sorted(c.items())): c for c in combos}
    for a in combos:
        for b in task["blocks"]:
            bid = b["id"]
            if bid in state["locks"]:
                continue
            for v in b["variants"]:
                z = {**a, bid: v["id"]}
                if a[bid] >= z[bid] or tuple(sorted(z.items())) not in by_combo:
                    continue
                key = pair_key(bid, a, z)
                if key in seen:
                    continue
                context = {k: value for k, value in a.items() if k != bid}
                changed = [k for k in context if context[k] != state["combo"][k]]
                found[key] = {"block": bid, "title": b["title"], "a": a, "b": z, "key": key,
                              "context": context, "context_changes": changed, "alternative_context": bool(changed)}
    return [found[k] for k in sorted(found)]


def query_pool(task, state, seen=(), seed=0, limit=12, context_mode="mixed", allowed_keys=None):
    queries = all_queries(task, state, seen)
    if allowed_keys is not None:
        queries = [q for q in queries if q["key"] in allowed_keys]
    current = [q for q in queries if not q["alternative_context"]]
    alternate = [q for q in queries if q["alternative_context"]]
    rng = random.Random(seed)
    if context_mode != "current":
        rng.shuffle(current)
    rng.shuffle(alternate)
    if context_mode == "current":
        pool = current[:limit]
    else:
        n = min(len(current), max(1, limit // 2))
        pool = current[:n] + alternate[:limit - n]
        if len(pool) < limit:
            pool += current[n:n + limit - len(pool)]
    return pool, {"full_pool_count": len(queries), "current_pool_count": len(current), "selected_pool_count": len(pool),
                  "pool_hash": digest([q["key"] for q in pool]), "pool_seed": seed, "pool_limit": limit, "context_mode": context_mode}


def cost_proxy(task, query):
    bid = query["block"]
    text_a = render_variant(task, variant_for(task, bid, query["a"][bid]))
    text_b = render_variant(task, variant_for(task, bid, query["b"][bid]))
    extra = sum(len(render_variant(task, variant_for(task, k, query["a"][k]))) for k in query["context_changes"])
    return 1.0 + (len(text_a) + len(text_b) + extra) / 80.0 + 1.5 * len(query["context_changes"])


def select_query(model, task, state, pool, policy="uncertainty", seed=0, planning_ms=1500, min_value=None):
    start = time.perf_counter()
    if policy not in ("random", "uncertainty", "kg", "cost_kg"):
        raise ValueError("Unknown query policy")
    if not pool:
        return None, {"stop_reason": "no_legal_queries", "planning_ms": 0.0}
    d = np.stack([model.encoder.encode(q["a"]) - model.encoder.encode(q["b"]) for q in pool])
    p = sigmoid(d @ model.weights)
    costs = np.array([cost_proxy(task, q) for q in pool])
    values = np.zeros(len(pool))
    fallback = None
    if policy in ("kg", "cost_kg"):
        candidates = enumerate_feasible(task, state)
        x = model.encoder.matrix(candidates)
        means = x @ model.weights
        current_value = float(means.max())
        # Solve H v=d (no explicit inverse). Two rank-one Newton fantasies.
        directions = np.linalg.solve(model.hessian, d.T)
        for i in range(len(pool)):
            if (time.perf_counter() - start) * 1000 > planning_ms:
                fallback = "uncertainty_after_planning_timeout"
                break
            variance = float(d[i] @ directions[:, i])
            influence = x @ directions[:, i] / (1 + float(p[i] * (1 - p[i])) * variance)
            va = float(np.max(means + (1 - p[i]) * influence))
            vb = float(np.max(means - p[i] * influence))
            values[i] = p[i] * va + (1 - p[i]) * vb - current_value
    if policy == "random":
        index = random.Random(seed).randrange(len(pool))
        selection_probability = 1.0 / len(pool)
        selected_scores = np.zeros(len(pool))
    elif policy == "uncertainty" or fallback:
        selected_scores = -np.abs(p - 0.5)
        index = int(np.argmax(selected_scores))
        selection_probability = 1.0
    else:
        selected_scores = values / costs if policy == "cost_kg" else values
        index = int(np.argmax(selected_scores))
        selection_probability = 1.0
        if min_value is not None and selected_scores[index] < min_value:
            return None, {"stop_reason": "value_below_threshold", "maximum_value": float(selected_scores[index]), "planning_ms": (time.perf_counter() - start) * 1000}
    query = dict(pool[index])
    direction = np.linalg.solve(model.hessian, d[index])
    metadata = {"policy_id": policy, "policy_version": "rankone-logistic-kg-v1", "seed": seed,
                "selection_probability_conditional_on_pool": selection_probability, "planning_ms": (time.perf_counter() - start) * 1000,
                "planning_limit_ms": planning_ms, "fallback": fallback, "selected_score": float(selected_scores[index]),
                "probability_a": float(p[index]), "difference_variance": float(d[index] @ direction),
                "raw_kg": float(values[index]) if policy in ("kg", "cost_kg") and not fallback else None,
                "estimated_cost": float(costs[index]), "cost_units": "uncalibrated proxy, not seconds",
                "negative_kg_count": int(np.sum(values < -1e-10)), "minimum_raw_kg": float(values.min()),
                "fantasy_method": "one rank-one Newton step at MAP; sigmoid MAP response probability; fixed feasible set",
                "stop_reason": None, "model": model.metadata()}
    query["probability_a"] = float(p[index])
    return query, metadata


def randomize_sides(query, seed):
    query = dict(query)
    swapped = bool(random.Random(seed).getrandbits(1))
    if swapped:
        query["a"], query["b"] = query["b"], query["a"]
        query["probability_a"] = 1 - query["probability_a"]
    return query, {"side_seed": seed, "sides_swapped": swapped}

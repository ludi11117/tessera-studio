"""Optional adapter used by the existing local workbench, not a separate product."""
import time
from core import enumerate_feasible, render
from research.model import create_model
from research.policies import query_pool, randomize_sides, select_query


def fitted(task, state, pairs):
    config = state["research"]
    return create_model(task, config["model"], config.get("l2_sum", 0.5)).fit(pairs)


def view_model(task, state, pairs, limit=5, trained=None):
    model = trained if trained is not None else fitted(task, state, pairs)
    combos = enumerate_feasible(task, state)
    scores = model.scores(combos)
    ranked = sorted(zip(combos, scores), key=lambda cs: (-round(float(cs[1]), 10), sum(cs[0][k] != state["combo"][k] for k in cs[0]), tuple(cs[0].values())))
    current_terms = model.explain(state["combo"])
    current_sums = {key: sum(t["contribution"] for t in current_terms if t["type"] == key) for key in ("unary", "interaction")}
    ranks = []
    for c, value in (ranked if limit is None else ranked[:limit]):
        terms = model.explain(c)
        sums = {key: sum(t["contribution"] for t in terms if t["type"] == key) for key in current_sums}
        ranks.append({"combo": c, "score": round(float(value), 5), "text": render(task, c),
                      "changes": [b["title"] for b in task["blocks"] if c[b["id"]] != state["combo"][b["id"]]],
                      "score_terms": sums, "score_delta": {k: sums[k] - current_sums[k] for k in sums}})
    weight_map = dict(zip(model.encoder.keys, model.weights))
    weights = [{"block": b["title"], "variant": i + 1, "weight": round(model.unary_contribution(b["id"], v["id"]) if hasattr(model, "unary_contribution") else float(weight_map[("unary", b["id"], v["id"])]), 4)} for b in task["blocks"] for i, v in enumerate(b["variants"])]
    return ranks, len(combos), weights, {**model.metadata(), "coverage": model.coverage()}


def make_offer(task, state, pairs, seen, revision):
    started = time.perf_counter()
    config = state["research"]
    if len(pairs) >= config["budget"]:
        return None, {"stop_reason": "feedback_budget_exhausted"}
    model = fitted(task, state, pairs)
    seed = config["seed"] + revision * 100003
    pool, pool_meta = query_pool(task, state, seen, seed, config.get("pool_limit", 12), config["context_mode"])
    query, planning = select_query(model, task, state, pool, config["policy"], seed, planning_ms=config.get("planning_ms", 1000))
    if query is None:
        return None, planning
    query, side_meta = randomize_sides(query, seed + 17)
    query["planning"] = {**planning, **pool_meta, **side_meta}
    query["planning"]["acquisition_ms"] = planning["planning_ms"]
    query["planning"]["planning_ms"] = (time.perf_counter() - started) * 1000
    query["response_mode"] = "evaluate_only" if query["alternative_context"] or config["evaluate_only"] else "adopt_winner"
    return query, planning

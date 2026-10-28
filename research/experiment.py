"""Isolated, seeded finite-domain benchmark. Does not import or open Store/SQLite."""
import argparse
import copy
import hashlib
import json
import math
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from core import enumerate_feasible, feasible, initial_state, render, validate_task
from research.model import PreferenceModel, digest, sigmoid
from research.policies import all_queries, cost_proxy, query_pool, select_query

ROOT = Path(__file__).resolve().parents[1]


def task_fixture(seed, n=3):
    blocks = []
    for i in range(n):
        variants = [{"id": f"part{i}-{j}", "template": f"模拟部件{i+1}版本{j+1}。" + "这是额外阅读内容。" * ((seed + i * 5 + j * 3) % 9)} for j in range(3)]
        blocks.append({"id": f"part{i}", "title": f"部件{i+1}", "variants": variants})
    return {"title": "模拟任务", "brief": "Synthetic candidate identifiers; no semantic oracle", "facts": {}, "blocks": blocks, "source": "simulation"}


class Oracle:
    def __init__(self, task, seed, strength, noise):
        self.task, self.seed, self.noise = task, seed, noise
        rng = np.random.default_rng(seed)
        self.unary = rng.normal(0, 0.45, (len(task["blocks"]), 3))
        self.edges = [(0, 1), (1, 2), (0, 2)]
        self.interactions = []
        for _ in self.edges:
            table = rng.normal(size=(3, 3))
            # Remove row/column main effects to separate true interaction strength.
            table = table - table.mean(axis=0)[None, :] - table.mean(axis=1)[:, None] + table.mean()
            self.interactions.append(table * strength)

    def utility(self, combo):
        indices = [next(j for j, v in enumerate(b["variants"]) if v["id"] == combo[b["id"]]) for b in self.task["blocks"]]
        return float(sum(self.unary[i, j] for i, j in enumerate(indices)) + sum(table[indices[i], indices[j]] for (i, j), table in zip(self.edges, self.interactions)))

    def p(self, query):
        # Deterministic latent preference, then symmetric independent response flips.
        delta = self.utility(query["a"]) - self.utility(query["b"])
        base = 1.0 if delta > 1e-10 else 0.0 if delta < -1e-10 else 0.5
        return self.noise + (1 - 2 * self.noise) * base

    def respond(self, query):
        # Same query and seed -> same exogenous response across arms.
        u = int(digest([self.seed, query["key"], "response"])[:13], 16) / 16**13
        return "a" if u < self.p(query) else "b"

    def actual_cost(self, task, query, misspecified=False):
        estimated = cost_proxy(task, query)
        return 1 + 16 / estimated if misspecified else estimated


def recommendation(model, combos, current):
    scores = model.scores(combos)
    best = max(range(len(combos)), key=lambda i: (round(float(scores[i]), 10), -sum(v != current[k] for k, v in combos[i].items()), -i))
    return combos[best]


def run_one(config, scenario, arm, seed):
    task = task_fixture(seed)
    validate_task(task)
    state = initial_state(task)
    if scenario.get("lock_first"):
        state["locks"]["part0"] = state["combo"]["part0"]
    state["max_chars"] = scenario.get("max_chars")
    combos = enumerate_feasible(task, state)
    oracle = Oracle(task, seed, scenario["interaction"], scenario["noise"])
    queries = all_queries(task, state, combos=combos)
    # The same deterministic held-out query set is excluded for every arm.
    heldout = [q for q in queries if int(digest([seed, q["key"], "holdout"])[:8], 16) % config["heldout_modulus"] == 0]
    allowed = {q["key"] for q in queries if q not in heldout}
    truth = max((oracle.utility(c) for c in combos), default=None)
    pairs, seen, logs, rows = [], set(), [], []
    user_cost = planning_seconds = fitting_seconds = 0.0
    stop_reason = "infeasible" if not combos else None
    model = PreferenceModel(task, arm["model"], config["l2_sum"])
    start = time.perf_counter()
    model.fit(pairs)
    fitting_seconds += time.perf_counter() - start
    for step in range(max(config["budgets"]) + 1):
        if step in config["budgets"]:
            chosen = recommendation(model, combos, state["combo"]) if combos else None
            predicted = [min(1-1e-12, max(1e-12, model.probability(q["a"], q["b"]))) for q in heldout]
            actual = [oracle.p(q) for q in heldout]
            nll = float(np.mean([-p*math.log(q)-(1-p)*math.log(1-q) for p,q in zip(actual,predicted)])) if actual else None
            brier = float(np.mean([p*(1-q)**2+(1-p)*q*q for p,q in zip(actual,predicted)])) if actual else None
            rows.append({"scenario": scenario["id"], "arm": arm["id"], "seed": seed, "budget": step,
                         "actual_feedback": len(pairs), "regret": max(0.0, truth-oracle.utility(chosen)) if chosen else None,
                         "user_cost_proxy_observed": user_cost, "planning_seconds": planning_seconds, "fitting_seconds": fitting_seconds,
                         "heldout_nll": nll, "heldout_brier": brier, "heldout_count": len(heldout),
                         "constraint_violations": int(chosen is not None and not feasible(task, chosen, state)),
                         "stop_reason": stop_reason, "recommendation": chosen, "gradient_max_abs": model.gradient_norm})
        if step == max(config["budgets"]) or stop_reason:
            if stop_reason and step < max(config["budgets"]):
                continue
            break
        pool_seed = seed * 100003 + step
        started = time.perf_counter()
        pool, summary = query_pool(task, state, seen, pool_seed, config["pool_limit"], arm["context_mode"], allowed)
        q, meta = select_query(model, task, state, pool, arm["policy"], pool_seed, config["planning_limit_ms"])
        planning_seconds += time.perf_counter() - started
        if q is None:
            stop_reason = meta["stop_reason"]
            continue
        if not feasible(task, q["a"], state) or not feasible(task, q["b"], state):
            raise AssertionError("Query constraint violation")
        choice = oracle.respond(q)
        pair = {"winner": q[choice], "loser": q["b" if choice == "a" else "a"]}
        pairs.append(pair)
        seen.add(q["key"])
        actual_cost = oracle.actual_cost(task, q, scenario.get("cost_misspecified", False))
        user_cost += actual_cost
        # Current-context response may be adopted as in V1; diagnostic backgrounds are evaluate-only.
        if not q["alternative_context"]:
            state["combo"] = dict(pair["winner"])
        logs.append({"schema_version": 2, "data_origin": "simulation", "scenario": scenario["id"], "arm": arm["id"],
                     "seed": seed, "step": step, "query": q, "response": choice, "actual_cost_proxy": actual_cost,
                     "planning": meta, "pool": summary})
        started = time.perf_counter()
        model.fit(pairs)
        fitting_seconds += time.perf_counter() - started
    return rows, logs


def counterexample():
    task = task_fixture(0, n=2)
    combos = enumerate_feasible(task, initial_state(task))
    def utility(c):
        a, b = int(c["part0"][-1]), int(c["part1"][-1])
        return 1.0 if a == b and a < 2 else 0.5 if a == b == 2 else 0.3 if 2 in (a,b) else 0.0
    pool = all_queries(task, initial_state(task), combos=combos)
    pairs = [{"winner": q["a"] if utility(q["a"])>utility(q["b"]) else q["b"], "loser": q["b"] if utility(q["a"])>utility(q["b"]) else q["a"]} for q in pool if abs(utility(q["a"])-utility(q["b"]))>1e-9]
    rows = []
    probes = [(q, utility(q["a"]) > utility(q["b"])) for q in pool if q["block"] == "part0" and {q["a"]["part0"],q["b"]["part0"]}=={"part0-0","part0-1"} and q["a"]["part1"] != "part1-2"]
    for coverage in ("single_context", "all_contexts"):
        training = [p for p in pairs if p["winner"]["part1"]==p["loser"]["part1"]=="part1-0"] if coverage == "single_context" else pairs
        for kind in ("legacy", "additive", "interaction"):
            model = PreferenceModel(task, kind).fit(training)
            probs = [model.probability(q["a"],q["b"]) for q,_ in probes]
            rows.append({"coverage": coverage,"model":kind,"pair_count":len(training),"probe_probability_a":probs,
                         "reversal_correct":sum((p>.5)==y and abs(p-.5)>1e-8 for p,(_,y) in zip(probs,probes)),
                         "probe_count":len(probes),"coverage_rank":model.coverage(),"model_metadata":model.metadata()})
    return {"data_origin":"simulation","algebraic_interaction_contrast":2,"note":"Representation and coverage check, not human evidence", "rows":rows}


def semantic_payload(rows, logs):
    clean_rows = [{k:v for k,v in r.items() if k not in ("planning_seconds","fitting_seconds")} for r in rows]
    clean_logs = copy.deepcopy(logs)
    for r in clean_logs:
        r["planning"].pop("planning_ms", None)
    return {"rows": clean_rows, "logs": clean_logs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "research/configs/benchmark-v1.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", choices=("development","evaluation"), default="evaluation")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if set(config["development_seeds"]) & set(config["evaluation_seeds"]):
        raise ValueError("Development/evaluation seeds must be disjoint")
    out = args.output or ROOT / "experiments/runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if out.exists():
        raise ValueError("Use a new output directory; results are immutable")
    out.mkdir(parents=True)
    (out / "config.json").write_text(json.dumps(config,indent=2),encoding="utf-8")
    source_files = [ROOT/"core.py", *sorted((ROOT/"research").glob("*.py"))]
    hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    for file in source_files:
        target=out/"source_snapshot"/file.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
    rows,logs=[],[]
    with (out/"queries.jsonl").open("w",encoding="utf-8") as query_file:
        for scenario in config["scenarios"]:
            for arm in config["arms"]:
                for seed in config[args.split+"_seeds"]:
                    r,l=run_one(config,scenario,arm,seed);rows+=r;logs+=l
                    query_file.writelines(json.dumps(v,ensure_ascii=False)+"\n" for v in l)
                print(f"{scenario['id']}: {arm['id']} complete",flush=True)
    (out/"metrics.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"counterexample.json").write_text(json.dumps(counterexample(),ensure_ascii=False,indent=2),encoding="utf-8")
    manifest={"schema_version":1,"data_origin":"simulation","split":args.split,"independent_seeds":config[args.split+"_seeds"],
              "python":sys.version,"platform":platform.platform(),"numpy":np.__version__,"source_hashes":hashes,
              "config_hash":digest(config),"semantic_hash":digest(semantic_payload(rows,logs)),"queries":len(logs),
              "fallback_count":sum(bool(l["planning"]["fallback"]) for l in logs),"real_participants":0}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({"output":str(out),"semantic_hash":manifest["semantic_hash"]}),flush=True)


if __name__ == "__main__":
    main()

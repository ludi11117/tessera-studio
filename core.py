"""Deterministic constraints, explicit pair labels, and a linear BT baseline."""
import copy
import itertools
import math
import re


class Invalid(ValueError):
    pass


MODEL_CONFIG = {"version": "linear-bt-onehot-v1", "features": "task-local immutable block/variant one-hot, including archived revisions", "l2": 0.08, "steps": 240, "learning_rate": 0.3, "initialization": "zero", "reduction": "mean"}


def validate_task(task):
    if not isinstance(task, dict):
        raise Invalid("任务格式不正确")
    if not isinstance(task.get("title"), str) or not 1 <= len(task["title"].strip()) <= 100:
        raise Invalid("任务名称应为1–100字")
    facts, blocks = task.get("facts"), task.get("blocks")
    if not isinstance(facts, dict) or len(facts) > 30 or any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", k) or not isinstance(v, str) or not v.strip() or len(v) > 500 or "{{" in v or "}}" in v for k, v in facts.items()):
        raise Invalid("事实应为不超过30个英文键与非空文本值；事实值不可嵌套引用")
    minimum = 1 if task.get('source') == 'generated' and task.get('category') == 'writing' else 2
    if not isinstance(blocks, list) or not minimum <= len(blocks) <= 6:
        raise Invalid(f"任务需有{minimum}–6个部件")
    ids = set()
    for b in blocks:
        if not isinstance(b, dict) or not isinstance(b.get("id"), str) or b["id"] in ids or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", b["id"]):
            raise Invalid("部件ID必须唯一且为英文、数字或连字符")
        ids.add(b["id"])
        if not isinstance(b.get("title"), str) or not 1 <= len(b["title"]) <= 100:
            raise Invalid("部件名称应为1–100字")
        if not isinstance(b.get("variants"), list) or len(b["variants"]) != 3:
            raise Invalid("每个部件需恰好三个版本")
        if b.get("fixed") and len({v.get("template") for v in b["variants"] if isinstance(v,dict)}) != 1:
            raise Invalid("固定部件的三个版本必须具有相同内容")
        seen = set()
        for v in b["variants"]:
            if not isinstance(v, dict) or not isinstance(v.get("id"), str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", v["id"]) or v["id"] in seen:
                raise Invalid("部件候选ID必须唯一且有效")
            seen.add(v["id"])
            if not isinstance(v.get("template"), str) or not 1 <= len(v["template"].strip()) <= 3000:
                raise Invalid("候选正文应为1–3000字")
            refs = re.findall(r"\{\{(.*?)\}\}", v["template"])
            if any(k not in facts for k in refs):
                raise Invalid("候选引用了不存在的事实")
            stripped = re.sub(r"\{\{.*?\}\}", "", v["template"])
            if "{{" in stripped or "}}" in stripped:
                raise Invalid("事实引用括号不完整")
        # Every alternative within a block must refer to the same fixed facts.
        refsets = [set(re.findall(r"\{\{(.*?)\}\}", v["template"])) for v in b["variants"]]
        if any(s != refsets[0] for s in refsets):
            raise Invalid("同一部件的三个版本必须引用相同的固定事实")
    used = set(re.findall(r"\{\{(.*?)\}\}", " ".join(v["template"] for b in blocks for v in b["variants"])))
    if used != set(facts):
        raise Invalid("每个固定事实都必须被候选引用")


def render_variant(task, variant):
    return re.sub(r"\{\{(.*?)\}\}", lambda m: task["facts"][m[1]], variant["template"])


def variant_for(task, bid, vid):
    for b in task["blocks"]:
        if b["id"] == bid:
            for v in b["variants"] + b.get("archive", []):
                if v["id"] == vid:
                    return v
    raise Invalid("未知的段落或版本")


def render(task, combo):
    if set(combo) != {b["id"] for b in task["blocks"]}:
        raise Invalid("组合缺失部件")
    return "\n\n".join(render_variant(task, variant_for(task, b["id"], combo[b["id"]])) for b in task["blocks"])


def initial_state(task):
    return {"combo": {b["id"]: b["variants"][0]["id"] for b in task["blocks"]}, "locks": {b["id"]: b["variants"][0]["id"] for b in task["blocks"] if b.get("fixed")}, "max_chars": None, "final": None}


def feasible(task, combo, state):
    if any(combo.get(b["id"]) not in {v["id"] for v in b["variants"]} for b in task["blocks"]):
        return False
    content = render(task, combo)
    from ai.acceptance import satisfied
    from ai.preservation import checks as preservation_checks
    return all(combo.get(k) == v for k, v in state["locks"].items()) and (state["max_chars"] is None or len(content) <= state["max_chars"]) and satisfied(task, combo, state) and all(c['passed'] for c in preservation_checks(task, combo, state))


def enumerate_feasible(task, state):
    keys = [b["id"] for b in task["blocks"]]
    return [c for values in itertools.product(*[[v["id"] for v in b["variants"]] for b in task["blocks"]])
            if feasible(task, c := dict(zip(keys, values)), state)]


def feature_keys(task):
    return [(b["id"], v["id"]) for b in task["blocks"] for v in sorted(b["variants"] + b.get("archive", []), key=lambda v: v["id"])]


def features(task, combo):
    # Task-local one-hot coefficients; no invented negative labels or cross-user reuse.
    return [float(combo[bid] == vid) for bid, vid in feature_keys(task)]


def sigmoid(z):
    return 1 / (1 + math.exp(-max(-40, min(40, z))))


def score(weights, x):
    return sum(w * a for w, a in zip(weights, x))


def fit(task, pairs):
    dim = len(feature_keys(task))
    weights = [0.0] * dim
    diffs = [[a - b for a, b in zip(features(task, p["winner"]), features(task, p["loser"]))] for p in pairs]
    if diffs:
        for _ in range(MODEL_CONFIG["steps"]):
            grad = [MODEL_CONFIG["l2"] * w for w in weights]
            for d in diffs:
                error = sigmoid(score(weights, d)) - 1
                for j in range(dim):
                    grad[j] += error * d[j] / len(diffs)
            weights = [w - MODEL_CONFIG["learning_rate"] * g for w, g in zip(weights, grad)]
    return weights


def recommendations(task, state, weights):
    combos = enumerate_feasible(task, state)
    current = state["combo"]
    combos.sort(key=lambda c: (-round(score(weights, features(task, c)), 10), sum(c[k] != current[k] for k in c), tuple(c.values())))
    return [{"combo": c, "score": round(score(weights, features(task, c)), 5), "text": render(task, c),
             "changes": [b["title"] for b in task["blocks"] if c[b["id"]] != current[b["id"]]]} for c in combos], len(combos)


def comparison(task, state, weights, seen):
    choices = []
    for b in task["blocks"]:
        bid = b["id"]
        if bid in state["locks"]:
            continue
        if len({v["template"] for v in b["variants"]}) < 2:
            continue
        for va, vb in itertools.combinations(b["variants"], 2):
            a, z = copy.deepcopy(state["combo"]), copy.deepcopy(state["combo"])
            a[bid], z[bid] = va["id"], vb["id"]
            if not feasible(task, a, state) or not feasible(task, z, state):
                continue
            key = pair_key(bid, a, z)
            if key in seen:
                continue
            p = sigmoid(score(weights, features(task, a)) - score(weights, features(task, z)))
            choices.append((abs(p - 0.5), {"block": bid, "title": b["title"], "a": a, "b": z, "probability_a": round(p, 5), "key": key}))
    return min(choices, key=lambda x: x[0])[1] if choices else None


def pair_key(bid, a, b):
    return repr((bid, sorted((tuple(sorted(a.items())), tuple(sorted(b.items()))))))

"""Build only exposed, explicit, unretracted pair labels. Standard library only."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from core import Invalid, initial_state, render, variant_for


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_dataset(audit, origin_override=None):
    if audit.get("schema_version") not in (1, 2):
        raise Invalid("Unsupported audit schema")
    task, events = copy.deepcopy(audit["task"]), audit["events"]
    retracted = {e["payload"]["target"] for e in events if e["kind"] == "undo"}
    retracted.update(e['payload']['target'] for e in events if e['kind']=='feedback_retract' and e['id'] not in retracted)
    exposed = {}
    labels, excluded = [], []
    current_state = initial_state(task)
    # Reconstruct active membership in the historical library, including legacy edits/undos.
    all_versions = {b["id"]: {v["id"]: v for v in b["variants"] + b.get("archive", [])} for b in task["blocks"]}
    first_edit = next((e for e in events if e["kind"] == "edit"), None)
    active = {b["id"]: {v["id"] for v in b["variants"]} for b in (first_edit["payload"]["previous_blocks"] if first_edit else task["blocks"])}
    by_id = {e["id"]: e for e in events}
    for event in sorted(events, key=lambda e: e["seq"]):
        kind, payload = event["kind"], event["payload"]
        if kind == "comparison_exposure":
            qid = payload["offer"]
            if qid in exposed:
                raise Invalid("Duplicate exposure identifier")
            a, b = payload["a"], payload["b"]
            changed = [k for k in a if a[k] != b.get(k)]
            whole=payload.get('comparison_kind')=='whole_plan'
            legal_change=(bool(changed) and payload['block']=='__whole__') if whole else (len(changed)==1 and changed[0]==payload['block'])
            if not legal_change or set(a) != set(active) or set(b) != set(active):
                raise Invalid("Exposed pair is not a controlled local comparison")
            for c in (a, b):
                if any(c[k] not in active[k] for k in active):
                    raise Invalid("Exposure references a candidate inactive at its revision")
                if any(c.get(k) != v for k, v in current_state["locks"].items()):
                    raise Invalid("Exposure violates historical locks")
                if current_state["max_chars"] is not None and len(render(task, c)) > current_state["max_chars"]:
                    raise Invalid("Exposure violates historical length constraint")
            exposed[qid] = (event, copy.deepcopy(current_state))
        elif kind == "compare":
            if event["id"] in retracted:
                excluded.append({"event": event["id"], "reason": "retracted"})
            else:
                if payload.get("training_label") is not True or payload.get("offer") not in exposed:
                    raise Invalid("Label lacks a prior, actually exposed comparison")
                exposure, constraint = exposed[payload["offer"]]
                q = exposure["payload"]
                if exposure["revision"] != event["revision"] - 1:
                    raise Invalid("Label references a stale query revision")
                if {sha(payload["winner"]), sha(payload["loser"])} != {sha(q["a"]), sha(q["b"])} or payload["winner"] == payload["loser"]:
                    raise Invalid("Label does not match the exposed alternatives")
                if payload.get("choice") not in ("a", "b") or payload["winner"] != q[payload["choice"]]:
                    raise Invalid("Label choice and winner disagree")
                snapshot = q.get("snapshot", {})
                group = snapshot.get("participant_id")
                origin = origin_override or snapshot.get("data_origin", "unclassified_legacy")
                texts = {side: render(task, q[side]) for side in ("a", "b")}
                if snapshot.get("texts") and texts != snapshot["texts"]:
                    raise Invalid("Immutable text snapshot mismatch")
                labels.append({"schema_version": 2, "label_id": event["id"], "session_id": event["session"],
                               "participant_id": group, "data_origin": origin, "exposure_id": exposure["id"], "query_id": payload["offer"],
                               "exposed_at": exposure["created"], "answered_at": event["created"], "task_revision": exposure["revision"],
                               "block": q["block"], "a": q["a"], "b": q["b"], "choice": payload["choice"],
                               "winner": payload["winner"], "loser": payload["loser"], "texts": texts, "facts": task["facts"],
                               "task_hash": sha({"title": task["title"], "brief": task.get("brief"), "facts": task["facts"]}),
                               "candidate_snapshot_hash": snapshot.get("task_hash") or sha({k: sorted(v) for k, v in active.items()}),
                               "pair_text_hash": sha(texts),
                               "constraint": {"locks": constraint["locks"], "max_chars": constraint["max_chars"], **({'acceptance':constraint['acceptance']} if constraint.get('acceptance') else {})},
                               "query_metadata": q.get("planning"), "comparison_context": {k: v for k, v in q["a"].items() if k != q["block"]}})
                if q.get('comparison_kind')=='whole_plan':
                    labels[-1]['comparison_kind']='whole_plan'
                    labels[-1]['comparison_context']=q.get('context',{})
                if payload.get('reasons'):labels[-1]['reasons']=payload['reasons']
                if payload.get('reason_note'):labels[-1]['reason_note']=payload['reason_note']
        if kind == "edit":
            for change in payload["changes"]:
                active[change["block"]].remove(change["old"])
                if change["new"] not in all_versions[change["block"]]:
                    raise Invalid("Edited candidate content is missing from immutable archive")
                active[change["block"]].add(change["new"])
        elif kind == "undo" and by_id[payload["target"]]["kind"] == "edit":
            old = by_id[payload["target"]]["payload"]["previous_blocks"]
            active = {b["id"]: {v["id"] for v in b["variants"]} for b in old}
        if event.get("after_state") is not None:
            current_state = event["after_state"]
    if len({r["query_id"] for r in labels}) != len(labels):
        raise Invalid("A query generated multiple active labels")
    manifest = {"schema_version": 2, "dataset_version": "exposed-local-pairs-v2", "label_count": len(labels),
                "excluded": excluded, "session_count": len({r["session_id"] for r in labels}),
                "participant_count": len({r["participant_id"] for r in labels if r["participant_id"]}),
                "origins": sorted({r["data_origin"] for r in labels}), "semantic_hash": sha(labels),
                "note": "Session IDs are not participant IDs. Legacy origin remains unclassified. No off-policy counterfactual labels."}
    return labels, manifest


def main():
    parser = argparse.ArgumentParser(description="Build traceable explicit-pair dataset from an audit JSON")
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", choices=["development_test", "simulation"])
    args = parser.parse_args()
    if (args.output / "manifest.json").exists() or (args.output / "pairs.jsonl").exists():
        raise Invalid("Use a new dataset output directory; existing datasets are immutable")
    raw = args.audit.read_bytes()
    rows, manifest = build_dataset(json.loads(raw.decode("utf-8-sig")), args.origin)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "pairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest["source_file_sha256"] = hashlib.sha256(raw).hexdigest()
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"labels": len(rows), "output": str(args.output), "semantic_hash": manifest["semantic_hash"]}))


if __name__ == "__main__":
    main()

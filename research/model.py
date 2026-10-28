"""Finite-candidate additive/interaction logistic MAP, independent of constraints."""
import hashlib
import json
import numpy as np

from core import MODEL_CONFIG, feature_keys, features, fit


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class FeatureEncoder:
    version = "id-unary-adjacent-endpoints-v1"

    def __init__(self, task, interaction=False):
        self.task = task
        self.unary = feature_keys(task)
        n = len(task["blocks"])
        self.edges = sorted(set([(i, i + 1) for i in range(n - 1)] + ([(0, n - 1)] if n > 2 else []))) if interaction else []
        self.keys = [("unary", bid, vid) for bid, vid in self.unary]
        for i, j in self.edges:
            left, right = task["blocks"][i], task["blocks"][j]
            a = sorted(left["variants"] + left.get("archive", []), key=lambda v: v["id"])
            b = sorted(right["variants"] + right.get("archive", []), key=lambda v: v["id"])
            self.keys += [("interaction", left["id"], va["id"], right["id"], vb["id"]) for va in a for vb in b]
        self.index = {key: i for i, key in enumerate(self.keys)}
        self.fingerprint = digest({"version": self.version, "keys": self.keys})

    def encode(self, combo):
        x = np.zeros(len(self.keys))
        for bid, vid in combo.items():
            key = ("unary", bid, vid)
            if key not in self.index:
                raise ValueError("Comparison references an unknown immutable candidate")
            x[self.index[key]] = 1
        for i, j in self.edges:
            a, b = self.task["blocks"][i]["id"], self.task["blocks"][j]["id"]
            x[self.index[("interaction", a, combo[a], b, combo[b])]] = 1
        return x

    def matrix(self, combos):
        return np.stack([self.encode(c) for c in combos]) if combos else np.zeros((0, len(self.keys)))


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))


class PreferenceModel:
    """Sum-loss models share a fixed prior; legacy preserves the V1 mean objective."""
    def __init__(self, task, kind="interaction", l2=0.5):
        if kind not in ("legacy", "additive", "interaction"):
            raise ValueError("Unknown preference model")
        self.task, self.kind, self.l2 = task, kind, l2
        self.encoder = FeatureEncoder(task, interaction=kind == "interaction")
        self.weights = np.zeros(len(self.encoder.keys))
        self.hessian = None
        self.n = 0

    def fit(self, pairs):
        self.n = len(pairs)
        self.weights = np.zeros(len(self.encoder.keys))
        d = np.stack([self.encoder.encode(p["winner"]) - self.encoder.encode(p["loser"]) for p in pairs]) if pairs else np.zeros((0, len(self.weights)))
        if self.kind == "legacy":
            self.weights = np.array(fit(self.task, pairs))
            prior = max(1, len(pairs)) * MODEL_CONFIG["l2"]
            self.iterations = MODEL_CONFIG["steps"] if pairs else 0
        else:
            prior = self.l2
            self.iterations = 0
            for iteration in range(24 if pairs else 0):
                p = sigmoid(d @ self.weights)
                grad = d.T @ (p - 1) + prior * self.weights
                h = (d.T * (p * (1 - p))) @ d + np.eye(len(self.weights)) * prior
                delta = np.linalg.solve(h, grad)
                old_loss = np.logaddexp(0, -(d @ self.weights)).sum() + prior / 2 * float(self.weights @ self.weights)
                step = 1.0
                while step > 1e-5:
                    proposed = self.weights - step * delta
                    loss = np.logaddexp(0, -(d @ proposed)).sum() + prior / 2 * float(proposed @ proposed)
                    if loss <= old_loss + 1e-12:
                        self.weights = proposed
                        break
                    step /= 2
                self.iterations = iteration + 1
                if float(np.max(np.abs(grad))) < 1e-8:
                    break
        p = sigmoid(d @ self.weights)
        self.hessian = (d.T * (p * (1 - p))) @ d + np.eye(len(self.weights)) * prior
        self.differences = d
        self.gradient_norm = float(np.max(np.abs(d.T @ (p - 1) + prior * self.weights))) if pairs else 0.0
        return self

    def scores(self, combos):
        return self.encoder.matrix(combos) @ self.weights

    def probability(self, a, b):
        return float(sigmoid((self.encoder.encode(a) - self.encoder.encode(b)) @ self.weights))

    def metadata(self):
        return {"model_id": self.kind, "feature_version": self.encoder.version, "feature_hash": self.encoder.fingerprint,
                "parameter_count": len(self.weights), "pair_count": self.n, "edges": self.encoder.edges,
                "reduction": "mean" if self.kind == "legacy" else "sum", "l2": MODEL_CONFIG["l2"] if self.kind == "legacy" else self.l2,
                "optimizer": "V1 fixed gradient descent" if self.kind == "legacy" else "Newton with backtracking",
                "iterations": self.iterations, "gradient_max_abs": self.gradient_norm,
                "snapshot_hash": digest({"encoder": self.encoder.fingerprint, "weights": self.weights.tolist()}),
                "uncertainty": "Laplace curvature approximation; uncalibrated"}

    def coverage(self):
        rank = int(np.linalg.matrix_rank(self.differences)) if self.n else 0
        return {"observed_difference_rank": rank, "parameter_count": len(self.weights),
                "note": "Rank is descriptive; regularization fixes non-identifiability, it does not prove preference recovery."}

    def explain(self, combo):
        x = self.encoder.encode(combo)
        return [{"type": k[0], "key": list(k[1:]), "contribution": float(self.weights[i])} for i, k in enumerate(self.encoder.keys) if x[i]]


def create_model(task, kind="interaction", l2=.5):
    """Keep the original estimator unchanged; optional content estimators share its interface."""
    if kind.startswith("content_"):
        from research.content_model import ContentPreferenceModel
        return ContentPreferenceModel(task, kind, l2)
    return PreferenceModel(task, kind, l2)

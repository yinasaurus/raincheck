"""Scores for a stored set of predictions. The bootstrap does not refit."""

from __future__ import annotations

import random


def brier(labels: list[int], probs: list[float]) -> float | None:
    if not labels or len(labels) != len(probs):
        return None
    return sum((p - y) ** 2 for y, p in zip(labels, probs)) / len(labels)


def skill(model: float | None, reference: float | None) -> float | None:
    if model is None or reference is None or reference == 0:
        return None
    return 1.0 - model / reference


def roc_auc(labels: list[int], probs: list[float]) -> float | None:
    """Mann-Whitney AUC. None when the rows are all one class."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    pairs = sorted(zip(probs, labels), key=lambda item: item[0])
    sum_pos = 0.0
    index = 0
    while index < len(pairs):
        end = index
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        for cursor in range(index, end):
            if pairs[cursor][1] == 1:
                sum_pos += average_rank
        index = end
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def hit_rate(labels: list[int], fired: list[bool]) -> float | None:
    losses = [flag for y, flag in zip(labels, fired) if y == 1]
    if not losses:
        return None
    return sum(1 for flag in losses if flag) / len(losses)


def false_alarm_rate(labels: list[int], fired: list[bool]) -> float | None:
    quiet = [flag for y, flag in zip(labels, fired) if y == 0]
    if not quiet:
        return None
    return sum(1 for flag in quiet if flag) / len(quiet)


def basis_risk_count(labels: list[int], fired: list[bool]) -> int:
    """Loss years the rule did not flag."""
    return sum(1 for y, flag in zip(labels, fired) if y == 1 and not flag)


def calibration(labels: list[int], probs: list[float], bins: int = 5) -> list[dict]:
    """Equal-count bins of the predicted probability against the observed loss rate."""
    if not labels:
        return []
    order = sorted(range(len(labels)), key=lambda i: probs[i])
    width = max(1, len(order) // bins)
    rows = []
    start = 0
    while start < len(order):
        chunk = order[start:start + width]
        if not chunk:
            break
        ys = [labels[i] for i in chunk]
        ps = [probs[i] for i in chunk]
        rows.append({
            "n": len(chunk),
            "mean_predicted": sum(ps) / len(ps),
            "observed_rate": sum(ys) / len(ys),
        })
        start += width
        if len(rows) == bins - 1:
            width = len(order) - start
    return rows


def block_interval(districts: list, labels: list[int], probs: list[float], score, draws: int, seed: int) -> dict:
    """Resample whole districts. score(labels, probs) -> float or None."""
    by_district: dict = {}
    for district, label, prob in zip(districts, labels, probs):
        by_district.setdefault(district, []).append((label, prob))
    keys = list(by_district)
    if not keys:
        return {"low": None, "high": None, "draws": 0}
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        chosen = [keys[rng.randrange(len(keys))] for _ in keys]
        ys: list[int] = []
        ps: list[float] = []
        for key in chosen:
            for label, prob in by_district[key]:
                ys.append(label)
                ps.append(prob)
        value = score(ys, ps)
        if value is not None:
            samples.append(value)
    if not samples:
        return {"low": None, "high": None, "draws": 0}
    samples.sort()
    return {"low": _percentile(samples, 2.5), "high": _percentile(samples, 97.5), "draws": len(samples)}


def _percentile(samples: list[float], percent: float) -> float:
    if len(samples) == 1:
        return samples[0]
    pos = (len(samples) - 1) * percent / 100.0
    low = int(pos)
    high = min(low + 1, len(samples) - 1)
    weight = pos - low
    return samples[low] * (1 - weight) + samples[high] * weight

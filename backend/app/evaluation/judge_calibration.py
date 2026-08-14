"""LLM-as-judge calibration and agreement helpers.

Calibration measures how well a judge's binary decisions match a gold (human)
label set. Agreement measures inter-rater reliability between two judges (or
two runs of the same judge) using Cohen's kappa.

Labels are normalized to 0/1 booleans: truthy values map to 1, falsy to 0.
"""
from __future__ import annotations


def _as_binary(labels: list) -> list[int]:
    return [1 if bool(v) else 0 for v in labels]


def _confusion(gold: list[int], predicted: list[int]) -> tuple[int, int, int, int]:
    tp = fp = tn = fn = 0
    for g, p in zip(gold, predicted):
        if g == 1 and p == 1:
            tp += 1
        elif g == 0 and p == 1:
            fp += 1
        elif g == 0 and p == 0:
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def binary_calibration_metrics(gold_labels: list, judge_labels: list) -> dict:
    """Accuracy / precision / recall / F1 of a judge vs a gold label set."""
    if len(gold_labels) != len(judge_labels):
        raise ValueError("gold_labels and judge_labels must have the same length")
    if not gold_labels:
        return {
            "n": 0,
            "accuracy": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "confusion": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
        }
    gold = _as_binary(gold_labels)
    judge = _as_binary(judge_labels)
    tp, fp, tn, fn = _confusion(gold, judge)
    n = len(gold)
    accuracy = (tp + tn) / n
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": n,
        "accuracy": round(accuracy, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def cohen_kappa(judge_a: list, judge_b: list) -> float:
    """Cohen's kappa for two binary raters.

    Returns a value in ``[-1, 1]`` where 1 is perfect agreement, 0 is chance
    agreement, and negative is worse than chance.
    """
    if len(judge_a) != len(judge_b):
        raise ValueError("judge_a and judge_b must have the same length")
    if not judge_a:
        return 1.0
    a = _as_binary(judge_a)
    b = _as_binary(judge_b)
    n = len(a)
    a_pos = sum(a)
    b_pos = sum(b)
    a_neg = n - a_pos
    b_neg = n - b_pos
    observed_agreement = sum(1 for x, y in zip(a, b) if x == y) / n
    expected_agreement = (a_pos * b_pos + a_neg * b_neg) / (n * n)
    if expected_agreement == 1.0:
        return 1.0 if observed_agreement == 1.0 else 0.0
    return (observed_agreement - expected_agreement) / (1.0 - expected_agreement)


def judge_agreement(judge_a: list, judge_b: list) -> dict:
    """Agreement rate + Cohen's kappa for two judges / two judge runs."""
    if len(judge_a) != len(judge_b):
        raise ValueError("judge_a and judge_b must have the same length")
    n = len(judge_a)
    if n == 0:
        return {"n": 0, "agreement_rate": 1.0, "cohen_kappa": 1.0}
    a = _as_binary(judge_a)
    b = _as_binary(judge_b)
    agreement_rate = sum(1 for x, y in zip(a, b) if x == y) / n
    return {
        "n": n,
        "agreement_rate": round(agreement_rate, 6),
        "cohen_kappa": round(cohen_kappa(a, b), 6),
    }

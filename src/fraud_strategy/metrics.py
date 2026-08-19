"""Evaluation metrics fixed by the M2 contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.special import logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from .strategy import policy_metrics


def expected_calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = 15) -> float:
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities)
    edges = np.linspace(0, 1, bins + 1)
    assignments = np.clip(np.digitize(probabilities, edges[1:-1], right=True), 0, bins - 1)
    error = 0.0
    for index in range(bins):
        selected = assignments == index
        if selected.any():
            error += selected.mean() * abs(probabilities[selected].mean() - labels[selected].mean())
    return float(error)


def calibration_slope_intercept(labels: np.ndarray, probabilities: np.ndarray) -> tuple[float, float]:
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    logits = logit(clipped).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=500)
    model.fit(logits, labels)
    return float(model.coef_[0, 0]), float(model.intercept_[0])


def metric_summary(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    labels = np.asarray(labels, dtype=np.int8)
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-9, 1 - 1e-9)
    prevalence = float(labels.mean())
    brier = float(brier_score_loss(labels, probabilities))
    null_brier = float(brier_score_loss(labels, np.full(len(labels), prevalence)))
    slope, intercept = calibration_slope_intercept(labels, probabilities)
    return {
        "prevalence": prevalence,
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "auroc": float(roc_auc_score(labels, probabilities)),
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "brier_score": brier,
        "brier_skill": 1 - brier / null_brier,
        "ece": expected_calibration_error(labels, probabilities),
        "calibration_slope": slope,
        "calibration_intercept": intercept,
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (float("nan"), float("nan"))
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = z * np.sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2)) / denominator
    return (float(center - margin), float(center + margin))


def capacity_summary(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    labels = np.asarray(labels, dtype=np.int8)
    for capacity in (0.01, 0.03, 0.05, 0.10):
        metrics = policy_metrics(labels, probabilities, capacity)
        caught = metrics["fraud_caught"]
        selected = metrics["queue_size"]
        false_positive = metrics["false_positive_count"]
        metrics["catch_rate_ci95"] = wilson_interval(caught, int(labels.sum()))
        metrics["precision_ci95"] = wilson_interval(caught, selected)
        metrics["false_positive_rate_ci95"] = wilson_interval(false_positive, int((labels == 0).sum()))
        result[f"{capacity:.2f}"] = metrics
    return result


def _stratified_bootstrap_indices(labels: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    positive = np.flatnonzero(labels == 1)
    negative = np.flatnonzero(labels == 0)
    return np.concatenate(
        [rng.choice(positive, len(positive), replace=True), rng.choice(negative, len(negative), replace=True)]
    )


def paired_pr_auc_lift_interval(
    labels: np.ndarray,
    challenger: np.ndarray,
    baseline: np.ndarray,
    *,
    resamples: int = 1_000,
    seed: int = 20260805,
    jobs: int = 4,
) -> dict[str, float | int]:
    labels = np.asarray(labels, dtype=np.int8)
    challenger = np.asarray(challenger)
    baseline = np.asarray(baseline)

    def one(index: int) -> float:
        sampled = _stratified_bootstrap_indices(labels, seed + index)
        return float(
            average_precision_score(labels[sampled], challenger[sampled])
            - average_precision_score(labels[sampled], baseline[sampled])
        )

    lifts = np.asarray(
        Parallel(n_jobs=jobs, prefer="threads")(delayed(one)(index) for index in range(resamples))
    )
    return {
        "resamples": resamples,
        "seed": seed,
        "observed": float(
            average_precision_score(labels, challenger) - average_precision_score(labels, baseline)
        ),
        "lower_95": float(np.quantile(lifts, 0.025)),
        "upper_95": float(np.quantile(lifts, 0.975)),
    }


def population_stability_index(reference: pd.Series, comparison: pd.Series, bins: int = 10) -> float:
    epsilon = 1e-6
    if pd.api.types.is_numeric_dtype(reference):
        valid = reference.dropna()
        if valid.nunique() > bins:
            edges = np.unique(np.quantile(valid, np.linspace(0, 1, bins + 1)))
            edges[0], edges[-1] = -np.inf, np.inf
            reference_bins = pd.cut(reference, bins=edges, include_lowest=True)
            comparison_bins = pd.cut(comparison, bins=edges, include_lowest=True)
        else:
            reference_bins, comparison_bins = reference, comparison
    else:
        reference_bins, comparison_bins = reference, comparison
    reference_bins = reference_bins.astype(object).where(reference_bins.notna(), "__missing__").astype(str)
    comparison_bins = comparison_bins.astype(object).where(comparison_bins.notna(), "__missing__").astype(str)
    categories = sorted(set(reference_bins.unique()) | set(comparison_bins.unique()))
    ref_distribution = reference_bins.value_counts(normalize=True).reindex(categories, fill_value=0) + epsilon
    cmp_distribution = (
        comparison_bins.value_counts(normalize=True).reindex(categories, fill_value=0) + epsilon
    )
    return float(((cmp_distribution - ref_distribution) * np.log(cmp_distribution / ref_distribution)).sum())


def segment_metrics(
    frame: pd.DataFrame,
    labels: np.ndarray,
    probabilities: np.ndarray,
    segment: str,
    *,
    capacity: float = 0.05,
    transform: Callable[[pd.Series], pd.Series] | None = None,
    minimum_positives: int = 200,
) -> dict[str, Any]:
    values = transform(frame[segment]) if transform else frame[segment]
    threshold = np.quantile(probabilities, 1 - capacity)
    reviewed = probabilities >= threshold
    rows: list[dict[str, Any]] = []
    for value in sorted(values.dropna().unique(), key=str):
        mask = np.asarray(values == value)
        group_labels = labels[mask]
        positives = int(group_labels.sum())
        negatives = int((group_labels == 0).sum())
        selected = reviewed[mask]
        caught = int((selected & (group_labels == 1)).sum())
        false_positive = int((selected & (group_labels == 0)).sum())
        publishable = positives >= minimum_positives
        rows.append(
            {
                "group": str(value),
                "rows": int(mask.sum()),
                "positive_labels": positives,
                "publishable": publishable,
                "tpr": caught / positives if publishable else None,
                "fpr": false_positive / negatives if publishable and negatives else None,
                "precision": caught / max(int(selected.sum()), 1) if publishable else None,
                "review_rate": float(selected.mean()) if publishable else None,
                "calibration_error": (
                    float(abs(probabilities[mask].mean() - group_labels.mean())) if publishable else None
                ),
                "tpr_ci95": wilson_interval(caught, positives) if publishable else None,
                "fpr_ci95": wilson_interval(false_positive, negatives) if publishable else None,
            }
        )
    published = [row for row in rows if row["publishable"]]
    tprs = [row["tpr"] for row in published]
    fprs = [row["fpr"] for row in published]
    rates = [row["review_rate"] for row in published]
    return {
        "segment": segment,
        "minimum_positive_gate": minimum_positives,
        "groups": rows,
        "max_min_tpr_gap": max(tprs) - min(tprs) if len(tprs) >= 2 else None,
        "max_min_fpr_gap": max(fprs) - min(fprs) if len(fprs) >= 2 else None,
        "review_rate_ratio": min(rates) / max(rates) if len(rates) >= 2 and max(rates) else None,
    }

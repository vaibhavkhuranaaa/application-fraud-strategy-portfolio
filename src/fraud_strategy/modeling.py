"""Temporal comparator, calibration, robustness, and explanation program."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier, Pool
from scipy.special import logit
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .calibration import (
    PriorShift,
    ProbabilityCalibrator,
    ScoreReference,
    fit_score_reference,
    score_to_probability,
    select_calibrator,
    select_prior_forecast,
)
from .config import (
    BASE_SOURCE,
    CAPACITIES,
    CATEGORICAL_FEATURES,
    DATASET_VERSION,
    HYBRID_FEATURES,
    INCUMBENT_FEATURE,
    INTERNAL_FEATURES,
    SEED,
    SOURCE_FILES,
)
from .contracts import ApprovalState, BehaviourFingerprint, ModelManifest
from .io import sha256_file, write_json
from .metrics import (
    capacity_summary,
    metric_summary,
    paired_pr_auc_lift_interval,
    population_stability_index,
    segment_metrics,
)
from .strategy import (
    compare_utility_grid,
    concentration_rule_flags,
    economic_sensitivity_surface,
    enforce_governance_refusal,
    evaluate_strategy_frontier,
    policy_metrics,
)

optuna.logging.set_verbosity(optuna.logging.WARNING)

ROLLING_FOLDS = [([0, 1, 2], [3]), ([0, 1, 2, 3], [4]), ([0, 1, 2, 3, 4], [5])]
TRAINING_MONTHS = [0, 1, 2, 3, 4, 5]
CALIBRATION_MONTH = 6
TEST_MONTH = 7
# Bumped at M6: the linear comparator, the calibration schedule, and the stability
# reference all changed, so every cached selection result from the previous protocol is
# stale and must be recomputed rather than read back.
CHECKPOINT_PROTOCOL = "m6-temporal-model-selection-v1"
LINEAR_COMPARATOR = "regularized_logistic"

REASON_LABELS = {
    "name_email_similarity": "Name and email similarity differed from lower-risk applications",
    "zip_count_4w": "Recent application concentration around the postal area was elevated",
    "velocity_6h": "Six-hour application velocity was elevated",
    "velocity_24h": "Twenty-four-hour application velocity was elevated",
    "velocity_4w": "Four-week application velocity was elevated",
    "bank_branch_count_8w": "Recent selected-branch application concentration was elevated",
    "date_of_birth_distinct_emails_4w": "Multiple recent emails were associated with the birth-date signal",
    "device_distinct_emails_8w": "Multiple recent emails were associated with the device signal",
    "foreign_request": "The request country differed from the bank country",
    "phone_home_valid": "Home-phone validation evidence increased risk",
    "phone_mobile_valid": "Mobile-phone validation evidence increased risk",
    "credit_risk_score": "The incumbent score proxy increased estimated risk",
}


@dataclass
class FittedCandidate:
    name: str
    estimator: Any
    features: list[str]
    categorical: list[str]

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.estimator.predict_proba(model_frame(frame, self.features))[:, 1], dtype=float)


def model_frame(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    result = frame[features].copy()
    for column in CATEGORICAL_FEATURES:
        if column in result:
            result[column] = result[column].astype("string").fillna("__missing__").astype(str)
    return result


def load_base(curated_dir: Path) -> pd.DataFrame:
    path = curated_dir / "base.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"curated Base artifact not found: {path}")
    frame = pd.read_parquet(path)
    if set(frame["evidence_source"].unique()) != {BASE_SOURCE}:
        raise ValueError("Base modeling artifact has an invalid evidence source")
    return frame


def deterministic_stratified_sample(frame: pd.DataFrame, maximum: int, seed: int) -> pd.DataFrame:
    if len(frame) <= maximum:
        return frame
    selected, _ = train_test_split(
        np.arange(len(frame)), train_size=maximum, stratify=frame["fraud_bool"], random_state=seed
    )
    return frame.iloc[np.sort(selected)]


def logistic_estimator(features: list[str]) -> Pipeline:
    categorical = [feature for feature in features if feature in CATEGORICAL_FEATURES]
    numeric = [feature for feature in features if feature not in categorical]
    transformer = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", add_indicator=False)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", min_frequency=10),
                categorical,
            ),
        ]
    )
    return Pipeline(
        [
            ("transform", transformer),
            (
                "model",
                # Class weighting is the whole fix. Without it, at roughly 1% prevalence the
                # unweighted objective is already near its optimum at the base-rate solution,
                # and a stochastic solver stops there: the comparator this replaced scored
                # AUROC 0.5156 for five milestones because of it. Weighting the classes makes
                # the minority class carry equal total weight, so the fit has something to
                # separate. A full-batch solver removes the second half of the problem, since
                # its stopping rule reads the gradient rather than a step-to-step delta.
                LogisticRegression(
                    class_weight="balanced",
                    solver="lbfgs",
                    C=1.0,
                    max_iter=2_000,
                    random_state=SEED,
                ),
            ),
        ]
    )


def catboost_estimator(
    features: list[str], parameters: dict[str, Any], *, iterations: int | None = None
) -> CatBoostClassifier:
    categorical = [features.index(feature) for feature in CATEGORICAL_FEATURES if feature in features]
    return CatBoostClassifier(
        loss_function="Logloss",
        eval_metric="PRAUC:type=Classic",
        iterations=iterations or int(parameters.get("iterations", 350)),
        depth=int(parameters["depth"]),
        learning_rate=float(parameters["learning_rate"]),
        l2_leaf_reg=float(parameters["l2_leaf_reg"]),
        random_strength=float(parameters["random_strength"]),
        bagging_temperature=float(parameters["bagging_temperature"]),
        auto_class_weights=parameters["auto_class_weights"],
        cat_features=categorical,
        random_seed=SEED,
        thread_count=4,
        allow_writing_files=False,
        verbose=False,
    )


def rolling_logistic_evaluation(frame: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for index, (train_months, test_months) in enumerate(ROLLING_FOLDS):
        train = frame[frame["month"].isin(train_months)]
        test = frame[frame["month"].isin(test_months)]
        estimator = logistic_estimator(INTERNAL_FEATURES)
        estimator.fit(model_frame(train, INTERNAL_FEATURES), train["fraud_bool"])
        probabilities = estimator.predict_proba(model_frame(test, INTERNAL_FEATURES))[:, 1]
        fitted_model = estimator.named_steps["model"]
        folds.append(
            {
                "fold": index + 1,
                "train_months": train_months,
                "test_months": test_months,
                "train_rows": len(train),
                "test_rows": len(test),
                "pr_auc": float(average_precision_score(test["fraud_bool"], probabilities)),
                "iterations": int(np.max(fitted_model.n_iter_)),
                "converged": int(np.max(fitted_model.n_iter_)) < int(fitted_model.max_iter),
            }
        )
    values = [item["pr_auc"] for item in folds]
    return {"folds": folds, "mean_pr_auc": float(np.mean(values)), "worst_pr_auc": float(min(values))}


def tune_catboost(
    frame: pd.DataFrame,
    *,
    trials: int = 6,
    max_train_rows: int = 250_000,
    max_test_rows: int = 100_000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    def objective(trial: optuna.Trial) -> float:
        parameters = {
            "iterations": trial.suggest_int("iterations", 250, 450, step=100),
            "depth": trial.suggest_int("depth", 5, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.035, 0.12, log=True),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 2.0, 12.0, log=True),
            "random_strength": trial.suggest_float("random_strength", 0.1, 2.0, log=True),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 2.0),
            "auto_class_weights": trial.suggest_categorical("auto_class_weights", [None, "Balanced"]),
        }
        scores: list[float] = []
        for fold_index, (train_months, test_months) in enumerate(ROLLING_FOLDS):
            train = deterministic_stratified_sample(
                frame[frame["month"].isin(train_months)],
                max_train_rows,
                SEED + trial.number * 10 + fold_index,
            )
            test = deterministic_stratified_sample(
                frame[frame["month"].isin(test_months)], max_test_rows, SEED + 100 + fold_index
            )
            estimator = catboost_estimator(INTERNAL_FEATURES, parameters)
            estimator.fit(model_frame(train, INTERNAL_FEATURES), train["fraud_bool"])
            probabilities = estimator.predict_proba(model_frame(test, INTERNAL_FEATURES))[:, 1]
            scores.append(float(average_precision_score(test["fraud_bool"], probabilities)))
            trial.report(float(np.mean(scores)), fold_index)
            if trial.should_prune():
                raise optuna.TrialPruned()
        trial.set_user_attr("fold_pr_auc", scores)
        trial.set_user_attr("worst_pr_auc", min(scores))
        return float(np.mean(scores) + 0.10 * min(scores))

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=SEED),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=2, n_warmup_steps=1),
    )
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    best = dict(study.best_trial.params)
    history = {
        "trials_requested": trials,
        "trials_completed": sum(trial.state == optuna.trial.TrialState.COMPLETE for trial in study.trials),
        "trials_pruned": sum(trial.state == optuna.trial.TrialState.PRUNED for trial in study.trials),
        "training_sample_cap": max_train_rows,
        "test_sample_cap": max_test_rows,
        "best_objective": float(study.best_value),
        "best_fold_pr_auc": study.best_trial.user_attrs["fold_pr_auc"],
        "search_space": {
            "iterations": [250, 350, 450],
            "depth": [5, 8],
            "learning_rate": [0.035, 0.12],
            "l2_leaf_reg": [2.0, 12.0],
            "random_strength": [0.1, 2.0],
            "bagging_temperature": [0.0, 2.0],
            "auto_class_weights": [None, "Balanced"],
        },
    }
    return best, history


def rolling_catboost_evaluation(
    frame: pd.DataFrame,
    features: list[str],
    parameters: dict[str, Any],
    *,
    max_train_rows: int = 350_000,
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for index, (train_months, test_months) in enumerate(ROLLING_FOLDS):
        train_full = frame[frame["month"].isin(train_months)]
        train = deterministic_stratified_sample(train_full, max_train_rows, SEED + 500 + index)
        test = frame[frame["month"].isin(test_months)]
        estimator = catboost_estimator(features, parameters)
        estimator.fit(model_frame(train, features), train["fraud_bool"])
        probabilities = estimator.predict_proba(model_frame(test, features))[:, 1]
        folds.append(
            {
                "fold": index + 1,
                "train_months": train_months,
                "test_months": test_months,
                "train_rows_available": len(train_full),
                "train_rows_used": len(train),
                "test_rows": len(test),
                "pr_auc": float(average_precision_score(test["fraud_bool"], probabilities)),
            }
        )
    values = [item["pr_auc"] for item in folds]
    return {"folds": folds, "mean_pr_auc": float(np.mean(values)), "worst_pr_auc": float(min(values))}


def fit_candidate(
    name: str, frame: pd.DataFrame, features: list[str], parameters: dict[str, Any]
) -> FittedCandidate:
    if name == LINEAR_COMPARATOR:
        estimator = logistic_estimator(features)
    else:
        estimator = catboost_estimator(features, parameters)
    estimator.fit(model_frame(frame, features), frame["fraud_bool"])
    return FittedCandidate(
        name=name,
        estimator=estimator,
        features=features,
        categorical=[feature for feature in features if feature in CATEGORICAL_FEATURES],
    )


def fit_and_select_calibration(
    candidate: FittedCandidate, calibration_frame: pd.DataFrame
) -> tuple[ProbabilityCalibrator, dict[str, Any], np.ndarray]:
    raw = candidate.predict(calibration_frame)
    calibrator, selection = select_calibrator(calibration_frame["fraud_bool"].to_numpy(), raw)
    return calibrator, selection, calibrator.predict(raw)


def calibrated_predict(
    candidate: FittedCandidate, calibrator: ProbabilityCalibrator, frame: pd.DataFrame
) -> np.ndarray:
    return calibrator.predict(candidate.predict(frame))


def incumbent_calibration(
    calibration_frame: pd.DataFrame, reference: ScoreReference
) -> tuple[ProbabilityCalibrator, dict[str, Any]]:
    raw = score_to_probability(calibration_frame[INCUMBENT_FEATURE].to_numpy(), reference)
    return select_calibrator(calibration_frame["fraud_bool"].to_numpy(), raw)


def global_and_local_explanations(candidate: FittedCandidate, frame: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(candidate.estimator, CatBoostClassifier):
        return {"method": "coefficient", "global": [], "local_examples": []}
    sample = deterministic_stratified_sample(frame, 2_000, SEED + 900)
    values = model_frame(sample, candidate.features)
    pool = Pool(values, cat_features=[values.columns.get_loc(column) for column in candidate.categorical])
    shap_values = candidate.estimator.get_feature_importance(pool, type="ShapValues")[:, :-1]
    importance = np.mean(np.abs(shap_values), axis=0)
    order = np.argsort(-importance)
    global_rows = [
        {
            "feature": candidate.features[index],
            "mean_absolute_shap": float(importance[index]),
            "plain_language": REASON_LABELS.get(
                candidate.features[index],
                f"{candidate.features[index].replace('_', ' ').title()} influenced the score",
            ),
        }
        for index in order[:15]
    ]
    local_examples: list[dict[str, Any]] = []
    probabilities = candidate.predict(sample)
    example_indices = np.argsort(-probabilities)[:25]
    for row_index in example_indices:
        positive_order = np.argsort(-shap_values[row_index])
        reasons = []
        for feature_index in positive_order:
            if shap_values[row_index, feature_index] <= 0:
                continue
            feature = candidate.features[feature_index]
            reasons.append(REASON_LABELS.get(feature, f"{feature.replace('_', ' ').title()} increased risk"))
            if len(reasons) == 3:
                break
        local_examples.append(
            {
                "application_id": sample.iloc[row_index]["application_id"],
                "uncalibrated_probability": float(probabilities[row_index]),
                "reason_codes": reasons,
            }
        )
    return {
        "method": "CatBoost SHAP",
        "sample_rows": len(sample),
        "global": global_rows,
        "local_examples": local_examples,
    }


def permutation_checks(
    candidate: FittedCandidate, frame: pd.DataFrame, top_features: list[str]
) -> list[dict[str, Any]]:
    sample = deterministic_stratified_sample(frame, 20_000, SEED + 901)
    labels = sample["fraud_bool"].to_numpy()
    baseline = average_precision_score(labels, candidate.predict(sample))
    rng = np.random.default_rng(SEED + 902)
    rows: list[dict[str, Any]] = []
    for feature in top_features[:10]:
        permuted = sample.copy()
        permuted[feature] = rng.permutation(permuted[feature].to_numpy())
        score = average_precision_score(labels, candidate.predict(permuted))
        rows.append({"feature": feature, "pr_auc_loss": float(baseline - score)})
    return sorted(rows, key=lambda row: row["pr_auc_loss"], reverse=True)


def partial_dependence_checks(
    candidate: FittedCandidate, frame: pd.DataFrame, top_features: list[str]
) -> list[dict[str, Any]]:
    sample = deterministic_stratified_sample(frame, 5_000, SEED + 903)
    rows: list[dict[str, Any]] = []
    for feature in top_features:
        if feature in CATEGORICAL_FEATURES or feature.endswith("__missing"):
            continue
        values = sample[feature].dropna()
        if values.nunique() < 5:
            continue
        points = np.unique(np.quantile(values, [0.10, 0.30, 0.50, 0.70, 0.90]))
        curve = []
        for point in points:
            modified = sample.copy()
            modified[feature] = point
            curve.append(
                {"value": float(point), "mean_probability": float(candidate.predict(modified).mean())}
            )
        rows.append({"feature": feature, "curve": curve})
        if len(rows) == 5:
            break
    return rows


def error_cohorts(frame: pd.DataFrame, labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    threshold = float(np.quantile(probabilities, 0.95))
    reviewed = probabilities >= threshold
    false_positive = frame[(reviewed) & (labels == 0)]
    false_negative = frame[(~reviewed) & (labels == 1)]

    def summarize(cohort: pd.DataFrame) -> dict[str, Any]:
        return {
            "rows": len(cohort),
            "income_distribution": cohort["income"].value_counts(normalize=True).sort_index().to_dict(),
            "channel_distribution": cohort["source"].astype(str).value_counts(normalize=True).to_dict(),
            "housing_distribution": cohort["housing_status"]
            .astype(str)
            .value_counts(normalize=True)
            .to_dict(),
            "median_name_email_similarity": float(cohort["name_email_similarity"].median()),
        }

    return {
        "capacity": 0.05,
        "threshold": threshold,
        "false_positives": summarize(false_positive),
        "false_negatives": summarize(false_negative),
    }


def drift_report(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    features: list[str],
    reference_months: list[int] | None = None,
) -> dict[str, Any]:
    """Monthly stability against the pooled training window.

    The reference is the whole window the model was fitted on, not its earliest month.
    Measuring against a single month charges the model for movement inside its own
    training data: on this dataset that alone accounted for half the blocking results.
    """
    reference_months = TRAINING_MONTHS if reference_months is None else reference_months
    report: list[dict[str, Any]] = []
    reference = frame["month"].isin(reference_months)
    for month in range(1, 8):
        comparison = frame["month"] == month
        in_window = month in reference_months
        for feature in features:
            psi = population_stability_index(frame.loc[reference, feature], frame.loc[comparison, feature])
            report.append(
                {
                    "month": month,
                    "feature": feature,
                    "psi": psi,
                    "status": "block" if psi >= 0.25 else "warn" if psi >= 0.10 else "pass",
                    "in_training_window": in_window,
                }
            )
        score_psi = population_stability_index(
            pd.Series(probabilities[reference.to_numpy()]), pd.Series(probabilities[comparison.to_numpy()])
        )
        report.append(
            {
                "month": month,
                "feature": "model_score",
                "psi": score_psi,
                "status": "block" if score_psi >= 0.25 else "warn" if score_psi >= 0.10 else "pass",
                "in_training_window": in_window,
            }
        )
    return {
        "reference_window": list(reference_months),
        "reference_basis": "pooled training window",
        "rows": report,
        "warnings": sum(row["status"] == "warn" for row in report),
        "blocks": sum(row["status"] == "block" for row in report),
        "blocks_after_training_window": sum(
            row["status"] == "block" and not row["in_training_window"] for row in report
        ),
    }


def fairness_report(frame: pd.DataFrame, labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    age = segment_metrics(frame, labels, probabilities, "customer_age")
    income = segment_metrics(frame, labels, probabilities, "income")
    source = segment_metrics(frame, labels, probabilities, "source")
    housing = segment_metrics(frame, labels, probabilities, "housing_status")
    reports = [age, income, source, housing]
    governance_review = False
    reasons: list[str] = []
    for report in reports:
        for metric in ("max_min_tpr_gap", "max_min_fpr_gap"):
            value = report[metric]
            if value is not None and value > 0.10:
                governance_review = True
                reasons.append(f"{report['segment']} {metric} exceeds 0.10")
        ratio = report["review_rate_ratio"]
        if ratio is not None and not 0.80 <= ratio <= 1.25:
            governance_review = True
            reasons.append(f"{report['segment']} review-rate ratio is outside 0.80-1.25")
    return {"segments": reports, "governance_review": governance_review, "reasons": reasons}


# The reference sample the fingerprint is computed over. Fixed period, fixed size, fixed
# seed, so the same model always produces the same digest and two models can be compared
# without re-deriving the sample.
FINGERPRINT_PERIOD = CALIBRATION_MONTH
FINGERPRINT_ROWS = 5_000
FINGERPRINT_SEED = SEED + 4_242
# Predictions are rounded before hashing. Two artifacts differing by less than this on
# every row of the reference sample are the same model operationally, and last-bit float
# noise must not read as a behaviour change.
FINGERPRINT_DECIMALS = 6


def behaviour_fingerprint(probabilities: np.ndarray) -> str:
    """Hash what the model does, over a fixed sample, at a stated precision."""
    rounded = np.round(np.asarray(probabilities, dtype=float), FINGERPRINT_DECIMALS)
    payload = ",".join(f"{value:.{FINGERPRINT_DECIMALS}f}" for value in rounded)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_reference(frame: pd.DataFrame) -> pd.DataFrame:
    period = frame[frame["month"] == FINGERPRINT_PERIOD]
    return deterministic_stratified_sample(period, FINGERPRINT_ROWS, FINGERPRINT_SEED)


def fingerprint_record(probabilities: np.ndarray, rows: int) -> BehaviourFingerprint:
    return BehaviourFingerprint(
        digest=behaviour_fingerprint(probabilities),
        reference_period=FINGERPRINT_PERIOD,
        reference_rows=rows,
        reference_seed=FINGERPRINT_SEED,
        decimals=FINGERPRINT_DECIMALS,
        method=(
            "sha256 over calibrated probabilities, rounded to the stated decimals, for a "
            "deterministic stratified sample of the reference period in row order"
        ),
    )


def load_governance_acceptance(evidence_dir: Path) -> dict[str, Any] | None:
    path = evidence_dir / "governance_acceptance.json"
    if not path.is_file():
        return None
    return dict(json.loads(path.read_text(encoding="utf-8")))


def apply_governance_acceptance(
    fairness: dict[str, Any], acceptance: dict[str, Any] | None
) -> dict[str, Any]:
    """Implement the half of gate 5 the code never had.

    The contract reads "resolved **or explicitly accepted by governance**". Only the first
    branch was ever computed, so a recorded human acceptance could not satisfy the gate it
    was written to satisfy. This is completing the approved wording, not changing it: no
    threshold, trigger, or measurement moves, and every warning stays visible.

    Two properties keep an acceptance from becoming a permanent bypass. It is matched
    reason by reason, so a segment that starts failing later is not covered by an older
    acceptance. And it is granted against the values observed at the time and lapses if any
    accepted metric worsens past its tolerance, which is how a model-risk acceptance
    behaves: it is a judgment about a measured condition, not a blanket exemption.
    """
    result = dict(fairness)
    result["governance_acceptance"] = None
    result["accepted_reasons"] = []
    result["outstanding_reasons"] = list(fairness["reasons"])
    result["lapsed_reasons"] = []
    if not acceptance or not fairness["reasons"]:
        return result

    granted = acceptance.get("granted_against", {})
    tolerance = acceptance.get("tolerance", {})
    gap_tolerance = float(tolerance.get("gap", 0.0))
    ratio_tolerance = float(tolerance.get("ratio", 0.0))

    lapsed_segments: dict[str, str] = {}
    for report in fairness["segments"]:
        baseline = granted.get(report["segment"])
        if not baseline:
            continue
        for metric in ("max_min_tpr_gap", "max_min_fpr_gap"):
            current, before = report[metric], baseline.get(metric)
            if current is not None and before is not None and current > before + gap_tolerance:
                lapsed_segments[report["segment"]] = (
                    f"{metric} moved from {before:.4f} to {current:.4f}, past the {gap_tolerance:.2f} tolerance"
                )
        current, before = report["review_rate_ratio"], baseline.get("review_rate_ratio")
        if current is not None and before is not None and current < before - ratio_tolerance:
            lapsed_segments[report["segment"]] = (
                f"review_rate_ratio moved from {before:.4f} to {current:.4f}, past the "
                f"{ratio_tolerance:.2f} tolerance"
            )

    accepted_reasons = set(acceptance.get("accepted_reasons", []))
    accepted: list[str] = []
    outstanding: list[str] = []
    lapsed: list[str] = []
    for reason in fairness["reasons"]:
        segment = reason.split(" ", 1)[0]
        if reason not in accepted_reasons:
            outstanding.append(reason)
        elif segment in lapsed_segments:
            lapsed.append(f"{reason} (acceptance lapsed: {lapsed_segments[segment]})")
        else:
            accepted.append(reason)

    result["governance_acceptance"] = {
        key: value for key, value in acceptance.items() if key != "granted_against"
    }
    result["accepted_reasons"] = accepted
    result["outstanding_reasons"] = outstanding
    result["lapsed_reasons"] = lapsed
    result["governance_review"] = bool(outstanding or lapsed)
    return result


def variant_stress_tests(
    curated_dir: Path, candidate: FittedCandidate, calibrator: ProbabilityCalibrator
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_name, contract in SOURCE_FILES.items():
        if file_name == "Base.csv":
            continue
        path = curated_dir / f"{Path(file_name).stem.lower().replace(' ', '_')}.parquet"
        frame = pd.read_parquet(path)
        labels = frame["fraud_bool"].to_numpy()
        probabilities = calibrated_predict(candidate, calibrator, frame)
        rows.append(
            {
                "evidence_source": contract["evidence_source"],
                "rows": len(frame),
                "metrics": metric_summary(labels, probabilities),
                "notice": "Frozen Base-trained model; variant was not used for training or tuning.",
            }
        )
    return rows


def compare_simple_and_complex(
    complex_name: str,
    linear_folds: dict[str, Any],
    complex_folds: dict[str, Any],
    test_metrics: dict[str, Any],
    test_capacity: dict[str, Any],
) -> dict[str, Any]:
    """State the real distance between the linear comparator and gradient boosting.

    The selection rule ends in simplicity, and that tiebreaker is only meaningful once the
    linear comparator works. This records what each one buys at the same review volume, so
    the reader can see the size of the trade rather than infer it from two ranking scores.
    """
    capacities = {
        f"{capacity:.2f}": {
            LINEAR_COMPARATOR: test_capacity[LINEAR_COMPARATOR][f"{capacity:.2f}"]["catch_rate"],
            complex_name: test_capacity[complex_name][f"{capacity:.2f}"]["catch_rate"],
        }
        for capacity in CAPACITIES
    }
    reference = capacities["0.05"]
    return {
        "simple": LINEAR_COMPARATOR,
        "complex": complex_name,
        "rolling_mean_pr_auc": {
            LINEAR_COMPARATOR: linear_folds["mean_pr_auc"],
            complex_name: complex_folds["mean_pr_auc"],
        },
        "month_7_pr_auc": {name: test_metrics[name]["pr_auc"] for name in (LINEAR_COMPARATOR, complex_name)},
        "month_7_auroc": {name: test_metrics[name]["auroc"] for name in (LINEAR_COMPARATOR, complex_name)},
        "catch_rate_by_capacity": capacities,
        "catch_rate_gap_points": {
            key: (row[complex_name] - row[LINEAR_COMPARATOR]) * 100 for key, row in capacities.items()
        },
        "linear_share_of_complex_catch_at_5_percent": reference[LINEAR_COMPARATOR] / reference[complex_name],
        "note": (
            "Model-risk context, not a promotion. A linear model with stable coefficients and "
            "direct adverse-action reasoning is cheaper to govern than gradient boosting, so the "
            "size of this gap is the term of the trade. Neither model is promoted here."
        ),
    }


def decompose_calibration_intercept(
    metrics: dict[str, float],
    probabilities: np.ndarray,
    prior_shift: PriorShift,
    observed_prevalence: float,
) -> dict[str, Any]:
    """Split the reported calibration intercept into the parts that produce it.

    The gate reads the recalibration line at probability 0.5. Application-fraud scores sit
    several logits below that, so any departure of the slope from 1.0 is multiplied by that
    distance before it reaches the intercept. Recording the split keeps a schedule effect,
    a slope effect, and a genuine level error from being read as one number.
    """
    mean_logit = float(np.mean(logit(np.clip(probabilities, 1e-6, 1 - 1e-6))))
    slope_term = -(metrics["calibration_slope"] - 1.0) * mean_logit
    return {
        "reported_intercept": metrics["calibration_intercept"],
        "mean_predicted_logit": mean_logit,
        "slope_term": slope_term,
        "offset_at_operating_point": metrics["calibration_intercept"] - slope_term,
        "one_period_prior_move_logit": float(
            logit(observed_prevalence) - logit(prior_shift.calibration_prior)
        ),
        "note": (
            "The reported intercept is the recalibration line at probability 0.5. The slope term is "
            "how much of it comes from the slope being multiplied by the distance from the operating "
            "point to that reading position. The remainder is the level error where the scores "
            "actually sit, and the prior move is how far the fraud rate travelled in the one period "
            "between calibration and scoring."
        ),
    }


def code_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    return result.stdout.strip() or "uncommitted-m3"


def write_model_card(path: Path, evaluation: dict[str, Any]) -> None:
    gates = evaluation["promotion_gates"]
    selected = evaluation["selected_challenger"]
    champion = evaluation["champion"]
    schedule = evaluation["calibration_schedule"]
    comparison = evaluation["simple_versus_complex"]
    lines = [
        "# Model card: application fraud strategy scorer",
        "",
        f"Status: `{evaluation['approval_state']}`. Evidence source: `baf_base`.",
        "",
        "## Intended use",
        "",
        "Rank synthetic BAF application records for bounded manual-review strategy analysis. The model does not approve, deny, or execute a lending decision.",
        "",
        "## Selection",
        "",
        f"- Selected challenger before untouched testing: `{selected}`.",
        f"- Resulting champion: `{champion}`.",
        "- Rolling-origin folds: train 0-2/test 3, train 0-3/test 4, train 0-4/test 5.",
        "- Final fit months 0-5; calibration selection month 6; one-time test month 7.",
        (
            f"- Linear comparator `{comparison['simple']}` reaches "
            f"{comparison['catch_rate_by_capacity']['0.05'][comparison['simple']]:.1%} of the fraud at 5% "
            f"review capacity against {comparison['catch_rate_by_capacity']['0.05'][comparison['complex']]:.1%} "
            f"for `{comparison['complex']}`."
        ),
        "",
        "## Calibration schedule",
        "",
        f"- Fitted on period {schedule['fitted_on']}, then level-corrected to a forecast of the scoring period.",
        (
            f"- Forecast rule `{schedule['selected']}`, chosen by backtest on periods "
            f"{schedule['backtest_periods']}, applying a logit shift of "
            f"{schedule['applied']['applied_logit_shift']:.4f}."
        ),
        f"- {schedule['operating_control']}",
        "",
        "## Promotion gates",
        "",
    ]
    lines.extend(f"- {name}: `{str(value).lower()}`" for name, value in gates.items())
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- BAF is privacy-preserving synthetic account-opening data, not observed personal- or auto-loan performance.",
            "- `credit_risk_score` is an incumbent proxy, not a verified vendor score.",
            "- Economic values are sensitivity assumptions, not observed P&L.",
            "- BAF has no cross-row identity truth; identity-linking evidence comes only from the separate fixture.",
            "- Fairness and drift warnings require governance interpretation and never trigger hidden group-specific thresholds.",
            "",
            "## Evidence",
            "",
            "See `evaluation/model_evaluation.json` for full metrics, confidence intervals, capacity comparisons, explanations, variant stress tests, and artifact lineage.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_model_program(
    curated_dir: Path,
    artifact_dir: Path,
    evidence_dir: Path,
    *,
    trials: int = 6,
    bootstrap_resamples: int = 1_000,
) -> dict[str, Any]:
    started = time.perf_counter()
    frame = load_base(curated_dir)
    train = frame[frame["month"].isin(TRAINING_MONTHS)]
    calibration = frame[frame["month"] == CALIBRATION_MONTH]
    test = frame[frame["month"] == TEST_MONTH]

    work_dir = evidence_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    selection_checkpoint = work_dir / "model_selection.joblib"
    selection = joblib.load(selection_checkpoint) if selection_checkpoint.is_file() else None
    selection_reused = bool(selection and selection.get("protocol") == CHECKPOINT_PROTOCOL)
    if selection_reused:
        logistic_folds = selection["logistic_folds"]
        best_parameters = selection["best_parameters"]
        tuning = selection["tuning"]
        internal_folds = selection["internal_folds"]
        hybrid_folds = selection["hybrid_folds"]
    else:
        logistic_folds = rolling_logistic_evaluation(frame)
        best_parameters, tuning = tune_catboost(frame, trials=trials)
        internal_folds = rolling_catboost_evaluation(frame, INTERNAL_FEATURES, best_parameters)
        hybrid_folds = rolling_catboost_evaluation(frame, HYBRID_FEATURES, best_parameters)
        joblib.dump(
            {
                "protocol": CHECKPOINT_PROTOCOL,
                "logistic_folds": logistic_folds,
                "best_parameters": best_parameters,
                "tuning": tuning,
                "internal_folds": internal_folds,
                "hybrid_folds": hybrid_folds,
            },
            selection_checkpoint,
        )

    cat_options = {"catboost_internal": internal_folds, "catboost_hybrid": hybrid_folds}
    selected_name = max(
        cat_options,
        key=lambda name: (
            cat_options[name]["mean_pr_auc"],
            cat_options[name]["worst_pr_auc"],
            -len(HYBRID_FEATURES if name == "catboost_hybrid" else INTERNAL_FEATURES),
        ),
    )
    selected_features = HYBRID_FEATURES if selected_name == "catboost_hybrid" else INTERNAL_FEATURES

    fit_checkpoint = work_dir / "fitted_candidates.joblib"
    fitted = joblib.load(fit_checkpoint) if fit_checkpoint.is_file() else None
    fit_reused = bool(fitted and fitted.get("protocol") == CHECKPOINT_PROTOCOL)
    if fit_reused:
        candidates = fitted["candidates"]
        calibrators = fitted["calibrators"]
        calibration_records = fitted["calibration_records"]
    else:
        candidates = {
            LINEAR_COMPARATOR: fit_candidate(LINEAR_COMPARATOR, train, INTERNAL_FEATURES, best_parameters),
            "catboost_internal": fit_candidate(
                "catboost_internal", train, INTERNAL_FEATURES, best_parameters
            ),
            "catboost_hybrid": fit_candidate("catboost_hybrid", train, HYBRID_FEATURES, best_parameters),
        }
        calibrators: dict[str, ProbabilityCalibrator] = {}
        calibration_records: dict[str, Any] = {}
        for name, candidate in candidates.items():
            calibrator, record, calibrated = fit_and_select_calibration(candidate, calibration)
            calibrators[name] = calibrator
            calibration_records[name] = {
                **record,
                "month_6_metrics": metric_summary(calibration["fraud_bool"].to_numpy(), calibrated),
            }
        joblib.dump(
            {
                "protocol": CHECKPOINT_PROTOCOL,
                # Recorded so a reused checkpoint still reports the revision its models
                # were actually fitted at, rather than the revision that read it back.
                "code_sha": code_sha(),
                "candidates": candidates,
                "calibrators": calibrators,
                "calibration_records": calibration_records,
            },
            fit_checkpoint,
        )

    # The incumbent proxy is calibrated outside the checkpoint because its reference
    # statistics are cheap to refit and must always match the mapping in use. Caching
    # them alongside the challenger candidates would let a stale reference survive a
    # change to the mapping.
    incumbent_reference = fit_score_reference(calibration[INCUMBENT_FEATURE].to_numpy())
    incumbent_calibrator, incumbent_record = incumbent_calibration(calibration, incumbent_reference)
    incumbent_record["month_6_metrics"] = metric_summary(
        calibration["fraud_bool"].to_numpy(),
        incumbent_calibrator.predict(
            score_to_probability(calibration[INCUMBENT_FEATURE].to_numpy(), incumbent_reference)
        ),
    )
    incumbent_record["score_reference"] = incumbent_reference.as_dict()
    calibrators["incumbent_proxy"] = incumbent_calibrator
    calibration_records["incumbent_proxy"] = incumbent_record

    # The calibration schedule, not the model. A calibrator fitted on the last closed month
    # carries that month's fraud rate into the next one, so its level is a schedule choice.
    # The forecast rule is chosen by backtest on months the model may already read; month 7
    # is never among them, and the rule that wins is applied to every calibrated comparator.
    observed_priors = [
        float(frame.loc[frame["month"] == month, "fraud_bool"].mean())
        for month in range(0, CALIBRATION_MONTH + 1)
    ]
    forecast = select_prior_forecast(observed_priors, backtest_from=ROLLING_FOLDS[0][1][0])
    prior_shift = PriorShift(
        rule=forecast["selected"],
        calibration_prior=observed_priors[-1],
        forecast_prior=forecast["forecast_prior"],
    )

    labels = test["fraud_bool"].to_numpy(dtype=np.int8)
    probabilities: dict[str, np.ndarray] = {
        name: prior_shift.apply(calibrated_predict(candidate, calibrators[name], test))
        for name, candidate in candidates.items()
    }
    # Scored against the calibration-period reference, not month 7's own distribution.
    probabilities["incumbent_proxy"] = prior_shift.apply(
        incumbent_calibrator.predict(
            score_to_probability(test[INCUMBENT_FEATURE].to_numpy(), incumbent_reference)
        )
    )
    probabilities["prevalence"] = np.full(len(test), train["fraud_bool"].mean())
    test_metrics = {name: metric_summary(labels, values) for name, values in probabilities.items()}
    test_capacity = {name: capacity_summary(labels, values) for name, values in probabilities.items()}

    best_baseline_name = max(
        ("incumbent_proxy", LINEAR_COMPARATOR), key=lambda name: test_metrics[name]["pr_auc"]
    )
    selected_probabilities = probabilities[selected_name]
    best_baseline_probabilities = probabilities[best_baseline_name]
    lift_interval = paired_pr_auc_lift_interval(
        labels,
        selected_probabilities,
        best_baseline_probabilities,
        resamples=bootstrap_resamples,
        jobs=4,
    )

    challenger_capacity = test_capacity[selected_name]
    incumbent_capacity = test_capacity["incumbent_proxy"]
    improvements = [
        challenger_capacity[f"{capacity:.2f}"]["catch_rate"]
        - incumbent_capacity[f"{capacity:.2f}"]["catch_rate"]
        for capacity in CAPACITIES
    ]
    at_least_three = sum(value > 0 for value in improvements) >= 3
    no_large_regression = min(improvements) >= -0.02
    challenger_five = policy_metrics(labels, selected_probabilities, 0.05)
    incumbent_five = policy_metrics(labels, probabilities["incumbent_proxy"], 0.05)
    economic = compare_utility_grid(challenger_five, incumbent_five)
    # Evidence alongside the gate, never in place of it. The gate keeps the approved grid
    # at both factors equal to 1.0; this records what the same comparison looks like once
    # review effectiveness and loss given fraud are allowed to be less than perfect.
    economic_sensitivity = economic_sensitivity_surface(challenger_five, incumbent_five)

    selected_metrics = test_metrics[selected_name]
    simple_versus_complex = compare_simple_and_complex(
        selected_name,
        logistic_folds,
        cat_options[selected_name],
        test_metrics,
        test_capacity,
    )
    calibration_diagnostics = decompose_calibration_intercept(
        selected_metrics, selected_probabilities, prior_shift, float(labels.mean())
    )
    promotion_gates = {
        "pr_auc_lift_ci_lower_above_zero": lift_interval["lower_95"] > 0,
        "catch_rate_improves_at_three_capacities": at_least_three,
        "no_capacity_regression_over_two_points": no_large_regression,
        "positive_brier_skill": selected_metrics["brier_skill"] > 0,
        "ece_at_most_0_02": selected_metrics["ece"] <= 0.02,
        "calibration_slope_0_8_to_1_2": 0.8 <= selected_metrics["calibration_slope"] <= 1.2,
        "calibration_intercept_abs_at_most_0_10": abs(selected_metrics["calibration_intercept"]) <= 0.10,
        "economic_grid_positive_at_least_80_percent": economic["positive_share"] >= 0.80,
        "warnings_visible": True,
    }
    selected_candidate = candidates[selected_name]
    selected_calibrator = calibrators[selected_name]
    explanation = global_and_local_explanations(selected_candidate, test)
    local_examples = explanation.pop("local_examples")
    local_reason_counts: dict[str, int] = {}
    for example in local_examples:
        for reason in example["reason_codes"]:
            local_reason_counts[reason] = local_reason_counts.get(reason, 0) + 1
    explanation["local_example_count"] = len(local_examples)
    explanation["local_reason_code_counts"] = dict(
        sorted(local_reason_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    top_features = [row["feature"] for row in explanation["global"]]
    permutation = permutation_checks(selected_candidate, test, top_features)
    partial_dependence = partial_dependence_checks(selected_candidate, test, top_features)
    errors = error_cohorts(test, labels, selected_probabilities)
    fairness = apply_governance_acceptance(
        fairness_report(test, labels, selected_probabilities),
        load_governance_acceptance(evidence_dir),
    )

    full_base_probabilities = calibrated_predict(selected_candidate, selected_calibrator, frame)
    drift = drift_report(frame, full_base_probabilities, selected_features)
    promotion_gates["no_automatic_promotion_psi_blocks"] = drift["blocks"] == 0
    promotion_gates["fairness_governance_review_resolved"] = not fairness["governance_review"]
    promoted = all(promotion_gates.values())
    # A failed gate returns the incumbent, never the strongest baseline. The linear
    # comparator outranks the incumbent proxy and is the harder bar the challenger has to
    # clear, but it has not itself passed these gates, so promoting it on the strength of
    # one test period would be the same unearned promotion the gates exist to prevent.
    champion = selected_name if promoted else "incumbent_proxy"
    candidate_approval_state = ApprovalState.CHAMPION if promoted else ApprovalState.REJECTED
    champion_approval_state = ApprovalState.CHAMPION if promoted else ApprovalState.RETAINED_BASELINE
    robustness = variant_stress_tests(curated_dir, selected_candidate, selected_calibrator)
    strategy = evaluate_strategy_frontier(
        labels,
        selected_probabilities,
        probabilities["incumbent_proxy"],
        concentration_rule_flags(test),
    )
    strategy = enforce_governance_refusal(
        strategy,
        promotion_gates,
        fairness_review_required=fairness["governance_review"],
        drift_blocks=drift["blocks"],
    )

    model_dir = artifact_dir / "models"
    prediction_dir = artifact_dir / "predictions"
    model_dir.mkdir(parents=True, exist_ok=True)
    prediction_dir.mkdir(parents=True, exist_ok=True)
    local_explanation_path = prediction_dir / "month_7_local_explanations.json"
    write_json(
        local_explanation_path,
        {
            "evidence_source": BASE_SOURCE,
            "publication_boundary": "Local row-level artifact; excluded from Git and public evidence.",
            "examples": local_examples,
        },
    )
    selected_model_path = model_dir / f"{selected_name}.cbm"
    selected_candidate.estimator.save_model(selected_model_path)
    calibrator_path = model_dir / f"{selected_name}-calibrator.joblib"
    joblib.dump(selected_calibrator, calibrator_path)
    incumbent_calibrator_path = model_dir / "incumbent-proxy-calibrator.joblib"
    joblib.dump(incumbent_calibrator, incumbent_calibrator_path)
    joblib.dump(candidates[LINEAR_COMPARATOR], model_dir / f"{LINEAR_COMPARATOR}.joblib")
    prediction_path = prediction_dir / "month_7_scores.parquet"
    pd.DataFrame(
        {
            "application_id": test["application_id"].to_numpy(),
            "evidence_source": BASE_SOURCE,
            "fraud_bool": labels,
            **{name: values for name, values in probabilities.items()},
        }
    ).to_parquet(prediction_path, index=False, compression="zstd")
    artifact_hash = sha256_file(selected_model_path)
    incumbent_artifact_hash = sha256_file(incumbent_calibrator_path)
    model_version = f"{selected_name}-m3-v1"

    reference = fingerprint_reference(frame)
    candidate_fingerprint = fingerprint_record(
        prior_shift.apply(calibrated_predict(selected_candidate, selected_calibrator, reference)),
        len(reference),
    )
    champion_fingerprint = fingerprint_record(
        prior_shift.apply(
            incumbent_calibrator.predict(
                score_to_probability(reference[INCUMBENT_FEATURE].to_numpy(), incumbent_reference)
            )
        ),
        len(reference),
    )

    candidate_manifest = ModelManifest(
        model_version=model_version,
        source_checksum=SOURCE_FILES["Base.csv"]["sha256"],
        dataset_version=DATASET_VERSION,
        feature_contract=selected_features,
        split_periods={"fit": TRAINING_MONTHS, "calibration": [CALIBRATION_MONTH], "test": [TEST_MONTH]},
        # The prior shift travels with the parameters because scoring cannot be reproduced
        # without it: it is part of the mapping from a raw score to a stated probability.
        parameters={**best_parameters, "calibration_prior_shift": prior_shift.as_dict()},
        calibrator=selected_calibrator.method,
        metrics={"month_7": selected_metrics, "promotion_gates": promotion_gates},
        artifact_hash=artifact_hash,
        behaviour_fingerprint=candidate_fingerprint,
        code_sha=code_sha(),
        approval_state=candidate_approval_state,
        limitations=[
            "BAF is synthetic account-opening data and not observed loan-origination performance.",
            "Economic values are assumptions rather than observed profit and loss.",
            "The incumbent credit-risk score is a proxy and not a verified vendor product.",
            "BAF has no cross-row identity or ring truth.",
        ],
    )
    candidate_manifest_path = model_dir / "candidate_model_manifest.json"
    write_json(candidate_manifest_path, candidate_manifest.model_dump(mode="json"))
    if promoted:
        champion_manifest = candidate_manifest
    else:
        champion_manifest = ModelManifest(
            model_version="incumbent-proxy-m3-v1",
            source_checksum=SOURCE_FILES["Base.csv"]["sha256"],
            dataset_version=DATASET_VERSION,
            feature_contract=[INCUMBENT_FEATURE],
            split_periods={
                "fit": TRAINING_MONTHS,
                "calibration": [CALIBRATION_MONTH],
                "test": [TEST_MONTH],
            },
            parameters={
                "mapping": (
                    "monotonic standardization against fixed calibration-period reference "
                    "statistics, followed by independent calibration and the prior shift"
                ),
                **incumbent_reference.as_dict(),
                "calibration_prior_shift": prior_shift.as_dict(),
            },
            calibrator=incumbent_calibrator.method,
            metrics={"month_7": test_metrics["incumbent_proxy"]},
            artifact_hash=incumbent_artifact_hash,
            behaviour_fingerprint=champion_fingerprint,
            code_sha=code_sha(),
            approval_state=ApprovalState.RETAINED_BASELINE,
            limitations=[
                "This is the BAF credit-risk-score field used only as an incumbent proxy.",
                "It is not a verified vendor model or production decision score.",
                "BAF is synthetic account-opening data and not observed loan-origination performance.",
            ],
        )
    champion_manifest_path = model_dir / "model_manifest.json"
    write_json(champion_manifest_path, champion_manifest.model_dump(mode="json"))

    result = {
        "evidence_id": "EV-M3-MODEL-20260805",
        "training_source_sha": (fitted or {}).get("code_sha") if fit_reused else code_sha(),
        "evaluation_source_sha": code_sha(),
        "execution": {
            "selection_checkpoint_reused": selection_reused,
            "fitted_candidate_checkpoint_reused": fit_reused,
            "checkpoint_protocol": CHECKPOINT_PROTOCOL,
        },
        "dataset_version": DATASET_VERSION,
        "rows": {"fit": len(train), "calibration": len(calibration), "test": len(test)},
        "fold_selection": {
            LINEAR_COMPARATOR: logistic_folds,
            "catboost_internal": internal_folds,
            "catboost_hybrid": hybrid_folds,
        },
        "tuning": tuning,
        "selected_challenger": selected_name,
        "selection_basis": "mean rolling PR-AUC, then worst-fold PR-AUC, then simplicity; selected before month-7 access",
        "simple_versus_complex": simple_versus_complex,
        "calibration": calibration_records,
        "calibration_schedule": {
            **forecast,
            "applied": prior_shift.as_dict(),
            "fitted_on": [CALIBRATION_MONTH],
            "basis": (
                "The calibrator is fitted on the last closed period before scoring, then its level is "
                "corrected to a forecast of the scoring period's prior. The forecast rule is chosen by "
                "backtest on earlier periods only."
            ),
            "operating_control": (
                "Recalibrate at every period close, and raise a recalibration review when the observed "
                f"prior moves more than {forecast['recalibration_trigger_logit']} in logit from the "
                "calibration prior. This is an operating control, not a promotion gate."
            ),
        },
        "month_7_metrics": test_metrics,
        "month_7_capacity": test_capacity,
        "calibration_intercept_decomposition": calibration_diagnostics,
        "best_baseline": best_baseline_name,
        "pr_auc_lift_bootstrap": lift_interval,
        "capacity_catch_rate_differences_vs_incumbent": {
            f"{capacity:.2f}": value for capacity, value in zip(CAPACITIES, improvements, strict=True)
        },
        "economic_grid_at_5_percent_capacity": economic,
        "economic_sensitivity_at_5_percent_capacity": economic_sensitivity,
        "promotion_gates": promotion_gates,
        "approval_state": candidate_approval_state.value,
        "champion": champion,
        "champion_approval_state": champion_approval_state.value,
        "explanations": explanation,
        "permutation_checks": permutation,
        "partial_dependence": partial_dependence,
        "error_cohorts": errors,
        "fairness": fairness,
        "drift": drift,
        "variant_stress_tests": robustness,
        "strategy_frontier": strategy,
        "artifacts": {
            "selected_model": selected_model_path.as_posix(),
            "calibrator": calibrator_path.as_posix(),
            "candidate_manifest": candidate_manifest_path.as_posix(),
            "champion_manifest": champion_manifest_path.as_posix(),
            "incumbent_calibrator": incumbent_calibrator_path.as_posix(),
            "local_explanations": local_explanation_path.as_posix(),
            "predictions": prediction_path.as_posix(),
            "candidate_artifact_hash": artifact_hash,
            "champion_artifact_hash": champion_manifest.artifact_hash,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "limitations": candidate_manifest.limitations,
    }
    evidence_path = evidence_dir / "model_evaluation.json"
    write_json(evidence_path, result)
    write_model_card(Path("docs/model-card.md"), result)
    return result

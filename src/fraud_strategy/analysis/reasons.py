"""Row-level reason codes for the review queue.

These come from the rejected challenger model, so the interface labels them as
challenger diagnostics rather than as champion behaviour. The retained champion is
the single incumbent score proxy and has no multi-feature explanation to give.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool

from ..config import CATEGORICAL_FEATURES, HYBRID_FEATURES
from ..modeling import REASON_LABELS, model_frame

MAX_REASONS = 3


@lru_cache(maxsize=1)
def _load(path_key: str) -> CatBoostClassifier:
    estimator = CatBoostClassifier()
    estimator.load_model(path_key)
    return estimator


def reason_label(feature: str) -> str:
    label = REASON_LABELS.get(feature, f"{feature.replace('_', ' ').title()} raised the ranking score")
    return (
        label.replace("increased estimated risk", "raised the ranking score")
        .replace("increased risk", "raised the ranking score")
        .replace("lower-risk applications", "lower-score applications")
    )


def reason_codes(frame: pd.DataFrame, model_path: Path, limit: int = MAX_REASONS) -> list[list[str]]:
    """Plain-language drivers that pushed each row's challenger score upward.

    Returns an empty list per row when the challenger artifact is unavailable, so the
    queue still renders its observed scores rather than failing outright.
    """
    if not model_path.is_file() or frame.empty:
        return [[] for _ in range(len(frame))]
    estimator = _load(model_path.as_posix())
    values = model_frame(frame, HYBRID_FEATURES)
    pool = Pool(
        values,
        cat_features=[values.columns.get_loc(column) for column in CATEGORICAL_FEATURES],
    )
    shap_values = estimator.get_feature_importance(pool, type="ShapValues")[:, :-1]
    output: list[list[str]] = []
    for row in range(shap_values.shape[0]):
        order = np.argsort(-shap_values[row])
        reasons: list[str] = []
        for index in order:
            if shap_values[row, index] <= 0:
                continue
            reasons.append(reason_label(HYBRID_FEATURES[index]))
            if len(reasons) == limit:
                break
        output.append(reasons)
    return output

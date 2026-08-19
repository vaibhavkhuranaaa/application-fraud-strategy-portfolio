import numpy as np
import pandas as pd

from fraud_strategy.config import (
    BASE_COLUMNS,
    EXCLUDED_FEATURES,
    HYBRID_FEATURES,
    INTERNAL_FEATURES,
)
from fraud_strategy.data import normalize_frame


def base_frame() -> pd.DataFrame:
    values = {column: [0, 1] for column in BASE_COLUMNS}
    for column in ("payment_type", "employment_status", "housing_status", "source", "device_os"):
        values[column] = ["AA", "AB"]
    values["month"] = [0, 7]
    values["fraud_bool"] = [0, 1]
    values["income"] = [0.1, 0.9]
    values["intended_balcon_amount"] = [0.0, 1.0]
    return pd.DataFrame(values, columns=BASE_COLUMNS)


def test_normalization_preserves_target_and_adds_missing_indicators() -> None:
    frame = base_frame()
    frame.loc[0, "prev_address_months_count"] = -1
    frame.loc[0, "intended_balcon_amount"] = -0.5
    normalized = normalize_frame(frame, "Base.csv")
    assert np.isnan(normalized.loc[0, "prev_address_months_count"])
    assert normalized.loc[0, "prev_address_months_count__missing"] == 1
    assert np.isnan(normalized.loc[0, "intended_balcon_amount"])
    assert normalized.loc[0, "intended_balcon_amount__missing"] == 1
    assert normalized["fraud_bool"].tolist() == [0, 1]


def test_immutable_feature_contract_excludes_leakage_and_audit_fields() -> None:
    assert not set(EXCLUDED_FEATURES) & set(INTERNAL_FEATURES)
    assert "credit_risk_score" not in INTERNAL_FEATURES
    assert "credit_risk_score" in HYBRID_FEATURES
    assert "customer_age" not in HYBRID_FEATURES
    assert "days_since_request" not in HYBRID_FEATURES

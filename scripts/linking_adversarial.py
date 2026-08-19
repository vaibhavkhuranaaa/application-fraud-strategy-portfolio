"""Adversarial hardening of the linking fixture, and the base-rate test it never had.

Clean pairwise F1 of 1.000 is not evidence that the approach works. The generator produces
duplicates by perturbing fields, and the matcher looks for exactly those fields, so a
perfect score says the implementation matches the generator's assumptions. Two things are
missing from that, and both are measured here.

**The acceptance rule has a hard blind spot.** `pair_evidence` accepts a pair only when
`score >= 0.72 and ({email, phone} intersects the exactly-matching signals)`. A pair that
varies both email and phone can never be accepted, at any score, even with device and
address matching exactly. This was found by building the daily suspect report rather than
by inspection: fixture ring members share device and address exactly and produced zero
accepted pairs, so ring detection had to be rebuilt on a separate path. Uniform corruption
cannot express this, because it degrades every signal at once. Corrupting only the two
signals the rule depends on can.

The rule is defensible. Requiring a strong identifier suppresses false merges across shared
households and shared devices, and a false merge is the expensive error: it produces a wrong
decline on someone who did nothing. What was missing is that the trade was never written
down or measured, so nobody could weigh it.

**Precision was never tested at a realistic duplicate rate.** The fixture carries 1,000
positive pairs in 50,000 applications. Real duplicate rates are orders of magnitude lower,
and precision degrades as the base rate falls because false positives scale with the
population while true positives scale with the duplicates. A matcher that looks excellent at
a rich base rate can be unusable at a sparse one.

    PYTHONPATH=src uv run python scripts/linking_adversarial.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.config import DATASET_VERSION, DEFAULT_EVIDENCE_DIR  # noqa: E402
from fraud_strategy.io import write_json  # noqa: E402
from fraud_strategy.linking import (  # noqa: E402
    SIGNALS,
    WEIGHTS,
    evaluate_fixture,
    generate_fixture,
)
from fraud_strategy.modeling import code_sha  # noqa: E402

APPLICATIONS = 50_000
RINGS = 200
POSITIVE_PAIRS = 1_000
RATES = (0.0, 0.25, 0.50, 0.75, 1.00)

# The two signals the acceptance rule requires, and the two it does not. An adversary who
# knows the rule varies the first pair and leaves the second alone, which costs nothing.
RULE_CRITICAL = ("email", "phone")
RULE_INCIDENTAL = ("device", "address")


def measure(key: bytes, *, positive_pairs: int = POSITIVE_PAIRS, **kwargs: Any) -> dict[str, Any]:
    fixture = generate_fixture(
        key, applications=APPLICATIONS, rings=RINGS, positive_pairs=positive_pairs, **kwargs
    )
    result = evaluate_fixture(fixture)
    pairwise = result["pairwise"]
    return {
        "positive_pairs": int(result["positive_pairs"]),
        "duplicate_pair_rate": positive_pairs / APPLICATIONS,
        "candidate_pairs": int(result["candidate_pairs"]),
        "accepted_pairs": int(result["accepted_pairs"]),
        "precision": float(pairwise["precision"]),
        "recall": float(pairwise["recall"]),
        "f1": float(pairwise["f1"]),
        "false_merge_rate": float(result["false_merge_rate"]),
    }


def build(evidence_dir: Path, key: bytes) -> dict[str, Any]:
    started = time.perf_counter()
    baseline = measure(key)

    # Vary only the signals the acceptance rule depends on.
    targeted = [
        {
            "corruption_rate": rate,
            "corrupted_signals": list(RULE_CRITICAL),
            **measure(key, signal_corruption={signal: rate for signal in RULE_CRITICAL}),
        }
        for rate in RATES
    ]
    # Control: vary the other two at the same rates. If recall holds here and collapses
    # above, the cause is the acceptance rule rather than corruption in general.
    control = [
        {
            "corruption_rate": rate,
            "corrupted_signals": list(RULE_INCIDENTAL),
            **measure(key, signal_corruption={signal: rate for signal in RULE_INCIDENTAL}),
        }
        for rate in RATES
    ]
    base_rate = [measure(key, positive_pairs=pairs) for pairs in (1_000, 500, 200, 100, 50)]

    worst_targeted = min(targeted, key=lambda row: row["recall"])
    matched_control = next(
        row for row in control if row["corruption_rate"] == worst_targeted["corruption_rate"]
    )
    sparsest = base_rate[-1]
    return {
        "evidence_id": "m8-linking-adversarial-v1",
        "dataset_version": DATASET_VERSION,
        "code_sha": code_sha(),
        "evidence_source": "synthetic_link_fixture",
        "boundary": (
            "Fixture only. BAF has no cross-row identity truth and no BAF application is linked, "
            "duplicated, or described as part of a ring anywhere in this analysis."
        ),
        "acceptance_rule": {
            "expression": "score >= 0.72 and ({email, phone} intersects exact signals)",
            "signal_weights": dict(WEIGHTS),
            "signals": list(SIGNALS),
            "blind_spot": (
                "A pair varying both email and phone cannot be accepted at any score, including a "
                "perfect match on device and address."
            ),
            "why_it_exists": (
                "Requiring a strong identifier suppresses false merges across shared households and "
                "shared devices. A false merge produces a wrong decline on someone who did nothing, "
                "which is the more expensive error."
            ),
        },
        "baseline_clean": baseline,
        "targeted_corruption": targeted,
        "control_corruption": control,
        "base_rate_sweep": base_rate,
        "findings": {
            "recall_at_full_targeted_corruption": worst_targeted["recall"],
            "recall_at_matching_control_corruption": matched_control["recall"],
            "targeted_corruption_collapses_recall": worst_targeted["recall"] < 0.5 * baseline["recall"],
            "control_corruption_holds_recall": matched_control["recall"] > 0.8 * baseline["recall"],
            "precision_at_richest_base_rate": base_rate[0]["precision"],
            "precision_at_sparsest_base_rate": sparsest["precision"],
            "sparsest_duplicate_pair_rate": sparsest["duplicate_pair_rate"],
            "base_rate_test_is_informative": sparsest["precision"] < base_rate[0]["precision"],
            "base_rate_interpretation": (
                "Precision does not move as the duplicate rate falls, and that is a statement about "
                "the fixture rather than about the matcher. Precision degrades under a falling base "
                "rate only when the population contains near-misses the matcher can confuse for "
                "duplicates. This fixture generates distinct entities from independent hashes, so "
                "there are no hard negatives to confuse and the matcher produces no false positives "
                "at any base rate. The test therefore cannot measure what it was written to measure, "
                "which is the same generator-and-matcher-share-assumptions problem in a second place. "
                "A fixture that could test precision would have to synthesise plausible non-duplicates: "
                "shared households, recycled phone numbers, family email patterns, address "
                "standardisation collisions."
            ),
        },
        "limitations": [
            "The fixture generator and the matcher still share assumptions about what a duplicate "
            "looks like. Targeted corruption tests the acceptance rule, not the modelling of identity.",
            "Real duplicate rates are lower still than the sparsest point measured here, and real "
            "evasion is adaptive rather than random character corruption.",
            "Nothing here transfers to BAF, which has no cross-row identity truth.",
        ],
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    arguments = parser.parse_args()
    key = os.environ.get("FRAUD_LINK_HMAC_KEY", "")
    if len(key.encode()) < 16:
        raise SystemExit("FRAUD_LINK_HMAC_KEY must be set to at least 16 bytes")

    result = build(arguments.evidence_dir, key.encode())
    write_json(arguments.evidence_dir / "linking_adversarial.json", result)

    print(
        f"clean baseline: precision {result['baseline_clean']['precision']:.4f} "
        f"recall {result['baseline_clean']['recall']:.4f} f1 {result['baseline_clean']['f1']:.4f}\n"
    )
    print(f"{'rate':>6}{'targeted recall':>18}{'control recall':>17}{'targeted f1':>14}")
    for hit, control in zip(result["targeted_corruption"], result["control_corruption"], strict=True):
        print(
            f"{hit['corruption_rate']:>6.2f}{hit['recall']:>18.4f}{control['recall']:>17.4f}{hit['f1']:>14.4f}"
        )
    print(f"\n{'dup rate':>10}{'pairs':>8}{'precision':>12}{'recall':>10}{'false merge':>13}")
    for row in result["base_rate_sweep"]:
        print(
            f"{row['duplicate_pair_rate']:>10.4f}{row['positive_pairs']:>8}"
            f"{row['precision']:>12.4f}{row['recall']:>10.4f}{row['false_merge_rate']:>13.4f}"
        )


if __name__ == "__main__":
    main()

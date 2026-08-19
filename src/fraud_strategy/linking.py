"""Deterministic HMAC-token identity-linking proof with withheld truth."""

from __future__ import annotations

import hashlib
import hmac
import itertools
import string
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import SEED
from .io import stable_id, write_json

SIGNALS = ("email", "phone", "device", "address")
WEIGHTS = {"email": 0.35, "phone": 0.30, "device": 0.20, "address": 0.15}


@dataclass(frozen=True)
class Fixture:
    application_ids: list[str]
    token_records: list[dict[str, dict[str, Any]]]
    entity_truth: list[str]
    ring_truth: list[str | None]
    positive_pairs: set[tuple[int, int]]


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def normalize(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def keyed_token(key: bytes, signal: str, value: str) -> str:
    return hmac.new(key, f"{signal}|{value}".encode(), hashlib.sha256).hexdigest()[:32]


def fuzzy_tokens(key: bytes, signal: str, value: str, width: int = 3) -> tuple[str, ...]:
    normalized = f"^^{normalize(value)}$$"
    grams = {normalized[index : index + width] for index in range(max(len(normalized) - width + 1, 1))}
    return tuple(sorted(keyed_token(key, f"{signal}-ngram", gram) for gram in grams))


def corrupt(value: str, rng: np.random.Generator) -> str:
    if len(value) < 3:
        return value + "x"
    operation = int(rng.integers(0, 3))
    index = int(rng.integers(1, len(value) - 1))
    if operation == 0:
        return value[:index] + value[index + 1 :]
    if operation == 1:
        replacement = rng.choice(list(string.ascii_lowercase + string.digits))
        return value[:index] + str(replacement) + value[index + 1 :]
    return value[:index] + value[index + 1] + value[index] + value[index + 2 :]


def raw_signals(entity_number: int, ring_number: int | None) -> dict[str, str]:
    digest = hashlib.sha256(f"synthetic-entity-{entity_number}".encode()).hexdigest()
    signals = {
        "email": f"{digest[:16]}@mail-{digest[16:24]}.example",
        "phone": f"{int(digest[24:40], 16) % 10_000_000_000:010d}",
        "device": f"device-{digest[40:56]}",
        "address": f"{int(digest[8:16], 16) % 99999} synthetic-{digest[56:64]} avenue",
    }
    if ring_number is not None:
        signals["device"] = f"ring-device-{ring_number:04d}"
        signals["address"] = f"{ring_number + 500} shared synthetic suite"
    return signals


def generate_fixture(
    key: bytes,
    *,
    applications: int = 50_000,
    rings: int = 200,
    positive_pairs: int = 1_000,
    corruption_rate: float = 0.0,
    seed: int = SEED,
    signal_corruption: dict[str, float] | None = None,
) -> Fixture:
    """Build the deterministic fixture.

    `signal_corruption` corrupts named signals at their own rates instead of corrupting
    every signal at `corruption_rate`. It exists so the matcher can be tested against an
    adversary who varies the fields the matcher weights most, which is the cheapest evasion
    available and the one uniform corruption cannot express. The random draw is taken for
    every signal either way, so a fixture built without it is byte-identical to before.
    """
    if len(key) < 16:
        raise ValueError("HMAC key must contain at least 16 bytes")
    if applications < positive_pairs * 2 + rings * 5:
        raise ValueError("fixture is too small for the requested truth contract")
    if not 0 <= corruption_rate <= 1:
        raise ValueError("corruption_rate must be in [0, 1]")

    entity_count = applications - positive_pairs
    duplicated_entities = set(range(positive_pairs))
    ring_start = positive_pairs
    ring_members = {
        ring_start + ring_number * 5 + offset: ring_number
        for ring_number in range(rings)
        for offset in range(5)
    }
    entity_sequence = list(range(entity_count)) + list(range(positive_pairs))
    rng = np.random.default_rng(seed)
    rng.shuffle(entity_sequence)

    application_ids: list[str] = []
    records: list[dict[str, dict[str, Any]]] = []
    entities: list[str] = []
    ring_truth: list[str | None] = []
    positions: dict[int, list[int]] = defaultdict(list)
    for application_number, entity_number in enumerate(entity_sequence):
        ring_number = ring_members.get(entity_number)
        raw = raw_signals(entity_number, ring_number)
        token_record: dict[str, dict[str, Any]] = {}
        for signal, value in raw.items():
            rate = corruption_rate if signal_corruption is None else signal_corruption.get(signal, 0.0)
            if rng.random() < rate:
                value = corrupt(value, rng)
            normalized = normalize(value)
            token_record[signal] = {
                "exact": keyed_token(key, signal, normalized),
                "fuzzy": fuzzy_tokens(key, signal, normalized),
            }
        application_ids.append(
            stable_id("synthetic-link-fixture-v1", seed, corruption_rate, application_number)
        )
        records.append(token_record)
        entities.append(f"entity-{entity_number:08d}")
        ring_truth.append(f"ring-{ring_number:04d}" if ring_number is not None else None)
        positions[entity_number].append(application_number)

    pair_truth = {
        tuple(sorted(indices))
        for entity_number, indices in positions.items()
        if entity_number in duplicated_entities and len(indices) == 2
    }
    if len(pair_truth) != positive_pairs:
        raise RuntimeError("fixture did not create the requested positive-pair count")
    return Fixture(application_ids, records, entities, ring_truth, pair_truth)


def dice(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    return 2 * len(left_set & right_set) / max(len(left_set) + len(right_set), 1)


def candidate_pairs(
    records: list[dict[str, dict[str, Any]]], maximum_block_size: int = 20
) -> set[tuple[int, int]]:
    blocks: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        for signal in SIGNALS:
            blocks[(signal, record[signal]["exact"])].append(index)
    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        if 1 < len(members) <= maximum_block_size:
            pairs.update(itertools.combinations(members, 2))
    return pairs


def pair_evidence(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]]
) -> tuple[float, dict[str, Any]]:
    similarities: dict[str, float] = {}
    exact: list[str] = []
    for signal in SIGNALS:
        if left[signal]["exact"] == right[signal]["exact"]:
            similarities[signal] = 1.0
            exact.append(signal)
        else:
            similarities[signal] = dice(left[signal]["fuzzy"], right[signal]["fuzzy"])
    score = sum(WEIGHTS[signal] * similarities[signal] for signal in SIGNALS)
    accepted = score >= 0.72 and bool({"email", "phone"} & set(exact))
    return float(score), {"similarities": similarities, "exact_signals": exact, "accepted": accepted}


def match_fixture(
    fixture: Fixture,
) -> tuple[set[tuple[int, int]], list[int], dict[tuple[int, int], dict[str, Any]]]:
    candidates = candidate_pairs(fixture.token_records)
    accepted: set[tuple[int, int]] = set()
    evidence: dict[tuple[int, int], dict[str, Any]] = {}
    union_find = UnionFind(len(fixture.application_ids))
    for left, right in candidates:
        score, details = pair_evidence(fixture.token_records[left], fixture.token_records[right])
        evidence[(left, right)] = {"score": score, **details}
        if details["accepted"]:
            accepted.add((left, right))
            union_find.union(left, right)
    clusters = [union_find.find(index) for index in range(len(fixture.application_ids))]
    return accepted, clusters, evidence


def b_cubed(entity_truth: list[str], clusters: list[int]) -> dict[str, float]:
    truth_members: dict[str, set[int]] = defaultdict(set)
    cluster_members: dict[int, set[int]] = defaultdict(set)
    for index, (truth, cluster) in enumerate(zip(entity_truth, clusters, strict=True)):
        truth_members[truth].add(index)
        cluster_members[cluster].add(index)
    precisions: list[float] = []
    recalls: list[float] = []
    for truth, cluster in zip(entity_truth, clusters, strict=True):
        intersection = len(truth_members[truth] & cluster_members[cluster])
        precisions.append(intersection / len(cluster_members[cluster]))
        recalls.append(intersection / len(truth_members[truth]))
    precision, recall = float(np.mean(precisions)), float(np.mean(recalls))
    return {"precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall)}


def detect_rings(fixture: Fixture) -> tuple[set[str], dict[str, Any]]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, record in enumerate(fixture.token_records):
        groups[(record["device"]["exact"], record["address"]["exact"])].append(index)
    flagged_groups = [members for members in groups.values() if 3 <= len(members) <= 12]
    predicted: set[str] = set()
    false_groups = 0
    delays: list[int] = []
    for members in flagged_groups:
        truths = [fixture.ring_truth[index] for index in members if fixture.ring_truth[index] is not None]
        if truths:
            values, counts = np.unique(truths, return_counts=True)
            best = str(values[int(np.argmax(counts))])
            if int(max(counts)) >= 3:
                predicted.add(best)
                full_positions = [index for index, ring in enumerate(fixture.ring_truth) if ring == best]
                member_positions = sorted(index for index in members if fixture.ring_truth[index] == best)
                delays.append(member_positions[2] - min(full_positions))
            else:
                false_groups += 1
        else:
            false_groups += 1
    truth = {ring for ring in fixture.ring_truth if ring is not None}
    return predicted, {
        "truth_rings": len(truth),
        "flagged_rings": len(predicted),
        "ring_recall": len(predicted & truth) / len(truth),
        "false_ring_groups": false_groups,
        "median_applications_to_flag_after_first_ring_application": float(np.median(delays))
        if delays
        else None,
        "queue_impact_applications": sum(len(members) for members in flagged_groups),
    }


def evaluate_fixture(fixture: Fixture) -> dict[str, Any]:
    started = time.perf_counter()
    accepted, clusters, evidence = match_fixture(fixture)
    truth = fixture.positive_pairs
    true_positive = len(accepted & truth)
    false_positive = len(accepted - truth)
    false_negative = len(truth - accepted)
    precision = true_positive / max(len(accepted), 1)
    recall = true_positive / len(truth)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    false_merge_rate = false_positive / max(len(accepted), 1)
    entity_counts = Counter(fixture.entity_truth)
    duplicated_entities = {entity for entity, count in entity_counts.items() if count > 1}
    split_entities = 0
    for entity in duplicated_entities:
        members = [index for index, truth_entity in enumerate(fixture.entity_truth) if truth_entity == entity]
        if len({clusters[index] for index in members}) > 1:
            split_entities += 1
    _, ring_metrics = detect_rings(fixture)
    return {
        "applications": len(fixture.application_ids),
        "positive_pairs": len(truth),
        "candidate_pairs": len(evidence),
        "accepted_pairs": len(accepted),
        "pairwise": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "b_cubed": b_cubed(fixture.entity_truth, clusters),
        "false_merge_rate": false_merge_rate,
        "false_splits": split_entities,
        "ring_flags": ring_metrics,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def run_linking_program(
    key: bytes,
    evidence_dir: Path,
    *,
    applications: int = 50_000,
    seeds: tuple[int, ...] = (SEED, SEED + 1, SEED + 2),
) -> dict[str, Any]:
    started = time.perf_counter()
    runs: list[dict[str, Any]] = []
    for corruption in (0.0, 0.05, 0.15, 0.30):
        for seed in seeds:
            fixture = generate_fixture(
                key,
                applications=applications,
                rings=200,
                positive_pairs=1_000,
                corruption_rate=corruption,
                seed=seed,
            )
            metrics = evaluate_fixture(fixture)
            runs.append({"corruption": corruption, "seed": seed, **metrics})
    grouped: dict[str, Any] = {}
    for corruption in (0.0, 0.05, 0.15, 0.30):
        selected = [row for row in runs if row["corruption"] == corruption]
        f1_values = [row["pairwise"]["f1"] for row in selected]
        merge_values = [row["false_merge_rate"] for row in selected]
        grouped[f"{corruption:.2f}"] = {
            "pairwise_f1_mean": float(np.mean(f1_values)),
            "pairwise_f1_min": float(min(f1_values)),
            "pairwise_f1_range": float(max(f1_values) - min(f1_values)),
            "false_merge_rate_max": float(max(merge_values)),
            "max_elapsed_seconds": float(max(row["elapsed_seconds"] for row in selected)),
        }
    gates = {
        "clean_pairwise_f1_at_least_0_90": grouped["0.00"]["pairwise_f1_min"] >= 0.90,
        "fifteen_percent_pairwise_f1_at_least_0_80": grouped["0.15"]["pairwise_f1_min"] >= 0.80,
        "false_merge_rate_at_most_0_02": max(
            row["false_merge_rate"] for row in runs if row["corruption"] <= 0.15
        )
        <= 0.02,
        "stable_within_two_percentage_points": max(
            grouped["0.00"]["pairwise_f1_range"], grouped["0.15"]["pairwise_f1_range"]
        )
        <= 0.02,
        "reference_runtime_under_five_minutes": max(row["elapsed_seconds"] for row in runs) < 300,
    }
    result = {
        "evidence_id": "EV-M3-LINKING-20260805",
        "evidence_source": "synthetic_link_fixture",
        "fixture_contract": {
            "applications": applications,
            "rings": 200,
            "positive_pairs": 1_000,
            "signals": list(SIGNALS),
            "privacy": "Only HMAC exact and HMAC n-gram tokens enter matching; raw generated values are transient.",
            "truth_boundary": "entity_id and ring_id are held only by evaluation and are never passed to matching.",
        },
        "runs": runs,
        "summary": grouped,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "limitation": "Fixture quality is not evidence that BAF or production identities can be resolved.",
    }
    write_json(evidence_dir / "linking_evaluation.json", result)
    return result

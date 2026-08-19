"""Daily suspect-application report from linking analysis.

The posting makes this a named daily duty at a stated 15% of the role: link incoming
applications on customer matching data and produce a report highlighting suspected
applications for the Enterprise Fraud Group. The project already had a linking engine and
a validation harness. It had no operational output, which is the part the desk actually
receives.

Boundary, and it is not negotiable. BAF rows carry no relationship to one another by its
publisher's own statement, so nothing here runs on BAF and no BAF row is ever described
as linked, duplicated, or part of a ring. This report runs on the separately generated
deterministic fixture, which has entity and ring truth, and every number it produces is a
statement about that fixture.

Arrival order is the fixture's own row order, split into equal days. Pairs are matched
once over the whole fixture and then attributed to the day the later application of the
pair arrived, which produces the same flag timing as scoring each day against history and
costs one pass instead of one per day.

Two flag types, because a fraud desk treats them differently:

- `duplicate_identity`, an accepted pair. The same identity applying more than once.
- `suspected_ring`, a cluster of 3 to 12 applications sharing device and address. Below 3
  there is no ring to investigate, and above 12 the group is a data artifact rather than
  a ring, which is the same window the linking evaluation uses.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import SEED
from .linking import (
    Fixture,
    UnionFind,
    candidate_pairs,
    generate_fixture,
    pair_evidence,
)
from .modeling import code_sha

DEFAULT_DAYS = 20
RING_MINIMUM = 3
RING_MAXIMUM = 12


def accepted_pairs_by_arrival(fixture: Fixture) -> list[tuple[int, int, int, dict[str, Any]]]:
    """Accepted pairs ordered by when the desk could first have seen them.

    A pair is visible on the day its later application arrives, never earlier, so this is
    what an end-of-day run would have had in front of it.
    """
    results: list[tuple[int, int, int, dict[str, Any]]] = []
    for left, right in candidate_pairs(fixture.token_records):
        score, details = pair_evidence(fixture.token_records[left], fixture.token_records[right])
        if details["accepted"]:
            results.append(
                (max(left, right), min(left, right), max(left, right), {"score": score, **details})
            )
    results.sort(key=lambda item: item[0])
    return results


def day_of(index: int, applications: int, days: int) -> int:
    per_day = -(-applications // days)
    return min(index // per_day, days - 1)


def build_daily_report(fixture: Fixture, *, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    started = time.perf_counter()
    applications = len(fixture.application_ids)
    union_find = UnionFind(applications)
    members: dict[int, set[int]] = defaultdict(set)
    reported_pairs: set[tuple[int, int]] = set()
    reported_rings: set[int] = set()
    shared_signals: dict[int, set[str]] = defaultdict(set)

    daily: list[dict[str, Any]] = [
        {
            "day": day,
            "applications_received": 0,
            "duplicate_identity_flags": 0,
            "suspected_ring_flags": 0,
            "applications_referred": 0,
            "flags": [],
        }
        for day in range(days)
    ]
    for index in range(applications):
        daily[day_of(index, applications, days)]["applications_received"] += 1

    for arrival, other, _, details in accepted_pairs_by_arrival(fixture):
        day = day_of(arrival, applications, days)
        record = daily[day]
        key = (min(arrival, other), max(arrival, other))
        if key not in reported_pairs:
            reported_pairs.add(key)
            record["duplicate_identity_flags"] += 1
            record["flags"].append(
                {
                    "type": "duplicate_identity",
                    "applications": [
                        fixture.application_ids[key[0]],
                        fixture.application_ids[key[1]],
                    ],
                    "match_score": round(float(details["score"]), 4),
                    "exact_signals": sorted(details["exact_signals"]),
                }
            )
            record["applications_referred"] += 2

        union_find.union(arrival, other)
        root = union_find.find(arrival)
        merged = members.pop(union_find.find(other), set()) | members.pop(root, set())
        merged |= {arrival, other}
        members[root] = merged
        shared_signals[root] |= set(details["exact_signals"])

    # Rings are a different mechanism and must not be folded into the pair matcher. That
    # matcher only accepts a pair sharing an exact email or phone, which is the right rule
    # for "same identity twice" and the wrong one for a ring: ring members are distinct
    # identities that share infrastructure. Grouping on exact device and address is what
    # surfaces them, and it is the same 3-to-12 window the linking evaluation uses.
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, record_tokens in enumerate(fixture.token_records):
        groups[(record_tokens["device"]["exact"], record_tokens["address"]["exact"])].append(index)
    ring_groups: dict[int, list[int]] = {}
    for group_index, (signals, positions) in enumerate(sorted(groups.items())):
        if not RING_MINIMUM <= len(positions) <= RING_MAXIMUM:
            continue
        ordered = sorted(positions)
        # Flagged on the day the group crosses the minimum, not the day it completes.
        flag_day = day_of(ordered[RING_MINIMUM - 1], applications, days)
        ring_groups[group_index] = ordered
        reported_rings.add(group_index)
        record = daily[flag_day]
        record["suspected_ring_flags"] += 1
        record["applications_referred"] += len(ordered)
        record["flags"].append(
            {
                "type": "suspected_ring",
                "applications": sorted(fixture.application_ids[position] for position in ordered),
                "cluster_size": len(ordered),
                "shared_signals": ["address", "device"],
                "applications_to_flag": ordered[RING_MINIMUM - 1] - ordered[0],
                "signature": {"device": signals[0][:12], "address": signals[1][:12]},
            }
        )

    open_clusters = len(ring_groups)
    totals = {
        "applications": applications,
        "days": days,
        "duplicate_identity_flags": sum(day["duplicate_identity_flags"] for day in daily),
        "suspected_ring_flags": sum(day["suspected_ring_flags"] for day in daily),
        "applications_referred": sum(day["applications_referred"] for day in daily),
        "open_clusters_at_period_end": open_clusters,
        "median_daily_referrals": sorted(day["applications_referred"] for day in daily)[days // 2],
    }
    # Validation against the fixture's withheld truth. Reported so the operational numbers
    # above can be trusted, and labelled so they are never read as a BAF result.
    truth_rings = {ring for ring in fixture.ring_truth if ring is not None}
    flagged_rings: set[str] = set()
    false_groups = 0
    for positions in ring_groups.values():
        present = [fixture.ring_truth[position] for position in positions]
        present = [value for value in present if value is not None]
        if present and present.count(max(set(present), key=present.count)) >= RING_MINIMUM:
            flagged_rings.add(max(set(present), key=present.count))
        else:
            false_groups += 1
    validation = {
        "scope": "deterministic synthetic fixture only; no BAF row is linked or claimed",
        "truth_rings": len(truth_rings),
        "rings_touched_by_a_flag": len(flagged_rings & truth_rings),
        "false_ring_groups": false_groups,
        "ring_recall": len(flagged_rings & truth_rings) / len(truth_rings) if truth_rings else None,
        "duplicate_pair_precision": (
            len(reported_pairs & fixture.positive_pairs) / len(reported_pairs) if reported_pairs else None
        ),
        "duplicate_pair_recall": (
            len(reported_pairs & fixture.positive_pairs) / len(fixture.positive_pairs)
            if fixture.positive_pairs
            else None
        ),
    }
    return {
        "evidence_id": "m9-daily-suspect-report-v1",
        "evidence_source": "synthetic_link_fixture",
        "code_sha": code_sha(),
        "seed": SEED,
        "boundary": (
            "BAF has no cross-row identity or ring truth and no BAF application is linked, "
            "duplicated, or described as part of a ring anywhere in this report."
        ),
        "totals": totals,
        "validation": validation,
        "days": [
            {key: value for key, value in day.items() if key != "flags"} | {"flag_count": len(day["flags"])}
            for day in daily
        ],
        "latest_day_flags": daily[-1]["flags"][:50],
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def run_suspect_report(
    key: bytes, evidence_dir: Path, *, applications: int = 50_000, days: int = DEFAULT_DAYS
) -> dict[str, Any]:
    from .io import write_json

    fixture = generate_fixture(key, applications=applications)
    report = build_daily_report(fixture, days=days)
    write_json(evidence_dir / "daily_suspect_report.json", report)
    return report

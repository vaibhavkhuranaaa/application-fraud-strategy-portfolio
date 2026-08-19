from fraud_strategy.linking import evaluate_fixture, generate_fixture


def test_clean_fixture_resolves_entities_without_false_merges() -> None:
    fixture = generate_fixture(
        b"fixture-test-key-32-bytes-long!!",
        applications=3_000,
        rings=20,
        positive_pairs=100,
        corruption_rate=0,
        seed=17,
    )
    metrics = evaluate_fixture(fixture)
    assert metrics["pairwise"]["f1"] >= 0.99
    assert metrics["false_merge_rate"] == 0
    assert metrics["ring_flags"]["truth_rings"] == 20
    assert metrics["ring_flags"]["ring_recall"] == 1.0


def test_corruption_is_deterministic() -> None:
    first = generate_fixture(
        b"fixture-test-key-32-bytes-long!!",
        applications=3_000,
        rings=20,
        positive_pairs=100,
        corruption_rate=0.15,
        seed=17,
    )
    second = generate_fixture(
        b"fixture-test-key-32-bytes-long!!",
        applications=3_000,
        rings=20,
        positive_pairs=100,
        corruption_rate=0.15,
        seed=17,
    )
    assert first.application_ids == second.application_ids
    assert first.token_records == second.token_records

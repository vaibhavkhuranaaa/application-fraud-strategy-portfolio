# Decision 0001: Modernize the dashboard as a decision workflow

Date: 2026-08-17

## Decision

Keep the static, zero-cost dashboard and its approved committee-exhibit visual system. Add a same-capacity
scenario comparison, three scenario starting points, URL-backed scenario state, progressive disclosure for
operational evidence, a ten-row queue window, retrospective-result and rule filters, and per-case evidence
drill-down.

The governance result remains fixed at `no robust recommendation`. No scenario input can change it.

## Why

The previous surface carried strong evidence but behaved like a long report. It rendered all five exhibits
and sixty queue rows in one pass. A fraud strategy owner could change inputs, but had to infer the difference
against the incumbent score proxy and scan a large table to inspect one case.

The chosen workflow makes the decision consequence explicit and moves detail behind native controls without
changing the evidence, payload, hosting model, or publication boundaries.

## Alternatives rejected

- A React dashboard or chart library. Existing HTML, CSS, JavaScript, and SVG already cover the task with no dependency or runtime cost.
- A multi-page application shell. It would split a committee decision across routes and weaken the established exhibit form.
- Recomputing policies in the browser. The pinned 1,152-row lookup grid is faster and keeps the verified evidence immutable.
- Showing all queue rows by default. It creates length without improving the decision and performs poorly on a phone.

## Not done

- No promotion gate, model, threshold, evidence value, fairness acceptance, or source boundary changed.
- No automatic decline, group-specific threshold, identity claim, production-performance claim, or realised financial claim was added.
- No server, database connection, authentication surface, paid service, or third-party request was added.

## Verification

The browser gate checks 390, 768, 1280, 1440, and 1680 pixel widths. It reports zero horizontal page scroll,
zero contrast failures, zero unnamed controls, zero heading skips, zero positive tab indexes, zero interaction
failures, and zero state-pattern failures. The minimum measured contrast is 5.11:1. Stakeholder, technical,
and phone evidence is in `docs/screenshots/`. The complete reviewed payload is embedded in the HTML, and
the browser gate verifies the dashboard reaches ready state both over HTTP and when opened directly from
disk. A forced failure of both the embedded payload and JSON fallback still exposes the named retry state.

## Changed

The decision workspace, browser quality gate, paired screenshots, public documentation, and private
delivery records changed. The analytical evidence, promotion gates, model status, data boundaries, and
zero-cost hosting architecture did not.

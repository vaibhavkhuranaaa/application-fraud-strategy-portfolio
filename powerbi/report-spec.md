# Power BI report specification

Six pages, matching the bands of the static dashboard so a reader in Power BI and a reader on the
dashboard see the same evidence and the same decision. Field references use
`table[column]` for columns and `[Measure]` for measures from `measures.dax`.

Layout convention on every page, mirroring `DESIGN.md`'s four bands top to bottom:
decision → reasons → evidence → controls. Canvas 1280×720, 16px gutters, no card shadows, no
decorative shapes, no icons. Text: 12px caption, 14px body, 20px page title, 28px decision.

Every page carries a footer text box with:
`[Evidence period label] · Dataset [Dataset version] · Evidence revision [Evidence revision] · Local evidence only; no live lending decision.`

---

## Page 1 - Situation

| Visual | Type | Bindings | Required annotation |
| --- | --- | --- | --- |
| Decision | Card (large) | `[Decision headline]` | Rendered in the refusal colour. Never conditional on a filter. |
| Blocking reasons | Multi-row card / text | `[Refusal reasons]` | Heading: "Why this is the recorded position" |
| Champion | Card | `[Champion]` | Subtitle "retained baseline" |
| Challenger | Card | `[Challenger]` | Subtitle "rejected at promotion" |
| Fraud caught at 5% capacity | Card | `[Catch rate]` filtered to `fact_capacity[review_capacity] = 0.05` and champion | Subtitle shows `[Challenger catch rate]` for the same capacity |
| Gate summary | Card | `[Promotion summary]` | - |
| Promotion gates | Table | `fact_promotion_gate[gate_name]`, `[Gate result label]` | Sort failures first. Print PASS/FAIL as text, colour secondary. |

Page filter: `fact_promotion_gate[gate_family] = "Model promotion"`.

## Page 2 - Strategy

| Visual | Type | Bindings | Required annotation |
| --- | --- | --- | --- |
| Refusal banner | Text box | `[Decision headline]` | Repeated on this page; scenarios never override it |
| Frontier | Scatter | X `fact_strategy_policy[review_rate]`, Y `fact_strategy_policy[catch_rate]`, legend `fact_strategy_policy[rules_enabled]`, detail `fact_strategy_policy[policy_id]` | Title: "How much more fraud is caught for each extra application sent to review?" Frontier points filled, dominated points hollow. |
| Policy table | Table | `policy_id`, `catch_rate`, `false_positive_rate`, `overflow`, `assumption_grid_positive_share`, `[Policy frontier label]` | Caption states that every rule-enabled policy overflowed capacity |
| Scenario value | Column chart | Axis `fact_strategy_policy[policy_id]`, value `[Policy scenario value (assumption)]` | Title must contain "(assumption)". Subtitle: `[Assumption notice]` |
| Capacity slicer | Slicer | `fact_strategy_policy[review_capacity]` | Labelled "Manual-review capacity" |
| Rules slicer | Slicer | `fact_strategy_policy[rules_enabled]` | Labelled "Concentration rules forcing review" |

The three economic inputs are fixed in this report at the recorded reference assumptions
(exposure $12,500, review $17, friction $150). Interactive assumption entry lives in the
static dashboard; do not imply here that the reader can change them.

## Page 3 - Review operations

| Visual | Type | Bindings | Required annotation |
| --- | --- | --- | --- |
| Review demand | Card | `[Review demand]` | Subtitle `[Capacity feasibility]` |
| Beyond capacity | Card | `[Beyond capacity]` | "referred for governance, never declined" |
| Catch by capacity | Line + column | Axis `fact_capacity[review_capacity]`, line `[Catch rate]`, column `fact_capacity[queue_size]`, legend `dim_comparator[comparator_name]` | Title: "What does each level of reviewer capacity buy?" |
| Confidence | Table | `review_capacity`, `[Catch rate]`, `[Catch rate interval]`, `fact_capacity[precision]` | Every rate shows its 95% interval |
| Comparator slicer | Slicer | `dim_comparator[comparator_name]` | Default: champion and challenger only |

No page element may present an action as executed. If an action column is added it must be
titled "Simulated action - non-binding".

## Page 4 - Model comparison

| Visual | Type | Bindings | Required annotation |
| --- | --- | --- | --- |
| Ranking lift | Card | `[Ranking lift]` | Subtitle `[Ranking lift interval]` |
| Calibration intercept | Card | `[Calibration intercept]` | Subtitle `[Calibration intercept status]` |
| Comparator matrix | Matrix | Rows `fact_model_metric[metric_name]`, columns `dim_comparator[comparator_name]`, values `[Metric value]` | Title: "How did each comparator perform on the untouched month-7 period?" |
| Variant stress | Clustered bar | Axis `dim_evidence_source[evidence_source_name]`, value `[Metric value]` filtered to `metric_name = "pr_auc"` | Caption: frozen Base-trained model; variants were never used for training or tuning; not a production-performance claim |
| Gates | Table | `fact_promotion_gate[gate_name]`, `[Gate result label]` | Failures first |

## Page 5 - Fairness and drift

| Visual | Type | Bindings | Required annotation |
| --- | --- | --- | --- |
| Segments triggering review | Card | `[Segments triggering review]` | - |
| Segment detail | Table | `segment_name`, `group_name`, `applications`, `positive_labels`, `[Group catch rate]`, `[Group display note]` | Withheld groups show the note, never a zero |
| Drift summary | Card | `[Drift summary]` | - |
| Drift by feature | Stacked bar | Axis `fact_drift[feature_name]`, value `COUNTROWS` by `fact_drift[psi_status]` | Title: "Which inputs shifted enough to block automatic promotion?" Top 10 features by blocking count; the visual must state that it is a top-10 view. |
| Drift heat | Matrix | Rows `feature_name`, columns `fact_drift[month]`, values `[Max PSI]` | Conditional formatting must be accompanied by the numeric value in the cell |

Required text box: segment gaps are a governance trigger, not a legal fairness finding, and no
group-specific threshold is applied.

## Page 6 - Data quality and linking

| Visual | Type | Bindings | Required annotation |
| --- | --- | --- | --- |
| Source rows | Card | `[Source rows]` | "across `[Files verified]` checksum-verified files" |
| Curation table | Table | `file_name`, `rows`, `source_columns`, `curated_columns`, `prevalence`, `source_sha256` | Checksums shown in full or explicitly marked truncated |
| Linking gates | Table | `fact_promotion_gate[gate_name]`, `[Gate result label]` filtered to `gate_family = "Identity linking"` | - |
| Pair quality by corruption | Line | Axis `fact_linking_run[corruption]`, value `[Worst pairwise F1]` | Reference line at 0.80. Title: "How far can the matching signals degrade before pair quality fails its gate?" |
| Boundary notice | Text box | `[Linking boundary notice]` | Must be visible without scrolling |

---

## Accessibility requirements

- Every visual has a title that states the question it answers, and alt text that states the
  finding in words.
- Tab order set explicitly per page, following the four-band order.
- No meaning carried by colour alone: pass/fail and frontier/dominated print their word.
- Theme colours must match the tokens in `DESIGN.md` so the report and the dashboard agree.
- Check the report in Power BI's own accessibility checker before any screenshot is recorded.

## Page 5, Desk performance (added 2026-08-10)

Purpose: what the fraud desk did, period by period. This page answers operational questions and
authorises nothing; the governance pages carry the promotion decision.

- Header cards: `Applications`, `Fraud attempts`, `Fraud rate bps`, `Catch rate`, `Investigator yield`.
- Line, period on the axis: `Fraud rate bps` against `Catch rate` on a secondary axis. Subtitle must
  state that catch rate assumes review prevents the fraud it finds.
- Column, period on the axis, `fact_vendor_performance`: `Additional fraud caught`, with
  `Vendor boundary notice` as the subtitle.
- Table, `fact_monthly_kpi`: period, applications, fraud attempts, fraud rate bps, queue size, catch
  rate, catch rate change, investigator yield, capacity overshoot.
- Card: `Capacity overshoot notice`. It is a sentence, not a number, and explains why a tied score
  cannot cut on an exact headcount.
- Footer: `Operational boundary notice`.
- Slicers: period, model version. The model slicer must default to showing both, because the page is
  a comparison and a single-model view invites reading the challenger as if it were live.


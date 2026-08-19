# Data dictionary

Status: `profiled 2026-08-05 against the actually downloaded Bank Account Fraud (BAF) suite files`. Every number below was measured directly from the downloaded CSVs (`data/quarantine/`, git-ignored) with `pandas` and `wc`/`shasum`, not taken from the paper, the datasheet, or Kaggle's page copy. Column *definitions* (the prose describing what each field means) are quoted from the publisher's own datasheet (`documents/datasheet.pdf` in `github.com/feedzai/bank-account-fraud`, Q7), because a definition cannot be measured from data alone - the measured min/max/null-rate/cardinality columns are this project's own verification of those claims, and are reported even where they differ slightly from the datasheet's stated ranges (expected, since the datasheet's ranges are suite-wide and this profile is Base-file-specific).

## Source and provenance

- Dataset: Bank Account Fraud (BAF) suite, NeurIPS 2022 Datasets & Benchmarks track. Publisher: Feedzai.
- Kaggle source: `kaggle.com/datasets/sgpjesus/bank-account-fraud-dataset-neurips-2022`
- Downloaded: 2026-08-05 via Kaggle CLI (`kaggle datasets download -d sgpjesus/bank-account-fraud-dataset-neurips-2022`)
- Archive: `bank-account-fraud-dataset-neurips-2022.zip`, 558,054,164 bytes; the verified checksum is retained in the private approved data record
- Storage: `data/quarantine/` (git-ignored - see `.gitignore`; never committed)
- Licence: CC BY-NC-SA 4.0 per the human's 2026-08-05 determination stated in the README attribution record

## Archive contents (measured)

The archive contains six CSVs - a `Base` table with no artificially injected bias, and five `Variant` tables (I–V) that resample the same underlying generative model under different bias conditions (group-size disparity, prevalence disparity, and separability disparity, per the datasheet). All six were extracted and measured; **this dictionary profiles `Base.csv` in full detail**, since it is the intended primary table for this project. Variant schemas and target rates are also measured below for completeness.

| File | Bytes | Rows (excl. header) | Columns |
|---|---|---|---|
| `Base.csv` | 213,427,735 | 1,000,000 | 32 |
| `Variant I.csv` | 213,400,445 | 1,000,000 | 32 |
| `Variant II.csv` | 213,537,521 | 1,000,000 | 32 |
| `Variant III.csv` | 252,204,320 | 1,000,000 | 34 |
| `Variant IV.csv` | 213,538,370 | 1,000,000 | 32 |
| `Variant V.csv` | 252,214,315 | 1,000,000 | 34 |

Variant III and V carry two extra columns, `x1` and `x2`, not present in Base or the other variants. Per the datasheet (Q6, Q23), these are synthetic features sampled from group/label-conditioned multivariate normal distributions to inject *separability disparity* (a bias type for fairness testing) - they are **not** identity or contact fields and are out of scope for the identity-linking design below. Aggregate `fraud_bool` positive rate is materially the same across all six files at this whole-table level (1.1029%–1.1030%, measured) - the datasheet's stated inter-variant differences are subgroup-conditional (age-group prevalence and separability), not visible in the unconditioned aggregate rate.

Row/column counts and byte sizes above were directly measured on 2026-08-05, not estimated. Exact source
checksums remain in the private approved data record rather than the public documentation.

## Base.csv - full schema (measured against 1,000,000 rows)

`fraud_bool` (the target) confirmed present. Positive-class rate measured: **11,029 / 1,000,000 = 1.1029%**. Per the datasheet (Q8): *"A positive value (fraud_bool=1) represents a fraudulent bank account application. A negative value (fraud_bool=0) represents a legitimate bank account application."* This is application/account-opening fraud, not post-account transaction fraud or loan-repayment default - confirmed by the datasheet's framing throughout (Q4, Q40) and matches this project's "application/acquisition fraud" scope.

`month` confirmed present, integer-valued, measured range **0–7** (8 distinct months), no gaps. Per the datasheet (Q11): the recommended split is temporal - *"the first six months of data for training and the last two months for validation."* Measured per-month row counts (not uniform - declines from month 0 at 132,440 rows to month 7 at 96,843 rows):

| month | rows |
|---|---|
| 0 | 132,440 |
| 1 | 127,620 |
| 2 | 136,979 |
| 3 | 150,936 |
| 4 | 127,691 |
| 5 | 119,323 |
| 6 | 108,168 |
| 7 | 96,843 |

No null values (`NaN`) were measured in any column of Base.csv (0.00% for all 32 columns) - consistent with the datasheet's Q9 claim ("There is no missing information from individual instances"). **However**, several numeric fields use an explicit **`-1` sentinel** (documented by the publisher, not inferred) to mean "not applicable / unknown," which a naive null-check misses. Measured `-1` rates:

| Column | `-1` count | `-1` rate |
|---|---|---|
| `prev_address_months_count` | 712,920 | 71.29% |
| `bank_months_count` | 253,635 | 25.36% |
| `current_address_months_count` | 4,254 | 0.43% |
| `session_length_in_minutes` | 2,015 | 0.20% |
| `device_distinct_emails_8w` | 359 | 0.04% |

`intended_balcon_amount` is documented by the datasheet as using **negative values generally** (not a single `-1` sentinel) as its missing-value convention ("negatives are missing values"); measured range is **-15.53 to 112.96**, with 742,523 of 1,000,000 rows (74.25%) negative - i.e., most rows carry a "missing" intended balance under the publisher's own convention. This is a materially high effective-missingness field and should be flagged for any modeling milestone.

### Full column list (definitions quoted from the datasheet Q7; measurements are this project's own)

| Column | Type (measured) | Datasheet definition | Measured null/`-1` rate | Measured cardinality / range |
|---|---|---|---|---|
| `fraud_bool` | int64 (binary) | Target: 1 = fraudulent application, 0 = legitimate | 0.00% | 2 values; positive rate 1.1029% |
| `income` | float64 | Annual income of the applicant, decile form, [0.1, 0.9] | 0.00% | 9 distinct deciles, measured range [0.1, 0.9] |
| `name_email_similarity` | float64 | Similarity between email and applicant's name; higher = more similar, [0,1] | 0.00% | 998,861 distinct values; measured range [1.43e-06, 0.99999932] |
| `prev_address_months_count` | int64 | Months at previous registered address (-1 = missing) | 71.29% coded `-1` | 374 distinct values |
| `current_address_months_count` | int64 | Months at current registered address (-1 = missing) | 0.43% coded `-1` | 423 distinct values |
| `customer_age` | int64 | Applicant age, rounded to the decade, [10,90] | 0.00% | 9 values: {10,20,...,90} |
| `days_since_request` | float64 | Days since the application was made, [0,79] | 0.00% | 989,330 distinct values |
| `intended_balcon_amount` | float64 | Initial transferred amount for application (negative = missing, per publisher convention) | 74.25% negative | measured range [-15.53, 112.96] |
| `payment_type` | categorical (str) | Anonymized credit payment plan type, 5 possible values | 0.00% | 5 values: AA,AB,AC,AD,AE (measured counts: AB 370,554; AA 258,249; AC 252,071; AD 118,837; AE 289) |
| `zip_count_4w` | int64 | Applications in same zip code in last 4 weeks, [1,6830] | 0.00% | 6,306 distinct values; measured range [1, 6700] |
| `velocity_6h` | float64 | Avg. applications/hour over last 6h | 0.00% | 998,687 distinct values; measured range [-170.6, 16715.6] |
| `velocity_24h` | float64 | Avg. applications/hour over last 24h | 0.00% | 998,940 distinct values |
| `velocity_4w` | float64 | Avg. applications/hour over last 4 weeks | 0.00% | 998,318 distinct values |
| `bank_branch_count_8w` | int64 | Applications at the selected bank branch in last 8 weeks | 0.00% | 2,326 distinct values; measured range [0, 2385] |
| `date_of_birth_distinct_emails_4w` | int64 | Distinct emails among applicants sharing the same date of birth, last 4 weeks | 0.00% | 40 distinct values; measured range [0, 39] |
| `employment_status` | categorical (str) | Anonymized employment status, 7 possible values | 0.00% | 7 values: CA 730,252; CB 138,288; CF 44,034; CC 37,758; CD 26,522; CE 22,693; CG 453 |
| `credit_risk_score` | int64 | Internal application-risk score | 0.00% | 551 distinct values; measured range [-170, 389] |
| `email_is_free` | int64 (binary) | Free vs. paid email domain | 0.00% | 2 values (1: 529,886 / 0: 470,114) |
| `housing_status` | categorical (str) | Anonymized residential status, 7 possible values | 0.00% | 7 values: BC 372,143; BB 260,965; BA 169,675; BE 169,135; BD 26,161; BF 1,669; BG 252 |
| `phone_home_valid` | int64 (binary) | Validity of provided home phone | 0.00% | 2 values (0: 582,923 / 1: 417,077) |
| `phone_mobile_valid` | int64 (binary) | Validity of provided mobile phone | 0.00% | 2 values (1: 889,676 / 0: 110,324) |
| `bank_months_count` | int64 | Age of previous account, months (-1 = missing) | 25.36% coded `-1` | 33 distinct values |
| `has_other_cards` | int64 (binary) | Applicant has other cards from the same bank | 0.00% | 2 values (0: 777,012 / 1: 222,988) |
| `proposed_credit_limit` | float64 | Applicant's proposed credit limit, [200,2000] | 0.00% | 12 distinct values |
| `foreign_request` | int64 (binary) | Request origin country differs from bank's country | 0.00% | 2 values (0: 974,758 / 1: 25,242) |
| `source` | categorical (str) | Online application channel | 0.00% | 2 values: INTERNET 992,952; TELEAPP 7,048 |
| `session_length_in_minutes` | float64 | Banking-website session length, minutes (-1 = missing) | 0.20% coded `-1` | 994,887 distinct values |
| `device_os` | categorical (str) | OS of the requesting device | 0.00% | 5 values: other 342,728; linux 332,712; windows 263,506; macintosh 53,826; x11 7,228 |
| `keep_alive_session` | int64 (binary) | User's session-logout preference | 0.00% | 2 values (1: 576,947 / 0: 423,053) |
| `device_distinct_emails_8w` | int64 | Distinct emails seen from this device on the banking site in last 8 weeks (-1 = missing); note: datasheet's prose names this field `device_distinct_emails` but the shipped CSV column is `device_distinct_emails_8w` - recorded as measured, not corrected | 0.04% coded `-1` | 4 values: -1 (359), 0 (6,272), 1 (968,067), 2 (25,302) |
| `device_fraud_count` | int64 | Count of fraudulent applications previously made with this device | 0.00% | **Constant - 1 value (0) across all 1,000,000 Base rows.** Datasheet states its theoretical range is [0,1]; in the measured Base file it never takes the value 1, i.e. it carries zero information in this table. |
| `month` | int64 | Month the application was made, [0,7] | 0.00% | 8 values (0–7); see per-month table above |

## Confirmed target and temporal coverage

- Target field: `fraud_bool` - confirmed present, confirmed binary, confirmed application/account-opening fraud semantics per the publisher's own datasheet answer to Q8. Measured positive rate 1.1029% (highly imbalanced, as expected for fraud data).
- Temporal field: `month` - confirmed present, confirmed integer 0–7 (8 months), confirmed non-uniform monthly volume (96,843–150,936 rows/month), consistent with the publisher's own recommended temporal train/validation split (months 0–5 train, 6–7 validate). This supports a genuine time-based split for any future modeling milestone rather than a random split.

## Identity-linking field assessment (job-critical)

This project's target job function requires "daily identity-linking of incoming applications to flag suspected fraud rings." The candidate fields named in this task's brief were checked one by one against the **actual downloaded schema** (not assumed from the field-name list):

| Candidate field (as named in the task brief) | Present in Base.csv? | Actual column name | What linking signal it supports |
|---|---|---|---|
| `name_email_similarity` | Yes | `name_email_similarity` | A per-application scalar (email-vs-name text similarity). Usable as a **feature** in a fraud model, and weakly as a filter (very low similarity is suspicious), but it is a property of one application in isolation - it does not link one application to another. |
| `prev_address_months_count` | Yes | `prev_address_months_count` | Tenure-at-address value for one applicant. Could support **approximate matching** (two applications with identical/near-identical prior-address tenure, income decile, and age bucket are weakly more likely to share a real-world identity) but this is fuzzy statistical similarity, not a join key. |
| `current_address_months_count` | Yes | `current_address_months_count` | Same category as above - a tenure value, usable only for approximate/statistical similarity matching, not exact linking. |
| `device_fraud_count` | Yes, but **constant (always 0) in Base.csv** | `device_fraud_count` | As measured, this field carries **zero variance and zero information** in the Base table - every one of the 1,000,000 rows is 0. It cannot support ring detection in this file as downloaded. (The datasheet's stated theoretical range is [0,1]; it is possible non-zero values appear in other variants or were designed to activate under different sampling, but that was not the case in Base as measured.) |
| `device_os` | Yes | `device_os` | A 5-value categorical (windows/linux/macintosh/x11/other) attached to each application. Because it has only 5 possible values shared across ~1,000,000 rows, grouping by it alone produces enormous, meaningless clusters - not a usable device fingerprint or linking key on its own. |
| `email_is_free` | Yes | `email_is_free` | Binary flag, same limitation as `device_os` - far too low-cardinality to link individual applications to each other; it is a model feature, not a linking key. |
| `phone_home_valid` / `phone_mobile_valid` | Yes | `phone_home_valid`, `phone_mobile_valid` | Binary validity flags with no phone *value* attached (no digits, no hash, no partial match). They tell you whether a phone was valid, never which phone - not usable for entity linking. |
| `bank_branch_count_8w` | Yes | `bank_branch_count_8w` | An **already-aggregated count** ("how many applications hit this branch in the last 8 weeks") rather than a branch identifier - you get the count, not the branch ID, so you cannot recover which specific other applications shared that branch. |
| `date_of_birth_distinct_emails_4w` | Yes | `date_of_birth_distinct_emails_4w` | Same pattern: an **already-aggregated count** ("how many distinct emails shared this date of birth in the last 4 weeks"), not a shared key you can join on. You know the count is elevated but not which rows contributed to it. |
| `device_distinct_emails*` | Yes | `device_distinct_emails_8w` (datasheet prose calls it `device_distinct_emails`; the shipped column is suffixed `_8w`) | Same aggregation pattern - a count (0–2, or -1 missing) of distinct emails seen on a device, not the device ID or the emails themselves. |

### What IS achievable for identity-linking with this dataset, stated plainly

- **Rule-based and statistical risk features derived from the aggregates.** `bank_branch_count_8w`, `date_of_birth_distinct_emails_4w`, `zip_count_4w`, `velocity_6h/24h/4w`, and `device_distinct_emails_8w` are all pre-computed "how concentrated is activity around this attribute" signals. They are legitimate, valuable **model features** for fraud scoring (a high `date_of_birth_distinct_emails_4w` is a real ring-adjacent signal), and can drive **threshold-based review rules** ("route to manual review if `bank_branch_count_8w` exceeds X and `fraud_bool`-model score exceeds Y").
- **Approximate/statistical similarity clustering.** It is possible to group applications by shared low-cardinality attribute combinations (e.g., same `customer_age` decade, same `income` decile, same `payment_type`, same `device_os`, similar `name_email_similarity`) and flag unusually dense clusters as ring-suspicious. This is a legitimate, if noisy, analytic technique.

### What is NOT achievable, and why - stated plainly per the task's honesty guardrail

- **Classic blocking-and-graph entity resolution is not directly possible with this dataset.** Entity resolution normally requires a raw joinable identifier - an email address string, a phone number, a device fingerprint/ID, a name, an SSN, a physical address string - that appears verbatim (or near-verbatim, e.g. via fuzzy string blocking) on two or more records, so a graph edge can be drawn between the specific rows that share it. **BAF contains none of these.** Every field that touches identity has already been converted into either (a) an anonymized/label-encoded categorical bucket (`payment_type`, `employment_status`, `housing_status`, `device_os` - all use opaque codes like `AA`/`CA`/`BC`, not real category names), or (b) a pre-aggregated numeric count/similarity score computed *before* the row was included in this table (`bank_branch_count_8w`, `date_of_birth_distinct_emails_4w`, `zip_count_4w`, `device_distinct_emails_8w`, `name_email_similarity`). There is no branch ID, zip code, device ID, email string, or phone number in the shipped schema to draw an edge between two specific rows.
- **The dataset's own documentation confirms this is by design, not an oversight.** The datasheet (Q10) states verbatim: *"There are no relationships between individual instances... Each individual instance was generated using a CTGAN independently of each other, and each instance represents features to detect fraud, with no links to other instances."* Rows in BAF are **independently sampled from a generative model**, not simulated as a connected population of applicants who might plausibly be the same person or a coordinated ring reapplying. There is, by the publisher's own account, no ground-truth ring structure baked into the data to detect or evaluate against - a stronger and more specific constraint than "the identifiers are anonymized." Any "fraud ring" found by clustering BAF rows would be a statistical artifact of the CTGAN's learned feature correlations, not a recovered real-world connection, and there is no labeled ring ground truth to validate a ring-detection method's precision/recall against.
- **Practical consequence for this project's M2+ design.** A literal blocking-and-graph identity-resolution module (the kind built on raw email/phone/device-ID joins, as the OneMain job description implies) cannot be built or demonstrated on BAF as downloaded. What *can* be honestly built and demonstrated is: (a) an aggregate-feature-driven fraud risk score that uses the concentration/velocity signals above as inputs, and (b) an approximate-similarity clustering exploration over the anonymized categorical/numeric fields, clearly labeled as a proxy demonstration of the *technique* rather than a dataset with recoverable real identity links. This distinction must be stated plainly in any M2+ architecture or evaluation document and in the eventual case study - overstating BAF as supporting "real" entity-resolution/graph fraud-ring detection would misrepresent what the data can do.

## Other variants (I–V) - noted, not fully profiled here

Variants I, II, and IV share Base's 32-column schema; Variants III and V add `x1`/`x2` (bias-injection features, not identity fields - see above). All six files were extracted, checksummed, and row/column-counted (see the archive contents table). Full column-by-column profiling (null rates, cardinality) was performed only for `Base.csv`, since it is the intended primary table for this project's later milestones; the variants exist to let a later fairness-evaluation milestone test performance under different induced bias conditions (group-size disparity, prevalence disparity, separability disparity), per the datasheet's stated purpose.

## M2 feature eligibility contract

This table is immutable during M3 tuning. Any change requires evaluation approval and a new evidence record before rerunning experiments.

| Field / group | M3 role | Decision |
| --- | --- | --- |
| `fraud_bool` | Target only | Never an input, reason code, rule, or deployed request field. |
| `month` | Temporal split and drift audit only | Never an input. Use rolling-origin folds, month 6 calibration, month 7 untouched test. |
| `customer_age` | Fairness audit only | Excluded from every model and policy rule. May segment evaluation when the positive-count gate is met. |
| `x1`, `x2` in Variants III/V | Variant audit only | Excluded from models. Used only to explain injected separability stress. |
| `device_fraud_count` | Excluded | Constant zero in Base; no information and no linking value. |
| `days_since_request` | Excluded | Not available at the initial origination decision point; treating it as input would violate the product timing contract. |
| `credit_risk_score` | Incumbent proxy and optional hybrid input | Score alone as the incumbent comparator; excluded from the internal-only logistic/CatBoost models; permitted only in the separately named hybrid challenger. Never call it a verified vendor product. |
| `prev_address_months_count`, `current_address_months_count`, `bank_months_count`, `session_length_in_minutes`, `device_distinct_emails_8w` | Eligible after normalization | Convert documented `-1` to null and add a missing indicator; preserve raw values in lineage, not model input. |
| `intended_balcon_amount` | Eligible after normalization | Convert all negative values to null and add a missing indicator; report the 74.25% effective missingness as a stability risk. |
| `name_email_similarity`, `zip_count_4w`, `velocity_6h`, `velocity_24h`, `velocity_4w`, `bank_branch_count_8w`, `date_of_birth_distinct_emails_4w`, `device_distinct_emails_8w` | Eligible score/rule inputs | Precomputed concentration/similarity evidence only. Never use them to draw a BAF graph edge or claim recovered identities. |
| `income`, address-tenure fields, anonymized payment/employment/housing codes, email/phone validity flags, `has_other_cards`, `proposed_credit_limit`, `foreign_request`, `source`, `session_length_in_minutes`, `device_os`, `keep_alive_session` | Eligible predecision inputs | May enter internal and hybrid models after contract validation; categorical values retain publisher codes and plain-language limitations. |

### Generated identifiers and evidence source

- `application_id`: deterministic cryptographic hash of dataset version, source file name, and zero-based source row. It identifies a row, not an applicant or person.
- `evidence_source`: one of `baf_base`, `baf_variant_i` through `baf_variant_v`, or `synthetic_link_fixture`; mandatory in curated rows, scores, link flags, strategy outputs, API objects, and visible product evidence.
- `dataset_version`: acquisition date plus source archive SHA-256. It prevents silent mixing of files or reruns.

### Synthetic linking fixture boundary

The fixture adds HMAC-tokenized email, phone, device, and address-like signals solely to generated demonstration applications. `entity_id` and `ring_id` are held in evaluation-only storage and never supplied to matching code. The fixture must not be described as BAF enrichment, observed PII, real customer data, or production fraud-ring evidence.

## M3 curated additions

Every curated BAF row adds:

| Field | Type | Meaning / restriction |
| --- | --- | --- |
| `application_id` | 32-character hexadecimal string | Stable hash of dataset version, file, and row number; a row ID, never an identity. |
| `dataset_version` | string | `baf-2026-08-05-fb8d6d8b96f9`; prevents silent source mixing. |
| `evidence_source` | controlled string | `baf_base` or the exact BAF variant label; mandatory on downstream evidence. |
| `<field>__missing` | int8 binary | One indicator for each of the five documented `-1` fields plus negative `intended_balcon_amount`. |

All six curated schemas, rows, source/curated hashes, target counts, month coverage, missing-indicator names, storage paths, and elapsed durations are recorded in `evaluation/data_curation.json`. The Parquet files themselves remain git-ignored.

# Product design contract

Status: `replacement world committed 2026-08-09 and screenshot-approved 2026-08-10; risk-control extension verified and publication-approved 2026-08-18`

## Direction contract

**THESIS.** This surface is a committee exhibit, not a console. It opens the way a decision memo opens - the recommendation first, the numbers that justify it beneath, the limitations stated rather than
buried. It refuses the category default: the dark-sidebar analytics console with four rounded KPI tiles,
icon chips, delta arrows and a donut, and equally refuses its predictable opposite, the monospace
terminal.

**OWN-WORLD.** Paper-white ground, ink-black text, hairline rules doing all the separating work - no
cards, no shadows, no rounded containers. One deep indigo accent for selection and the primary data
series. Status red, amber and green kept desaturated to a print register and reserved strictly for
pass/fail meaning. Tabular figures throughout, ruled measure rows on a shared baseline, exhibits
numbered because a committee refers to them by number.

**STORY.** A fraud strategy owner reads the recommendation and the two failed checks in ten seconds,
sees that fraud pressure rose 69% across the period while volume fell, tests what a different review
capacity would buy, and leaves able to defend a refusal in a governance meeting.

**FIRST VIEWPORT.** Masthead rule with period and data nature. Then the decision block at 40px: the
status verdict, one sentence of consequence, the check tally, and the controlled temporary disposition.
Then the eight headline measures in a ruled band, no tiles. The scenario controls sit below the measures
they drive, not above them.

**FORM.** Statistical-exhibit tradition from bank annual reports and credit-committee packs, crossed
with the decision-memo opening. Derived from the audience's own documents rather than from dashboard
convention. The concept-seed script returned an empty roll in this environment, so the direction is
authored rather than dealt, and that is disclosed.

## Product context

- **Primary audience: non-technical.** A fraud strategy owner at a consumer lender. Reads outcomes,
  staffing and money. Never shown PR-AUC, calibration intercept, or PSI on the main surface.
- **Decision supported:** adopt or refuse one bounded screening strategy for governance review. The
  product never issues a lending decision.
- **Current verified answer is a refusal.** It leads, and no control can overturn it.

## Structure

One decision workspace carries the stakeholder story. The decision, scenario comparison, and two primary
exhibits stay visible. Operational evidence and technical evidence use separate native disclosures.

| Band | Content |
|---|---|
| Masthead | Product, period, applications assessed, data nature |
| Decision | Verdict, consequence sentence, check tally, the failed checks and what each means |
| Risk disposition | Temporary baseline status, permitted use, and evidence required to reopen |
| Control register | Native disclosure with seven owners, triggers, responses, and evidence gaps |
| Measures | Eight headline figures in a ruled band, assumption-derived ones marked |
| Scenario | Three starting points, approach, review capacity, concentration rules, three economic assumptions, same-capacity comparison |
| Exhibit 1 | Fraud pressure over time - volume bars, rate line, eight months |
| Exhibit 2 | What each review level buys - capture against workload, selected point marked |
| Operational evidence | Native disclosure containing Exhibits 3 to 5 |
| Exhibit 3 | Where applications go, from assessed to confirmed fraud |
| Exhibit 4 | Fraud rate by customer group, with withheld groups shown as withheld |
| Queue | Ten sampled cases at a time, retrospective-result and rule filters, plus case evidence drill-down |
| Analyst detail | Comparators, calibration, stability, variants, matching, provenance |
| Colophon | Limitations, licence, non-binding statement |

## Vocabulary

Industry terms lead; a plain reading sits beneath each.

| On screen | Means |
|---|---|
| Fraud capture rate | Share of fraud attempts routed to review |
| Leakage | Fraud attempts that reached approval unchecked |
| Insult rate | Good customers held up by a review |
| Investigator hit rate | Confirmed fraud per 100 cases worked |
| Alert-to-fraud ratio | Cases worked per fraud found |
| Referral volume | Cases pushed beyond capacity to governance |
| Capacity utilisation | Review demand against the team's ceiling |
| Value protected | Exposure avoided, from analyst assumptions only |

## Visual system

**Colour.** Restrained. `--paper #FFFFFF`, `--ground #F4F6F8`, `--ink #16181D`, `--ink-muted #5A616B`,
`--rule #D8DCE2`, `--accent #2B3A67`, `--pass #1E5E3F`, `--warn #8A6100`, `--fail #9B2C22`. Light only:
the use scene is a daytime office and a meeting-room projector, and the surface is meant to survive
being printed.

**Type.** One system sans. Fixed rem scale at a 1.2 ratio: 11px label, 13px body, 15px lead, 20px
section, 40px verdict. `font-variant-numeric: tabular-nums` everywhere a figure appears. Numbers right
aligned, labels left aligned, one baseline across each measure row.

**Space.** 8px base. Hairline rules and space separate content. Maximum content width 1200px.

**Charts.** Hand-authored inline SVG, no chart library, so nothing arrives with a vendor's defaults. Data bars are SVG rects rather than styled elements, which keeps the page free of inline style attributes and lets the content-security policy stay strict.
Every exhibit states the question it answers, carries units and a source line, and provides its finding
in words for assistive technology.

## Non-negotiable content rules

- Observed evidence and analyst assumptions are visually and verbally distinct. Assumption-derived
  figures carry the `◇` mark and the word assumption.
- Pass and fail print their word, never colour alone.
- Groups under 200 fraud cases render as withheld, never as zero.
- No identity or ring claim about the source data anywhere.
- No figure presented as realised profit, loss or saving.
- Simulated actions are labelled as simulated wherever they appear.

## Copy rules

No em dashes anywhere in the product. Sentences end and restart instead. No marketing register, no
hedging, no phrase that exists to sound balanced rather than to say something. Industry terms lead and a
plain reading follows. Model names stay in the analyst section: the main surface names approaches by what
they are, such as "Proposed approach" and "Incumbent score proxy".

## Refused

Cards as page structure. Icon-plus-heading tiles. Delta chips and trend arrows. Donut charts. Gradient
text. Glass. Coloured left borders. Sparklines standing in for content. Monospace as a costume.
Uppercase eyebrows over every section. Decorative motion.

## Quality gate

Measured by `scripts/ux_check.py` across four viewport widths.

- [x] No horizontal page scroll at 390, 768, 1280, 1440, 1680px
- [x] WCAG AA contrast on every text node
- [x] One `h1`, no heading-level skips, real table headers
- [x] Keyboard operable, visible focus, no positive `tabindex`
- [x] Every chart carries a text finding
- [x] Loading, empty, and error recovery states are named and keyboard operable
- [x] Scenario comparison, queue filters, URL state, and case drill-down pass browser interaction checks
- [x] Human approves the risk-control stakeholder and technical screenshots before publication

Results in `evaluation/ux_evaluation.json`; screenshots in `docs/screenshots/`.

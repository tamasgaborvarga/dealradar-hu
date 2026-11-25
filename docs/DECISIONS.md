# DealRadar HU — Architecture Decision Records

Format: **ID · title · status** — Context · Decision · Rationale · Consequences.
Status: `ACCEPTED` (follows from a stated requirement or accepted review), `PROPOSED` (architect's
recommendation, user may veto), `OPEN` (needs user input — see table at the end),
`SUPERSEDED by ADR-x`. Revised 2026-11-24 after the architecture review (`docs/REVIEW_2026-11-24.md`).

---

### ADR-001 · Modular monolith, single SQLite database, no daemon — ACCEPTED
**Context:** one user, one Windows PC, zero recurring cost. **Decision:** one Python package with
package boundaries, one SQLite file, CLI + Streamlit as the only entry points.
**Rationale:** microservices, queues or a server DB add operational cost with no benefit for a single
local user. **Consequences:** single writer (ADR-018); migration to PostgreSQL stays possible via SQLAlchemy.

### ADR-002 · Two engines, two result tables, never a combined score — ACCEPTED (revised)
**Context:** v0.1 used one `evaluations` table with an `engine` column and nullable columns for both.
**Decision:** `personal_evaluations` and `resale_evaluations` as separate tables with separate verdict
enums; engines live in separate packages that may not import each other; no view, function or sort
order combines them. **Rationale:** a shared wide table invites "just add a total score" and lets a
query accidentally mix verdict vocabularies; the schema should make the forbidden thing hard.
**Consequences:** some symmetric code in services/UI; accepted.

### ADR-003 · Deterministic pure-function engines; AI is advisory only — ACCEPTED
**Decision:** engines take immutable inputs and return results, no I/O. AI output is stored in
`ai_responses` and can only become data through an explicit, audited user action (accepting a match
candidate or confirming attributes). **Rationale:** reproducible, testable verdicts; AI cannot
override financial or safety rules.

### ADR-004 · Alembic migrations, explicit upgrade, backup first — ACCEPTED
**Decision:** schema changes only via reviewed Alembic migrations; `dealradar db upgrade` is explicit;
automatic backup before upgrade; app refuses to start on schema mismatch.
**Rationale:** requirement "never silently change the schema". Alembic is free and the standard
companion of SQLAlchemy. **Consequences:** one extra dependency.

### ADR-005 · Uncertainty → MANUAL_REVIEW, enforced in code and DB — ACCEPTED (revised)
**Decision:** rules declare required inputs; missing input or review flag short-circuits to
`MANUAL_REVIEW`. DB CHECK: `MANUAL_REVIEW` ⇔ non-empty `missing_inputs_json`/`review_flags_json`.
Unverified fee/tax profile is a review flag. **Rationale:** requirement; the CHECK prevents a verdict
of MANUAL_REVIEW without an explanation and vice versa.

### ADR-006 · Completed sales and asking prices in different tables — ACCEPTED (revised)
**Context:** v0.1 stored `ASKING_PRICE` and `DELISTED_LISTING` rows in the same `market_sales`
table as completed sales, separated only by an enum — exactly the confusion the requirements forbid.
**Decision:** `observed_sales` holds only completed sales (platform-shown final price or user-reported);
the user's own sales come from the ledger via the view `v_completed_sales`; asking prices exist only in
price observations of `CLASSIFIED`/`AUCTION` offers (ADR-039). `ResaleInputs` types completed sales separately from
display-only asking prices. **Rationale:** a filter bug can no longer turn an asking price into a
sale price. **Consequences:** the resale engine returns MANUAL_REVIEW often until evidence exists — intended.

### ADR-007 · Money as integer HUF, basis points, centi-HUF unit prices — ACCEPTED
**Decision:** `INTEGER` HUF gross, `INTEGER` bp, `INTEGER` centi-HUF per canonical unit; `Decimal`
arithmetic with a single rounding policy in `core/money.py`; floats banned in money modules (AST test).
**Rationale:** exact comparisons, no float drift. v0.1 assumed a ruff rule could ban `float(` —
not verified, so a project-owned AST test is used instead (no tooling assumption).

### ADR-008 · Source access policy — ACCEPTED
**Decision:** a source is enabled only with recorded robots.txt check and ToS note (DB CHECK);
blocked → `BLOCKED`, stop; no proxies, login, CAPTCHA solving, fingerprint spoofing; honest UA;
manual import always available; Playwright only for permitted JS-only sources.
**Rationale:** requirement; legal risk; stability.

### ADR-009 · Scheduling via Windows Task Scheduler, optional — PROPOSED
**Decision:** no in-process scheduler; optional OS scheduled task runs `dealradar collect --due`.
**Rationale:** zero dependencies; the app need not be open. **Consequences:** gaps when PC is off (ADR-016 handles them).

### ADR-010 · Build order: core → manual vertical slice for all categories → engines → first source — PROPOSED
**Rationale:** risk-first; manual entry gives all four categories coverage early, so "equal importance"
is not delayed by scraper availability. Automated sources come per category when a permitted one exists.

### ADR-011 · Claude Pro workflow without API; CLI mode sandboxed — PROPOSED (revised)
**Context:** v0.1 proposed letting an interactive Claude Code session process request files. Claude Code
can run shell commands and edit files; feeding it untrusted listing text is a prompt-injection path
onto the user's PC. **Decision:** default modes CLIPBOARD and FILE with answers pasted back
(claude.ai chat has no access to the PC). Optional CLI mode runs `claude -p` with `--tools ""`,
`--strict-mcp-config` (no MCP servers), empty temp working dir, stdin prompt, `--json-schema`, timeout,
one click per request. Interactive Claude Code must not process `ai_exchange` files.
**Rationale:** no API billing, manual initiation, and no tool access for content from the internet.
**Consequences:** analysis capacity bounded by Pro usage limits → one offer per request, user-prioritised queue.

### ADR-012 · Category modules own attributes, identity, rules and benchmark policy — ACCEPTED (revised)
**Decision:** `CategoryModule` protocol incl. `resolve_variant`, `comparison_basis`, `benchmark_policy`;
modules may not import each other; shared code may not branch on category (architecture test).
**Rationale:** v0.1 put variant handling in a single `variant_key` string on products and left unit-price
and size logic implicit in shared code — the place where category logic leaks.

### ADR-013 · (SUPERSEDED by ADR-016) Store observations on change + weekly heartbeat
v0.1 decision. Problem: medians over change-rows are biased toward volatile periods, and "heartbeat"
rows still mixed checks with changes. Replaced by price spans.

### ADR-014 · Two-level product identity: product + variant; listing 1:N offers — ACCEPTED
**Context:** v0.1 linked one listing to one product. A shop page for a sneaker carries many sizes with
different stock and sometimes different prices; a food page may offer several pack sizes; a laptop
model name covers several configurations. **Decision:** `products` (model/style) → `product_variants`
(comparable unit) → `variant_identifiers` (multiple GTIN/MPN per variant). `listings` (page/ad) → `offers`
(listing × variant) → `price_observations` (ADR-039). Matching assigns listing → product; the category module resolves
offer → variant. **Rationale:** prices are only comparable at variant level; product-level roll-ups
are category policy. **Consequences:** one more join; correct comparisons.

### ADR-015 · Conservative automatic product creation and merge support — ACCEPTED
**Decision:** the system creates products automatically only from offers with a valid identifier;
everything else stays UNMATCHED for the user. Duplicates are fixed with `merged_into_id` + audit.
**Rationale:** auto-creating products from titles causes product explosion and false benchmarks.

### ADR-016 · (SUPERSEDED by ADR-039) Price spans with known intervals
**Decision:** `price_spans(first_seen_at, last_confirmed_at, closed_at)`; only `last_confirmed_at` of the
open span is updated. Gaps between spans are unknown and excluded from statistics. Medians are
time-weighted over known time. **Rationale:** compact (row per change), statistically correct, makes
local-first gaps explicit. **Consequences:** one narrowly-scoped mutable column in an otherwise
append-only table — accepted and documented as mutability class `SPAN`.

### ADR-017 · (partly SUPERSEDED by ADR-040) Benchmarks are a cache; evaluations snapshot inputs
**Decision:** one current benchmark row per (variant, basis); evaluations store used values in
`inputs_json` + `inputs_hash`; re-evaluate only when the hash changes; "current" = latest id (no
`is_current` flag). **Rationale:** v0.1 kept benchmark history *and* FKs to it, plus an `is_current`
flag on an "append-only" table — redundant and contradictory. **Consequences:** smaller DB; full reproducibility.

### ADR-018 · Single-writer lock — ACCEPTED
**Decision:** all writers take `data/dealradar.lock`; SQLite WAL for concurrent reads.
**Rationale:** Task Scheduler run + Streamlit action could otherwise write concurrently; SQLite
`busy_timeout` alone yields intermittent "database is locked" errors in long transactions.

### ADR-019 · Ledger with positive amounts + direction; derived cost basis; acquisitions — ACCEPTED
**Decision:** `transactions` insert-only, `amount_huf > 0` + `direction`, CHECK type↔direction;
`acquisitions` group multi-unit orders; one `inventory_items` row per physical unit; cost basis is a
view with deterministic allocation. Own completed sales are read from the ledger, not copied.
**Rationale:** v0.1 stored cost basis on the item (duplicate of the ledger), used signed amounts
(sign-convention bugs) and could not represent one order containing several units.

### ADR-020 · Local Streamlit hardening and data minimization — ACCEPTED
**Decision:** `.streamlit/config.toml` with `server.address="127.0.0.1"`, `browser.gatherUsageStats=false`,
headless, XSRF on; private sellers only as salted hash; no contact data stored; raw-file retention per source.
**Rationale:** the UI must not be reachable from the LAN and must not send telemetry; classifieds pages
contain personal data that the app does not need.

### ADR-021 · Listing kinds and benchmark bases — ACCEPTED
**Decision:** `listing_kind ∈ {RETAIL, MARKETPLACE, CLASSIFIED, AUCTION, FLYER}`; benchmark bases
`RETAIL_NEW`, `USED_ASK` (context only), `FLYER`. Loyalty-only and multi-buy prices are flagged, not
mixed into `RETAIL_NEW` unless the category policy says so. Net-priced (B2B) listings normalized to gross;
VAT unknown → MANUAL_REVIEW. **Rationale:** v0.1 mixed new retail prices, marketplace prices and
private asks in one benchmark, which makes "% below median" meaningless.

### ADR-022 · Rule logic in code, rule parameters as versioned data — ACCEPTED
**Decision:** thresholds in `rule_params` (insert-only, hashed); logic versioned by git and recorded as
`code_version` on every evaluation. **Rationale:** v0.1 `rulesets` table was ambiguous about whether
logic or parameters lived in the DB.

### ADR-023 · No new external services; free data only — ACCEPTED
**Decision:** FX from MNB official rates (reviewed as a source) or user entry; fuzzy matching with stdlib
`difflib`; notifications in-app (external channel only if chosen in OPEN-4 and free). No API keys required.
**Rationale:** "no hidden recurring costs". Review found none in v0.1 besides an open notification choice.

### ADR-024 · Accepted match = candidate with status ACCEPTED (no pointer on listings) — ACCEPTED
**Context:** v0.2 had `listings.accepted_match_id` → circular FK listings ↔ match_candidates and a
duplicate of the candidate's status. **Decision:** partial unique index "one ACCEPTED candidate per
listing"; `listings.match_status` + `product_id` with CHECK `MATCHED ⇔ product_id`.
**Rationale:** one source of truth, no FK cycle (SQLite cannot add FKs later without table rebuild).

### ADR-025 · Mutability enforced at ORM level + CHECKs; read/write sessions — ACCEPTED
**Decision:** `__mutability__` / `__mutable_columns__` on models, guarded by SQLAlchemy events;
`read_session()` refuses flushes, `write_session()` holds the writer lock. **Rationale:** cheap,
tested, no extra dependency. **Known gap:** raw SQL bypasses the guards; SQLite triggers may be added
later in a migration.

### ADR-026 · Streamlit pages as files in `ui/page_scripts/`, never `ui/pages/` — ACCEPTED
**Context:** found in the browser smoke test: a folder named `pages/` next to the main script makes
Streamlit switch to legacy file-based navigation, overriding `st.navigation` (wrong titles, broken
pages). Callable pages could not be addressed by the headless test runner. **Decision:** thin page
scripts in `ui/page_scripts/`; regression test asserts `ui/pages/` does not exist.

### ADR-027 · Security flags passed explicitly by `dealradar ui` — ACCEPTED
**Context:** Streamlit reads `.streamlit/config.toml` only from the current working directory.
**Decision:** the CLI passes `--server.address=127.0.0.1`, `--browser.gatherUsageStats=false`,
headless, XSRF, `--client.toolbarMode=viewer` (hides the Deploy button that links to an external
hosting service) and pins `DEALRADAR_DATA_DIR` to an absolute path. The health check reads the live
options inside the UI and the committed file from the CLI.

### ADR-028 · UI language English for now — PROPOSED (OPEN-10 still open)
Strings are few and kept in the view modules; switching to Hungarian later is cheap.

### ADR-029 · Category module contract; three attribute levels — ACCEPTED (implemented)
**Context:** four categories with different attributes, identity and validation must share one
database and one pipeline. **Decision:** each category implements `CategoryModule`
(`categories/base.py`): normalize, validate, matching rules, evaluation inputs, and three Pydantic
schemas - product level (typed table), variant level (`variant_attrs` JSON), listing level
(`listings.category_attrs` JSON). Generic layers (`normalize`, `matching`, `evaluation`) know no
category; the cascade receives the category's rules as a parameter. **Rationale:** category logic
stays in one place per category; shared code has no `if category ==` (architecture test).
**Consequences:** adding a category = a new module + attribute table + migration.

### ADR-030 · Manufacturer-scoped MPN / style codes — ACCEPTED
**Decision:** MPN and style-code identifiers are stored as `<brand_key>|<CODE>`. Without a known
brand the code stays unscoped and can never auto-match. **Rationale:** part numbers are unique per
manufacturer, not globally; a global unique index on bare codes would either collide or merge
different products.

### ADR-031 · Restricted-circulation barcodes are not identifiers — ACCEPTED
**Decision:** GTINs with GS1 restricted prefixes (EAN-13 020-029 and 200-299, EAN-8 starting 0/2:
in-store and variable-weight codes) are dropped as identifiers with a warning. All GTINs are
check-digit validated and stored zero-padded to 14 digits (UPC-A == EAN-13 with leading 0).
**Rationale:** the same in-store code means different products in different shops.

### ADR-032 · `Condition.USED` = used, grade not stated — ACCEPTED
**Decision:** new enum value (migration 0002). "Használt" maps to USED; only explicit wording
("újszerű", "like new") maps to a grade. **Rationale:** mapping "used" to a grade would be a guess.

### ADR-033 · Identifier scope: does an identifier pin the variant? — ACCEPTED
**Context:** found by the apparel tests: a sneaker style code covers every size, so treating every
identifier hit as "this exact variant" matched EU43 listings to the EU42 variant. **Decision:**
`identifier_pins_variant(id_type)` per category (apparel style code: no; EAN/MPN: yes). Non-pinning
hits resolve the variant from the listing's variant key; unknown variants are reported.

### ADR-034 · Same-name-but-contradicting candidates stay visible — ACCEPTED
**Decision:** a rule-key hit whose specs contradict the listing is returned as REVIEW with
confidence 40 and the contradiction as reason, not dropped. **Rationale:** it is usually a data
error or a near-duplicate product; hiding it would let a duplicate product be created silently.

### ADR-035 · No "retail means new" assumption — ACCEPTED
**Decision:** normalization never assumes a condition. Retail listings without condition text keep
`condition=None` (evaluation input `condition` missing). A collector may pass a condition only from
recorded source-level knowledge (e.g. "this shop sells new items only", noted in the source's access
review). Food is exempt: condition is not an input there.

### ADR-036 · Unparsable or ambiguous values become issues, never guesses — ACCEPTED
**Decision:** parsers raise on ambiguity ("1,299", "03/04/27", bare shoe size "9", two pack sizes
in a title, conditional free shipping, net price without VAT, title/spec conflicts); normalization
turns that into `ERROR` (blocks automatic decisions, product creation) or `WARNING` issues.
Inferences that are near-certain are allowed but always flagged: bare sizes 30-50 read as EU
(`size_system_inferred`), unlabeled `A x B x C` dimensions read as W x H x D
(`dimension_order_assumed`), appliance model numbers used as MPN.

### ADR-037 · Freight classification thresholds — PROPOSED
**Decision:** HOME items >= 30 kg or with a side >= 1.2 m are `bulky` -> delivery method FREIGHT;
FREIGHT without a known delivery cost is an ERROR. Values are heuristics in
`categories/home/normalize.py`; adjust once real delivery quotes are collected (OPEN-16).

### ADR-038 · Source files contain no invisible or bidi characters — ACCEPTED
**Context:** escape sequences written through the editing tools were stored as literal NBSP,
zero-width and right-to-left-override characters (found by ruff RUF001 and a manual scan).
**Decision:** such characters must appear only as `\uXXXX` escapes; `tests/test_architecture.py`
fails on any Cf/Cc character in source. **Rationale:** "Trojan Source" - code must read the way it runs.

### ADR-039 · One immutable observation per check (supersedes ADR-016) — ACCEPTED
**Context:** requirement "store observations even when the price has not changed". It also exposed
a flaw in price spans: a span extended from day 1 to day 10 claims the price was known on days
2-9 even if nobody checked (PC off). **Decision:** `price_observations`, one IMMUTABLE row per
check with snapshots of source, condition, listing kind, availability, loyalty / multi-buy terms
and a separate delivery cost. Migration 0003 drops the (empty) `price_spans` table and refuses to
run if it contains rows. **Consequences:** ~15 M rows/year at full scale (OPEN-19); the `SPAN`
mutability class is retired.

### ADR-040 · Benchmarks computed on demand, no cache table — ACCEPTED
**Decision:** benchmarks are computed from observations when requested (pure functions);
evaluations will snapshot the values they use. **Rationale:** no stale cache, no invalidation logic,
fast enough for local volumes. Revisit if UI latency requires a cache.

### ADR-041 · Category benchmark policies — PROPOSED (defaults are heuristics)
TECH 90-day window; APPAREL 60 days and 4 samples (sparse per size); FOOD 30 days, 24 h freshness,
condition not relevant, unit-price basis, cross-pack unit price allowed; HOME 120 days, landed price
relevant (missing delivery caps confidence at MEDIUM). Common: >= 5 offer-day samples, >= 2 distinct
offers, MAD z 3.5, 10 % trimmed mean. To be tuned on real data (OPEN-20).

### ADR-042 · Offer-day sampling and robust statistics — ACCEPTED
**Decision:** one sample per offer and UTC day; robust median after MAD outlier removal
("trimmed median"), type-7 quantiles, trimmed mean; outliers excluded but reported; lowest current
price reported as a fact with an outlier flag; insufficient data returns no statistics.
**Rationale:** polling frequency must not weight a shop; gaps must not be extrapolated; the engine
needs to see suspicious prices, not have them silently removed.

### ADR-043 · Engines implemented as pure functions over typed views — ACCEPTED
**Decision:** `engines/personal` and `engines/resale` import only `core` and `evaluation`; services
build `PersonalInputs` / `ResaleInputs` from the database (benchmark *views*, never raw pricing
objects). Separate verdict enums and result types; an architecture test forbids imports between the
engines and checks the result types share no score field. Results are not persisted yet (OPEN-21).

### ADR-044 · Resale: missing critical input -> no numbers; review flag -> provisional numbers — ACCEPTED
**Decision:** if any critical input (price, delivery, condition, match, completed sales, fee profile
incl. shipping/packaging, tax profile, time to sell) is missing, the engine returns MANUAL_REVIEW
and computes nothing. If only review flags are open (unverified fee/tax, low-confidence sales...),
numbers are computed, marked `provisional`, and the verdict stays MANUAL_REVIEW.
**Rationale:** the requirement forbids calculating with missing inputs; showing provisional numbers
for a known-but-unverified input helps the user decide what to verify.

### ADR-045 · No built-in fees or tax rates; every number labelled — ACCEPTED
**Decision:** fee and tax profiles are user input with a `verified` flag; there are no defaults.
Engine parameters (return/defect rates, capital cost, thresholds) are labelled ASSUMPTION with
their source; medians and days-to-sell are ESTIMATE; profiles are USER_INPUT. Unknown buyer
shipping is assumed 0 (conservative, labelled). All formulas: docs/ENGINE_FORMULAS.md.

### ADR-046 · Engines check critical inputs themselves (defence in depth) — ACCEPTED
**Context:** found by tests: with unknown shipping but no "shipping" note from the category inputs,
the personal engine still produced a verdict and the resale engine hit an internal assertion.
**Decision:** both engines treat unknown price / delivery / condition as missing on their own,
regardless of what the category module reported.

### ADR-047 · Category engine parameters with audited user overrides — ACCEPTED
**Decision:** `PERSONAL_PARAMS` / `RESALE_PARAMS` per category module; overrides in `settings`
(`engine.<engine>.<CATEGORY>`), validated (unknown key / wrong type / negative -> error, never a
silent fallback) and audited. Defaults: docs/ENGINE_FORMULAS.md §1.7, §2.8 (PROPOSED, OPEN-22).

### ADR-048 · Manual Claude analysis implemented (clipboard mode) — ACCEPTED
**Decision:** `claude_bridge/` (pure: core + normalize only) builds a labelled package (FACT /
SELLER_CLAIM / ESTIMATE / ASSUMPTION / missing / deterministic verdicts), renders a deterministic
prompt with rules against prompt injection (untrusted listing text fenced, cleaned, delimiter
spoofs and code fences removed), and validates pasted answers with a strict Pydantic schema
(`dealradar.analysis.v1`, extra fields forbidden, strict types, no BUY value, no numeric fields).
Semantic rejections: wrong request_id, unknown disputed fact keys, HIGH-confidence CONSIDER while
information is missing, links / e-mail / phone numbers, hidden characters. Every pasted answer is
stored (valid or not) with its timestamp; packages expire after 7 days. The UI offers the prompt
with Streamlit's copy button, a download, and a plain link to claude.ai. No API key, no network
call, no browser automation (tests block sockets). The CLI mode (OPEN-1) is still not built.
**Consequences:** the answer is advisory only - an architecture test proves the bridge cannot
reach engines, pricing, the database or services.

### ADR-049 · `MOCK` access method for synthetic sources — ACCEPTED
**Decision:** synthetic fixture sources (`mock_shop`, `mock_market`) declare `AccessMethod.MOCK`;
migration 0004 allows the value. They never contact a network. Running them will require an
explicit demo opt-in (source framework, in progress).

### ADR-050 · Own completed sales are sold evidence (`OWN_SALE`) — ACCEPTED
**Decision:** SALE transactions of the user's own SOLD inventory items (with variant and condition)
feed the sold benchmark as evidence `OWN_SALE`, read straight from the ledger (no copy). The
`observed_sales` table may never hold `OWN_SALE` rows (CHECK `no_own_sales`), so the same sale
cannot be counted twice. Days listed = purchase -> sale (a proxy, documented).

### ADR-051 · Ledger: positive amounts, direction, reversals; actual vs. estimated kept apart — ACCEPTED
**Decision:** `acquisitions` (one order), `inventory_items` (one row per unit), `transactions`
(LEDGER: amount > 0, direction fixed by type, belongs to exactly one of order / item, corrections
only by a reversal row). Pure calculations in `ledger/calc.py` (imports core only): order money is
split equally over its units, remainder HUF to the lowest ids; realized profit only for closed
resale items; personal items are spending. Every summary shows ACTUAL (recorded transactions) and
ESTIMATED (Resale engine) in separate boxes; they are never added together. Formulas:
ENGINE_FORMULAS.md §4.

### ADR-052 · Notifications: in-app inbox, optional Telegram Bot API — ACCEPTED (resolves OPEN-4)
**Decision:** every notification is stored in `notifications` (dedupe key unique) and shown in the
app. If `DEALRADAR_TELEGRAM_BOT_TOKEN` and `DEALRADAR_TELEGRAM_CHAT_ID` are set, it is mirrored to
Telegram with the free Bot API (`sendMessage`, plain text, stdlib `urllib`, 10 s timeout, no new
dependency). Failures are recorded on the notification and logged with the token scrubbed; they
never break a refresh. Nothing in the app requires Telegram.

### ADR-053 · Evaluations, decisions, watchlists and fee profiles persisted (migration 0005) — ACCEPTED (resolves OPEN-21)
**Decision:** `personal_evaluations` and `resale_evaluations` (IMMUTABLE, separate tables, latest =
highest id, CHECK verdict MANUAL_REVIEW <=> missing/flags non-empty, full result JSON),
`offer_decisions` (WATCH / REJECT with a mandatory reason / RESTORE / BOUGHT - BOUGHT only via a
recorded purchase), `watchlists`, `fee_profiles` (user input, `verified` flag; default in settings
`resale.fee_profile_id`), tax profile in settings `resale.tax_profile`. Listings keep a JSON
snapshot of the normalized listing so offers can be re-evaluated without refetching.
Simplified from the design: no `rule_params` / `inputs_hash` tables yet (parameters are audited
overrides, ADR-047); every evaluation run is stored.

### ADR-054 · Refresh workflow and demo opt-in for mock sources — ACCEPTED
**Decision:** `refresh_jobs`, `source_runs` (+ counts), `source_run_errors`; refresh by source,
category or all (docs/SOURCES.md). MOCK sources run only after an explicit, stored demo opt-in;
health and the Overview warn while they exist. A third mock source (`mock_shop_2`) gives
benchmarks more than one offer. No real transport exists until a real source is verified.

### ADR-055 · Offer decisions are append-only feedback — ACCEPTED
**Decision:** the latest decision per offer wins; REJECT hides the offer from deal lists and needs
a reason (TOO_EXPENSIVE, WRONG_MATCH, BAD_CONDITION, SUSPECTED_SCAM, NOT_INTERESTED, OUT_OF_STOCK,
OTHER). The "Rejected offers" page summarizes reasons as feedback; RESTORE undoes a rejection.
Decisions never change evaluations.

### ADR-056 · Hungarian user interface; code stays English — ACCEPTED (resolves OPEN-10)
**Decision:** everything the user sees is Hungarian: UI, CLI output and help, notifications
(in-app and Telegram), error messages shown to the user, engine reasons, health check output.
Code, identifiers, database values, logs and developer docs stay English. One module,
`core/hu.py`, holds every label (enum values, missing-input / review-flag codes) and the formats:
money "12 345 Ft" with non-breaking spaces, percent "+12,5 %" with a decimal comma, dates in local
Budapest time "2026. 11. 24. 22:16". A test checks that every enum member and every code has a
label. Claude is asked to write free-text answer fields in Hungarian. `tzdata` becomes a direct
dependency (free, data only; it was already installed through pandas) so local time works on
Windows. Evaluations stored before this change keep their English reason texts until the offer is
re-evaluated.

### ADR-057 · One UI kit for a consistent interface — ACCEPTED
**Decision:** every page is built from `ui/views/widgets.py`: `page()` (title + one-sentence
purpose), status notices, one primary action, sections with bordered cards or tabs, `metrics()`
grids, `table()` (money right-aligned), verdict pills (`st.badge`) and `deal_list()`. Colours carry
meaning only: green = good / actual money, blue = action, orange = needs review, red = loss /
blocked, gray = neutral; set once in `.streamlit/config.toml` [theme]. A static stylesheet (no user
data) disables italics and synthetic fonts, mid-word breaks and uses tabular figures. The Personal
and Resale lists are separate tabs. Selectbox labels must be unique (`unique_labels()`): Streamlit
identifies options by label, so equal labels selected the wrong record (browser finding). The price
chart is Altair with Hungarian axis formats and a step line (price holds until the next check).

---

## Open decisions (need user input)

| ID | Question | Recommendation | Blocks |
|---|---|---|---|
| OPEN-1 | Claude modes: clipboard / file / sandboxed CLI | Clipboard + file now; CLI after a verified test on this PC | Phase 6 |
| OPEN-2 | Candidate sources per category | User lists; each gets robots/ToS review | Phase 5 |
| OPEN-3 | Resale platforms | Needed for fee profiles (user verifies fees) | Phase 4 |
| ~~OPEN-4~~ | External notification channel | **Resolved by ADR-052**: in-app + optional Telegram | - |
| OPEN-5 | Food resale | NOT_APPLICABLE permanently | Phase 4 |
| OPEN-6 | Deal thresholds per category and engine | User sets; defaults proposed in Phase 3 | Phase 3–4 |
| OPEN-7 | Tax status for resale | Clarify with an accountant; app flags until verified | Phase 4 |
| OPEN-8 | Collection frequency / unattended runs | Manual first, Task Scheduler later | Phase 5 |
| OPEN-9 | Used/refurbished acceptable for personal buys, per category | — | Phase 3 |
| ~~OPEN-10~~ | UI language | **Resolved by ADR-056**: Hungarian UI, English code | - |
| OPEN-11 | First category for vertical slice / first source | TECH | Phase 2, 5 |
| OPEN-12 | Raw snapshot retention | 30 days | Phase 5 |
| OPEN-13 | Local pickup: location + radius, or delivery only | — | Phase 3 |
| OPEN-14 | User's apparel sizes (per size system) | Needed for apparel personal rules | Phase 3 |
| OPEN-15 | Minimum completed sales for a PROFITABLE verdict (DB floor is 1) | 3 within 90 days | Phase 4 |
| OPEN-16 | Freight thresholds for HOME (ADR-037) | 30 kg / 1.2 m until real delivery data exists | Phase 3 |
| OPEN-17 | Brands/models to mark `counterfeit_prone` (raises authenticity risk) | User keeps the list; none preset | Phase 3 |
| OPEN-18 | Short-dated food threshold | 7 days before best-before | Phase 3 |
| OPEN-19 | Observation volume: compact old observations to one per offer-day after N days? | Not before 1 year of data | Phase 8 |
| OPEN-20 | Benchmark policy numbers per category (ADR-041) | Keep defaults until real data | Phase 3 |
| ~~OPEN-21~~ | Persist evaluations and fee/tax profiles | **Resolved by ADR-053** (migration 0005) | - |
| OPEN-22 | Engine thresholds and resale risk assumptions per category (ENGINE_FORMULAS §1.7, §2.8) | Keep until own sales data exists | Phase 4 |
| OPEN-23 | Your fee profiles (platforms, current commissions) and tax profile | Needed before any resale verdict can be PROFITABLE | Phase 4 |

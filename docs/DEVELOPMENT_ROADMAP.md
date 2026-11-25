# DealRadar HU — Development Roadmap

Status: v0.4 (2026-11-24). Phase 0 done; foundation, categories, pricing, engines, Claude bridge,
source framework and the user workflow implemented (awaiting user acceptance). QA: docs/QA_REPORT.md.
Each phase ends with: tests green, docs updated, user review.
No phase starts before the previous one is accepted. Phases are ordered by risk, not by category
importance — all four categories are equal in the end state (see ADR-010).

## Phase 0 — Requirements and documentation ✅
- Requirements analysis, risks, open decisions.
- README, CLAUDE.md, PRODUCT_SPEC, ARCHITECTURE, DATABASE_DESIGN, ROADMAP, DECISIONS.
- **Exit:** user answers the blocking open decisions (OPEN-1, -2, -3, -6, -11).

## Phase 1 — Skeleton and core primitives ✅ (2026-11-24, awaiting user acceptance)

**Done (verified):** `pyproject.toml`, venv, ruff, mypy `--strict`, pytest; config via env vars
(pydantic-settings); JSON-lines logging; `core/money.py`; SQLAlchemy 2 models for all tables below
with CHECK constraints and ORM mutability guards; repositories; Alembic migration `0001` (reviewed by
Claude Code, user review pending); single-writer lock; backups; `dealradar` CLI (`db upgrade|status|
backup`, `health`, `ui`); Streamlit navigation with Overview, four category dashboards (Personal and
Resale columns, empty), Sources, System health; health checks; 86 tests; architecture tests.
Verified manually: CLI on a fresh data dir, UI served on 127.0.0.1 only, pages render in a real
browser (Playwright), live health = OK.
Re-verified 2026-11-24 (stability check): clean caches, 86 tests, ruff, mypy strict, `pip check`,
fresh venv install exactly per README, `db upgrade` + `health` = OK, UI listening on 127.0.0.1 only.

**Done later the same day (needed by the category modules):** `core/units.py`, `core/hu_parse.py`
(51 number/price cases), `core/identifiers.py`.

**Still open in Phase 1:**
- (done in the pricing step below)

Original scope:
- `pyproject.toml`, venv, ruff, mypy, pytest; package skeleton.
- `core/money.py` (HUF integer + Decimal math, rounding), `core/units.py` (unit conversion,
  unit price), HU price-string parser (`1 299 Ft`, `1.299,-`, `12 990 Ft/kg`, `2x500 g`).
- SQLAlchemy models for: platforms, sources, source_runs, raw_records, products, product_variants,
  variant_identifiers, category attribute tables, listings, offers, price_spans, settings, audit_log.
  Alembic init + first migration (reviewed). Single-writer lock. `.streamlit/config.toml`
  (127.0.0.1, telemetry off). `.gitignore` for `data/`, `.env`.
- `tests/test_architecture.py`: import rules, no `if category ==` outside `categories/`,
  no `float` in money modules.
- **Tests:** money rounding, unit conversion, ≥ 40 parser cases from real-looking strings,
  span open/confirm/close semantics.
- **Exit:** `pytest` green; `dealradar db upgrade` creates an empty DB.

## Category domain modules ✅ (2026-11-24, pulled forward from Phase 7, awaiting user acceptance)
- Four modules with own attributes, normalization, validation, matching rules and evaluation
  inputs; shared `normalize/`, `matching/` (cascade), `evaluation/inputs.py`; `services/catalog.py`
  on the shared database; migration `0002`. 308 tests (parsers, normalization, matching per
  category, DB round trip, constraint survival). No collection, no engines, no Claude.
- Phase 7 keeps: more sources per category, fuzzy-match tuning on real data, benchmark roll-ups.

## Pricing and price-history engine ✅ (2026-11-24, pulled forward, awaiting user acceptance)
- `price_observations` (every check), `observed_sales` (completed sales), migration 0003.
- `pricing/` pure engine: offer-day sampling, median / trimmed median / quantiles / trimmed mean,
  MAD outliers, confidence, NO_DATA / INSUFFICIENT_DATA / STALE, delivery and landed price, lowest
  current price, category policies, food unit price across pack sizes; `services/pricing.py`.
- 404 tests incl. synthetic markets and DB-level variant isolation. No scraping.

## Evaluation engines ✅ (2026-11-24, pulled forward from Phases 3-4, awaiting user acceptance)
- `engines/personal`, `engines/resale` (pure, independent), `evaluation/costs.py` (all money
  formulas), `evaluation/params.py` (configurable parameters, fee/tax profiles),
  `services/evaluation.py` (inputs from DB, audited overrides). docs/ENGINE_FORMULAS.md.
- 529 tests incl. hand-computed financial cases, verdict boundaries, missing-input matrices.
- Not yet: persistence of evaluations and fee/tax profiles (OPEN-21), UI.

## Manual Claude analysis ✅ (2026-11-24, Phase 6 pulled forward, awaiting user acceptance)
- `claude_bridge/` (package, sanitizer, prompt, strict schema, validator), `services/analysis.py`,
  UI page "Claude analysis", migration 0004. No API, no automation. CLI mode (OPEN-1) not built.

## Source adapter framework ✅ (2026-11-24, awaiting user acceptance)
- Adapter interface, error kinds, polite requester (robots, throttle, daily cap, retries,
  Retry-After, cache, block detection), three synthetic mock adapters, registry, refresh service
  (source / category / all, progress, duplicates, staleness), refresh jobs and run errors
  (migration 0005), CLI and UI refresh, demo opt-in, docs/SOURCES.md.
- **No real source.** Each real source still needs the verification procedure (SOURCES.md §2) and
  the user's choice (OPEN-2).

## User workflow ✅ (2026-11-24, awaiting user acceptance)
- Central dashboard, four category dashboards with refresh buttons, refresh all, separate Personal
  and Resale lists, offer details with price-history chart, Claude analysis history, watchlists,
  decisions and rejection feedback, fee/tax profiles, inventory, purchase and sale records,
  reversals, realized profit (ACTUAL) shown apart from opportunities (ESTIMATED), in-app
  notifications, optional Telegram. Migration 0005; ADR-050..055.
- Phase 2-4 items below that are now covered: offer list / detail / history chart, watchlists,
  persisted evaluations, fee/tax profiles, acquisitions / inventory / ledger.
- Still open from those phases: CSV import and "add offer by hand", match review queue / unmatch /
  merge UI, `observed_sales` entry UI, rule_params versioning and inputs_hash.

## Phase 2 — Manual ingestion vertical slice (no scraping)
- CSV import + "add offer by hand" form (URL, title, price, shipping, condition, category).
- Normalization pipeline (generic + per-category stubs).
- Exact matching only (GTIN/MPN/style code/user) + variant resolution per category module.
  Match review queue, unmatch, product merge.
- Benchmarks shown in the UI (engine done: see the pricing step above).
- Minimal Streamlit: offer list, offer detail with history chart, match review.
- **Exit:** user can track products manually across all four categories end-to-end.

## Phase 3 — Personal Deal Engine
- Shared `evaluation/` (Rule framework, inputs builder, `costs.py`); `rule_params` versioned in DB,
  logic versioned by `code_version`. `personal_evaluations` table.
- Generic personal rules + category rules (tech: warranty type, condition; apparel: size match;
  food: unit price, best-before/validity; home: bulky shipping known).
- Watchlists; dashboard "Personal" column.
- **Tests:** each verdict boundary, MANUAL_REVIEW on every missing input, reproducibility via inputs_hash.

## Phase 4 — Resale Deal Engine (evidence-first)
- Fee profiles (user-entered, versioned, `verified_at`), tax profiles (unverified ⇒ MANUAL_REVIEW).
- Acquisitions, per-unit inventory, positive-amount ledger, cost-basis view; own sales exposed via
  `v_completed_sales` (no copy).
- `observed_sales` manual entry. `resale_evaluations` table.
- Net-profit range, ROI, liquidity, days-to-sell; food → NOT_APPLICABLE default.
- **Tests:** fee math per profile, cost allocation remainder, invariant "no PROFITABLE without
  completed sales", "asking prices never set expected sale price", negative-margin cases, rounding.

## Phase 5 — First automated source (one, carefully chosen)
- Polite HTTP client: robots cache, per-host limiter, Retry-After, block detection → `BLOCKED`.
- Source registry UI with access review fields (cannot enable without review).
- One collector for a source with an official API/feed or clearly permitted public access
  (chosen with the user — OPEN-2). Golden-fixture tests, parser health check.
- **Exit:** a scheduled or manual run collects, normalizes, matches, evaluates, notifies.

## Phase 6 — Claude bridge (manual)
- Sanitizer, prompt builder, response schemas, import + validation, UI page.
- Modes: clipboard + file hand-off (answered in claude.ai chat). Sandboxed CLI mode (`--tools ""`,
  no MCP, empty temp dir, `--json-schema`) only after OPEN-1 is decided and verified on the PC.
- **Tests:** injection fixtures (listing text containing "ignore previous instructions", fake JSON,
  markdown fences), schema rejection of extra fields, invariant "AI never changes verdicts".

## Phase 7 — Remaining category depth + more sources
- Per category, in the order agreed under OPEN-11: richer attribute extraction, fuzzy matching
  with review, 1–2 more permitted sources each.
- Apparel size handling, food unit-price ranking & flyer validity, home bulky-item shipping,
  tech config disambiguation.

## Phase 8 — Notifications, scheduling, hardening
- In-app inbox + optional Telegram: done (ADR-052).
- Windows Task Scheduler setup script (optional).
- Backups, snapshot pruning, performance check on 1 year of synthetic data.

## Later / maybe
Threshold tuning from decision history · PostgreSQL if ever multi-device · price-drop
forecasting (only with enough history) · export reports.

## Definition of done (every phase)
- Type-hinted, ruff + mypy clean, tests for business-critical logic.
- No new dependency without ADR; no schema change without migration.
- Docs (`ARCHITECTURE`, `DATABASE_DESIGN`, `DECISIONS`) updated in the same change.
- Feature claimed working only if a test or a recorded manual check proves it.

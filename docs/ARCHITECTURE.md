# DealRadar HU — Architecture

Status: v0.6 (2026-11-24). Implemented: `core`, `db`, `migrations` (0001-0005), `normalize`,
`matching`, `pricing`, `evaluation`, `engines` (personal, resale), all four `categories`,
`claude_bridge`, `sources` (framework + mock adapters, no real source), `ledger` (pure
calculations), `services` (incl. refresh, workflow, ledger, notify, demo), `ui` (all pages), `cli`.
The planned `workflow/` package became `services/workflow.py` + `services/notify.py`; the ledger
is `ledger/calc.py` (pure) + `services/ledger.py` (I/O).

## 1. Style

**Modular monolith**: one Python package, one SQLite file, one repo, no services, no daemon.
Boundaries are Python packages with a one-way import rule (§3) checked by a test.

```
 Streamlit UI ── calls ──► services (application layer: load inputs, call pure logic, persist)
                                  │
   collect ─► normalize ─► match ─► resolve variant ─► observations ─► benchmarks (on demand)
   (sources)  (generic +   (generic   (category          (pricing)      (pricing)
               category)    cascade +  module)                              │
                            category keys)                                  ▼
                                               ┌──────── evaluation inputs builder ───────┐
                                               │ (shared: effective cost, benchmark view, │
                                               │  completed-sales view, watchlist hit)    │
                                               └───────┬──────────────────────┬───────────┘
                                                       ▼                      ▼
                                              engines.personal        engines.resale
                                              → personal_evaluations  → resale_evaluations
                                                       └──────────┬───────────┘
                                   notify · decisions · inventory/ledger · claude_bridge (advisory)
```

## 2. Package layout

```
dealradar/
  core/          money.py (Huf type, Decimal math), units.py (quantities, pack sizes, unit prices),
                 hu_parse.py (HU number/price strings), identifiers.py (GTIN check digit, restricted
                 prefixes, MPN/style-code keys), enums.py, clock.py, errors.py, config.py
  db/            models/ (one file per area), session.py (PRAGMAs, lock), views.sql, repositories/
  migrations/    Alembic
  sources/       base.py (SourceAdapter protocol), errors.py, requester.py (PoliteRequester),
                 registry.py, mock/ (synthetic catalog, in-process transport, adapters) -
                 see docs/SOURCES.md
  normalize/     types.py (RawListing, NormalizedListing, Issue), text.py (sanitizer),
                 generic.py (price, shipping, warranty, condition, colour, identifiers),
                 pipeline.py (generic -> category normalize -> category validate)
  matching/      types.py (ProductCandidate, MatchOutcome, MatchingRules protocol),
                 cascade.py (identifier -> rule key -> fuzzy); merge.py later
  pricing/       types.py (keys, policy, results), stats.py (median, quantiles, trimmed mean,
                 MAD outliers), benchmarks.py (advertised, sold, unit price across packs)
  evaluation/    inputs.py (CategoryEvaluationInputs base - implemented), rules.py (Rule, runner),
                 costs.py (effective_cost, fee calc, net profit — the ONLY place money formulas live)
  engines/
    personal/    evaluator.py, generic_rules.py
    resale/      evaluator.py, generic_rules.py, liquidity.py
  categories/
    base.py      CategoryModule protocol, CategoryInfo, shared helpers; registry.py (module_for)
    tech/ apparel/ food/ home/
                 attributes.py (product / variant / listing Pydantic schemas), normalize.py
                 (normalization + validation), identity.py (matching rules), inputs.py (evaluation
                 inputs), __init__.py (MODULE); later: personal_rules.py, resale_rules.py
  claude_bridge/ sanitize.py, prompts.py, schemas.py, importer.py, cli_runner.py (optional, OPEN-1)
  ledger/        calc.py (pure: allocation, realized profit, portfolio summary - core only)
  services/      app_context, schema (status/upgrade), backup, health, overview, sources,
                 catalog (normalize, create_product, load_candidates, match_listing, snapshot),
                 pricing, evaluation, analysis, refresh (manual refresh workflow), workflow
                 (watchlists, decisions, fee/tax profiles, stored evaluations, deal lists, offer
                 detail), ledger (purchases, sales, reversals, summaries), notify (inbox +
                 optional Telegram), demo (synthetic data, opt-in)
  ui/            app.py (st.navigation), page_scripts/ (thin page files — never name it pages/),
                 views/ (render functions), state.py (cached AppContext)
  cli.py
tests/           mirrors the package tree; fixtures/
data/            (git-ignored) dealradar.db, raw/, backups/, ai_exchange/
```

## 3. Dependency rules (enforced by `tests/test_architecture.py`, stdlib `ast` scan, no extra tool)

```
core  ◄── everything
db    ◄── services, repositories only
normalize      may import: core                      (NOT categories, NOT db)
matching       may import: core, normalize           (category rules arrive via MatchingRules)
evaluation     may import: core, normalize
engines.*      may import: core, evaluation          (NOT db, NOT categories, NOT each other)
categories.X   may import: core, normalize, matching, evaluation, categories.base
               (NOT engines internals, NOT another category, NOT db)
services       may import everything except ui
ui             may import services, core only
claude_bridge  may import core, normalize only — NOT engines, NOT db, NOT services
ledger         may import core only (pure money calculations)
sources        may import core, normalize, sources — NOT db, NOT services, NOT engines
```

Consequences:
- `engines.personal` and `engines.resale` cannot share code except via `evaluation` → no hidden
  coupling, no merged score, and no duplicated money formulas (both call `evaluation/costs.py`).
- Categories never import each other → genuinely independent modules.
- Engines never import categories: category rules are *injected* by the service via the registry.

## 4. Category modules

Implemented contract (`categories/base.py`, ADR-029):

```python
class CategoryModule(Protocol):
    info: CategoryInfo                     # key, label, scope, variant meaning, comparison basis
    product_attrs_model / variant_attrs_model / listing_attrs_model: type[BaseModel]
    fuzzy_threshold: int                   # fuzzy never auto-accepts; threshold only filters
    rule_key_decisive: bool
    # normalization + validation
    def normalize(self, listing: NormalizedListing) -> NormalizedListing   # attrs + variant_key
    def validate(self, listing: NormalizedListing) -> list[Issue]          # ERROR blocks
    # matching rules (consumed by the generic cascade)
    def identifier_requires_brand(self, id_type) -> bool  # MPN / style code only with maker
    def identifier_pins_variant(self, id_type) -> bool    # EAN = one size; style code = all sizes
    def rule_key(self, listing) -> str | None
    def product_rule_key(self, product: ProductCandidate) -> str | None
    def contradictions(self, listing, product) -> list[str]
    # evaluation inputs (consumed by the engines in Phases 3-4)
    def evaluation_inputs(self, listing) -> CategoryEvaluationInputs
```

Where an attribute lives: **product** attributes (model-level) in the typed `product_attrs_<cat>`
table; **variant** attributes (capacity, size, pack) in `product_variants.variant_attrs` (JSON,
validated by the module schema); **listing** attributes (authenticity risk, best-before, delivery
method, unit price) in `listings.category_attrs`.

Planned extensions (Phases 3-4): `benchmark_policy()`, `personal_rules()`, `resale_rules()`.

Shared pipeline code dispatches only through the registry; `if category == ...` outside
`categories/` is forbidden (architecture test greps for it).

Per-category behaviour:

| | tech | apparel | food | home |
|---|---|---|---|---|
| product = | manufacturer + model line | brand + model + colourway | brand + product | manufacturer + model number |
| variant = | capacity / configuration (`2000GB`, `32GB-2X16GB`, `16GB-512GB`) | size (`EU42`, `INTM`, `INTW32L34`) | pack size (`500G`, `6X330ML`) | colour, else `default` |
| identifiers | EAN; MPN (brand-scoped) | EAN (one size); style code (brand-scoped, all sizes) | EAN (in-store codes ignored) | EAN; model number as MPN (brand-scoped) |
| decisive rule key | none (review) | none (review) | none (review) | manufacturer + model number if code-like |
| contradictions | kind, socket, GPU chipset, RAM type, SSD interface | colour, gender (UNISEX ok, KIDS not) | measurement unit | energy class, dimension > 2 % |
| key validation | capacity / RAM type / chipset per kind; title vs specs conflict | size; authenticity HIGH | pack size; expired / past best-before | manufacturer; bulky without delivery cost |
| comparison | item | item, per size | **unit price** (HUF/kg, l, piece) and item | item; unit price for consumables |
| benchmark roll-up | none | "any size in user's sizes" | best unit price across pack sizes | none |
| extra personal rules | warranty type, condition grade | user size available | validity window, loyalty-only, min quantity | shipping/delivery known for bulky |
| resale default | enabled | enabled, counterfeit-risk flag on marketplace/private | **NOT_APPLICABLE** | enabled, bulky shipping cost required |

## 5. Two engines (implemented - formulas in docs/ENGINE_FORMULAS.md)

Both engines are pure functions:

```python
evaluate_personal(i: PersonalInputs, rules: Sequence[Rule[PersonalInputs]], p: RuleParams) -> PersonalResult
evaluate_resale(i: ResaleInputs, rules: Sequence[Rule[ResaleInputs]], p: RuleParams,
                fees: FeeProfile, tax: TaxProfile) -> ResaleResult
```

- **Shared, once:** `evaluation/rules.py` (Rule protocol, runner, short-circuit to MANUAL_REVIEW),
  `evaluation/costs.py` (effective purchase cost, fee computation, net profit), `evaluation/inputs.py`.
- **Separate:** verdict enums, thresholds (`rule_params` per engine × category), result tables,
  UI columns, notification rules. No function or view returns both verdicts combined.
- `ResaleInputs.completed_sales: tuple[CompletedSale, ...]` — the type has no field for asking
  prices except `context_asking_prices`, which is ignored by the price/profit computation and only
  displayed. Invariant test: removing all completed sales can never yield `PROFITABLE`.
- Uncertainty: each rule declares required inputs; missing → `MANUAL_REVIEW` with
  `missing_inputs`. Unverified fee or tax profile → review flag → `MANUAL_REVIEW` (one-time fix: the
  user verifies the profile).
- Re-evaluation only when `inputs_hash` changes.

## 6. Price history and benchmarks (implemented, ADR-039..042)

**Storage.** `price_observations`: one immutable row per check of an offer, also when nothing
changed; source, condition, listing kind, availability and loyalty / multi-buy terms are
snapshotted; delivery cost is its own column (NULL = unknown, never 0). `observed_sales`: completed
sales with a final price, in a separate table - advertised prices and sales never share a table,
a function or a result type (`AdvertisedBenchmark` vs `SoldBenchmark`, `price_kind`).

**Benchmark key.** variant (plus variants merged into it) x condition group
(NEW / OPEN_BOX / REFURBISHED / USED / FOR_PARTS; food: NOT_APPLICABLE) x channel (RETAIL =
shops + marketplace sellers, SECONDHAND = classifieds + auctions, FLYER). Offers without a resolved
variant are never included; unknown conditions are excluded and counted, never assumed.

**Sampling.** One sample per offer-day (last observation of the UTC day). Re-checks of an unchanged
price are stored but do not multiply its weight; unchecked days contribute nothing.

**Exclusions (counted in `excluded`).** outside window, other variant / channel / condition,
condition unknown, out of stock, price missing, loyalty-only and multi-buy (unless the category
policy includes them).

**Statistics** (`pricing/stats.py`, Decimal only): `median_all` (every eligible sample),
`trimmed_median` (median after outlier removal - trimming equal tails would not change a median,
so the robust variant removes flagged outliers), p10 / p25 / p75 / p90 (type-7 quantiles, tested
against Python's `statistics`), `trimmed_mean` (10 % per tail), min / max. Separate delivery stats,
landed price (item + delivery, only samples with known delivery) and unit price in centi-HUF.

**Outliers.** Modified z-score on the MAD (|z| > 3.5); if most values are identical (MAD = 0),
values > 50 % from the median; zero prices always. Checked from 5 samples. Outliers are excluded
from the statistics but listed with reasons - a suspiciously low price may be the deal or an error.

**Status and confidence.** `NO_DATA` / `INSUFFICIENT_DATA` (fewer than `min_samples` offer-days or
fewer than 2 distinct offers) return **no statistics** - nothing is estimated. `STALE` when the newest
sample is older than the policy allows (confidence <= LOW). `OK` with confidence HIGH only with
enough samples, >= 2 sources, IQR/median <= 25 % and <= 20 % outliers; every limitation is listed in
`reasons`. Sold benchmarks with only user-reported sales are capped at MEDIUM.

**Lowest current price** is a fact, not a statistic: the cheapest buyable offer whose latest
observation is within the policy's freshness window, flagged if it was an outlier.

**Category awareness.** Each category module exposes a `BenchmarkPolicy` (window, minimum
samples, freshness, condition relevance, landed-price relevance, unit-price basis). Only food may
compare different variants, and only by unit price across pack sizes, as a separately labelled
`UnitPriceBenchmark` (`basis = UNIT_PRICE_ACROSS_PACK_SIZES`).

**Shop "was" prices** are stored nowhere as a benchmark (fake-discount protection).

## 7. Product identity and matching

Two levels: **product** (model/style) and **variant** (comparable unit). Matching is listing → product;
variant resolution is offer → variant by the category module (ADR-014).

Cascade (`matching/cascade.py`, implemented; first decisive step wins). Outcomes:
`AUTO_MATCH`, `REVIEW` (candidates for the user), `CONFLICT` (evidence contradicts itself), `NO_MATCH`.
1. Identifier hit (GTIN / MPN / style code) within the listing's category → `AUTO_MATCH`, unless
   the identifiers point to different products or the category reports a contradiction → `CONFLICT`.
   MPN and style codes are stored brand-scoped (`samsung|MZV9P2T0BW`), so the same part number at
   two manufacturers never matches (ADR-030). Whether the hit also fixes the variant is the
   category's `identifier_pins_variant` (an apparel style code covers every size).
   If the pinned variant disagrees with the listing's own variant key → `CONFLICT`.
2. Category rule key hit → `AUTO_MATCH` only if the category declares it decisive and there is one
   uncontradicted hit; otherwise `REVIEW`. Same key but contradicting specs is still shown for
   `REVIEW` (confidence 40, contradiction as reason) - never silently dropped.
3. Fuzzy (stdlib `difflib`, order-insensitive tokens, same brand, no contradictions) → `REVIEW` only.
4. User or AI suggestion → candidate only, user decides (Phase 2 / Phase 6).

After the product is decided, the variant is resolved from the listing's category `variant_key`;
an unknown variant (e.g. a new size) is reported, not invented (`variant_id=None` + reason).

Only accepted matches link data. Rejecting a match closes the link and invalidates benchmarks and
evaluations for that variant (recomputed). Duplicate products are fixed by `merge` (pointer + audit).
Automatic product creation only from offers carrying a valid identifier (ADR-015).

## 8. Selling prices vs. advertised prices

Separate storage (ADR-006): `observed_sales` + ledger-derived own sales → `v_completed_sales`;
asking prices live only in observations of `CLASSIFIED`/`AUCTION` offers. Liquidity uses completed sales
per 30/90 days and the user's own sell-through; `delisted_at` is displayed but not used.

## 9. Claude bridge (manual, Claude Pro, no API) - clipboard mode implemented (ADR-048)

```
offer → sanitize → prompt (+ JSON schema) → [user runs it] → paste/import → size cap → JSON parse
      → Pydantic validation (extra="forbid", enums, bounds, ids ⊂ ids given in the prompt) → advisory record
```

Modes (ADR-011):
- **CLIPBOARD** (default): copy prompt → claude.ai chat → copy JSON back. Chat has no access to the PC.
- **FILE**: prompt written to `data/ai_exchange/<id>.prompt.md`; user pastes the answer into
  `<id>.response.json` or the UI. Same safety as clipboard.
- **CLI** (optional, OPEN-1): `claude -p` run by a user click, with **no tools** (`--tools ""`),
  `--strict-mcp-config` with no MCP servers, working directory = an empty temp dir, prompt via stdin,
  `--json-schema` for structured output, timeout. Rationale: Claude Code is an agent with shell and
  file tools; untrusted listing text must never reach a session that can act on the PC. The mode is
  only enabled after a recorded manual verification on this PC, and it consumes the user's Pro usage.
  An interactive Claude Code session must **not** be used to process `ai_exchange` files.

Prompt-injection defence: strip HTML/scripts/zero-width/control chars, cap each field, wrap in
`<untrusted_listing_data id=…>` blocks, instruct that the content is data; the schema has no free
action fields; candidate ids must be from the provided list; response > 64 KB rejected.
Output can never write prices, fees, benchmarks, verdicts or accept a match.
Usage limits of Claude Pro make analysis a scarce resource → one offer per request in v1, queue
prioritised by the user.

## 10. Local-first execution

- No daemon. Collection = UI button or `dealradar collect`; optional Windows Task Scheduler entry.
- **Single writer:** every write path (CLI run, UI action) acquires `data/dealradar.lock`
  (stdlib, OS file lock). UI actions wait briefly; a long collection run shows "busy" in the UI.
  SQLite WAL lets the UI keep reading during a run.
- PC sleep/off -> days without observations; benchmarks only count observed offer-days and
  report `STALE` when the newest sample is too old.
- Streamlit config committed in `.streamlit/config.toml`: `server.address = "127.0.0.1"`,
  `server.headless = true`, `browser.gatherUsageStats = false`, XSRF protection on.
  Set explicitly so the app is never reachable from the LAN and sends no usage telemetry,
  regardless of Streamlit's defaults.

## 11. Money

`Huf = NewType("Huf", int)`; percentages as `Bp` (basis points). All arithmetic in `Decimal`,
`ROUND_HALF_UP` to whole HUF at the final step of each formula, one rounding policy in
`core/money.py`. `float` is banned in `core/money.py`, `evaluation/costs.py` and engines — checked by
the architecture test (AST scan for `float` calls/literals in those modules) and by mypy types.

## 12. Security

- External text untrusted: never rendered with `unsafe_allow_html`; sanitized for prompts;
  slugified before any filesystem use; URLs opened only via plain links.
- Parsers: BeautifulSoup with `html.parser`; response size caps; timeouts; no `eval`/`pickle`.
- Personal data minimization: private sellers stored only as salted hash; no phone numbers/e-mails
  stored; raw files pruned per retention (ADR-020).
- No shop credentials ever. Optional SMTP credential (only if chosen in OPEN-4) lives in `.env`
  (git-ignored), never in the DB or logs; `keyring` is not added (extra dependency for one secret).
- `data/`, `.env` in `.gitignore`. Repo contains no fixtures with personal data.

## 13. Observability

JSON-lines log per run; `source_runs` counters; parse-success ratio below threshold → source
`DEGRADED`, writes paused for that source until the user acknowledges (prevents silent garbage).

## 14. Testing

Unit tests for money, HU parsing, unit prices, observations/benchmarks (incl. gaps), fee/net-profit,
cost-basis allocation, each rule, sanitizer, response validation (injection fixtures).
Invariant tests: no PROFITABLE without completed sales; AI import never changes evaluations;
MANUAL_REVIEW ⇔ missing inputs/flags; architecture import rules; no float in money modules.
Golden fixtures per collector. No network in tests.

## 15. Dependencies

Runtime: `sqlalchemy>=2`, `alembic`, `pydantic>=2`, `pydantic-settings`, `httpx`,
`beautifulsoup4`, `streamlit`. Optional, per permitted source only: `playwright`.
Dev: `pytest`, `ruff`, `mypy`. Fuzzy matching: stdlib `difflib`. Scheduling: Windows Task Scheduler.
FX: MNB official rates or user entry. Anything else requires an ADR.
No paid service, API key or account is required to run the app.

## 15a. User-facing language and UI kit (ADR-056, ADR-057)

`core/hu.py` (pure, no dependencies) holds all Hungarian labels and number / date formats; engines,
services, CLI and UI use it. `ui/views/widgets.py` is the only place that defines page anatomy,
colours, pills, tables and the stylesheet.

## 16. User workflow (implemented 2026-11-24)

```
Refresh (button / CLI) -> services.refresh -> adapter.fetch via PoliteRequester
   -> normalize -> listing + offer (snapshot) -> match -> price_observation
   -> services.workflow.evaluate_offer -> engines.personal -> personal_evaluations
                                       -> engines.resale   -> resale_evaluations
   -> services.notify (inbox; Telegram mirror if configured)
UI: Overview (refresh all, top list per engine, ACTUAL vs ESTIMATED money, inbox, warnings)
    4 category pages (refresh, Personal list, Resale list) -> Offer details (history chart, both
    evaluations, decision, record purchase, Claude analyses) -> Inventory (sales, costs,
    statuses, reversals, actual results) · Watchlists · Rejected offers · Settings (fee/tax,
    Telegram, demo)
```

- The two lists are separate queries and separate sort orders (`personal_deals`,
  `resale_deals`); an architecture test allows engine result types only in engines,
  services.evaluation, services.analysis and services.workflow.
- Money shown to the user comes from two different functions: `ledger.portfolio` (ACTUAL,
  recorded transactions) and `ledger.estimated_opportunities` (ESTIMATED, Resale engine). No code
  adds them together.
- Telegram is optional: without credentials `notify` only writes the inbox and never calls the
  network.

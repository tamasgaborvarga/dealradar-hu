# DealRadar HU — Database Design

Status: v0.7 (2026-11-24). Implemented: migrations `0001` (Phase 1 tables), `0002` (category
attributes), `0003` (price_observations, observed_sales; price_spans dropped - ADR-039), `0004`
(ai_requests, ai_responses, MOCK access method), `0005` (refresh jobs and run errors, evaluations,
decisions, watchlists, notifications, fee profiles, ledger - see the "Implemented (0005)" notes
below; where they differ from the original design, the note wins).
Logical design. The first Alembic migration is generated from SQLAlchemy models in Phase 1 and
reviewed before it is applied.

## 1. Conventions

- SQLite 3, WAL mode, `PRAGMA foreign_keys=ON`, `busy_timeout=5000`.
- Schema changes **only** via reviewed Alembic migrations, applied by an explicit command
  (ADR-004). The app refuses to start on a schema mismatch.
- Primary keys: `INTEGER` autoincrement `id`.
- Timestamps: UTC, ISO-8601 text via SQLAlchemy `DateTime(timezone=True)`; Europe/Budapest only in UI.
- Money: `INTEGER` HUF, gross (VAT-inclusive) (`*_huf`). Percentages: `INTEGER` basis points (`*_bp`).
  Unit prices: `INTEGER` centi-HUF per canonical unit (`*_chuf`). No floats (ADR-007).
- Enums: `TEXT` + `CHECK`, mirrored by Python `StrEnum`.
- Unknown = `NULL`. `0` is a real value (free shipping), never "unknown".
- **Mutability classes** (every table is labelled):
  - `IMMUTABLE` — insert only, never updated or deleted (except retention pruning of raw files).
  - `LEDGER` — insert only; corrections are reversal rows.
  - (`SPAN` - retired with ADR-039; price history is IMMUTABLE observations now.)
  - `STATE` — mutable current state; every user-originated change is written to `audit_log`.
  - `CACHE` — derived, may be deleted and recomputed at any time; never a source of truth.

### 1.1 Implementation notes (Phase 1)

- Mutability classes are enforced by SQLAlchemy `before_update`/`before_delete` guards
  (`dealradar/db/base.py`) and by CHECK constraints. Raw SQL / bulk `update()` bypasses the ORM
  guards — repositories must not use them on non-STATE tables. SQLite triggers as a second line of
  defence are a known open item.
- `source_runs` are mutable while `RUNNING`, immutable once finished. `raw_records` allow
  `parse_status` and `storage_path` (pruning) to change.
- Reads use `Database.read_session()` (a flush raises); writes use `Database.write_session()`
  (takes the writer lock, commits or rolls back).
- `variant_identifiers` uniqueness uses two partial unique indexes because SQLite treats NULLs as
  distinct in a plain UNIQUE constraint (a single `(id_type, value, source_id)` key would have
  allowed the same GTIN on two variants). Tested.
- Lengths/sizes are integers in small units (`screen_diag_tenth_in`, `*_mm`, `weight_g`), no floats.
- Enum CHECK constraints in the migration are named after the enum (`status`, `category`, …).

## 2. Entity overview

```
platforms ─┬─< sources ─< source_runs ─< raw_records
           ├─< fee_profiles
           └─< observed_sales / transactions / inventory listings

products ─< product_variants ─< variant_identifiers
   │              │
   │              ├─< offers ─< price_observations
   │              │     ▲
   │              │  listings (page/ad) ─< offers           (listing 1:N offers, e.g. one page, many sizes)
   │              │     └─< match_candidates >─ products
   │              ├─< benchmarks (CACHE)
   │              ├─< observed_sales           ┐
   │              └─< inventory_items ─< ...   ┘→ v_completed_sales (view)
   └─< product_attrs_{tech|apparel|food|home}

offers ─< personal_evaluations      (separate tables — ADR-002)
offers ─< resale_evaluations
offers ─< ai_requests ─< ai_responses
offers ─< decisions
acquisitions ─< inventory_items ;  transactions (ledger)
rule_params · tax_profiles · fx_rates · settings · notifications · audit_log
```

## 3. Product identity

Identity has two levels (ADR-014):

- **product** = a model / style / product line that a human would call "the same thing":
  *RTX 4070 Super Gaming OC (brand X)*, *Nike Air Max 90 style DM0029-100*, *Brand Y ground coffee*.
- **product_variant** = the concrete sellable unit whose price is comparable 1:1:
  laptop configuration, apparel size, food pack size, appliance colour if it changes the price.
  Every product has at least one variant (`default` variant when there is no variation).

Benchmarks, offers, evaluations and sales attach to **variants**. Product-level roll-ups
(e.g. "cheapest size", "best unit price across pack sizes") are computed by the category module.

**products** `STATE`
| column | type | notes |
|---|---|---|
| id | int PK | |
| category | enum | `TECH`,`APPAREL`,`FOOD`,`HOME` — authoritative category |
| subcategory | text | module-defined vocabulary (e.g. `GPU`, `SNEAKER`, `COFFEE`) |
| brand, model_name, title | text | |
| brand_key, model_key | text null | `core.identifiers.text_key()` of brand / model; index (category, brand_key) for candidate lookup |
| created_by | enum | `USER`, `RULE` (RULE only from GTIN/MPN-bearing offers, ADR-015) |
| merged_into_id | FK products null | product merge keeps history; reads follow the pointer |

**product_variants** `STATE` — id, product_id FK, variant_key (text, module-built, e.g. `EU42`,
`16GB-1TB-RTX4060`, `1KG`, `default`), title_suffix, merged_into_id. Unique (product_id, variant_key).

**variant_identifiers** `STATE` — id, variant_id FK, id_type (`GTIN`,`MPN`,`STYLE_CODE`,`SHOP_SKU`),
value (normalized), source_id FK null (only for `SHOP_SKU`). Unique (id_type, value, source_id).
One variant may have several GTINs (regional packs); one GTIN never maps to two variants —
a conflict blocks automatic matching and goes to review.

**product_attrs_tech / _apparel / _food / _home** `STATE` — one typed table per category, keyed by
`product_id` (model-level attributes) — plus `variant_attrs_json` on the variant only where the
module declares variant attributes (size, config, pack). Schemas are owned by the category module
and validated by its Pydantic model before writing.

Product level (typed tables, migration 0002) / variant level (`variant_attrs` JSON) /
listing level (`listings.category_attrs` JSON). Schemas: `categories/<cat>/attributes.py`;
`tests/test_category_persistence.py` asserts every product-attribute field has a column.

| | product (table column) | variant (JSON) | listing (JSON) |
|---|---|---|---|
| tech | kind, cpu_socket, gpu_chipset, ram_type, ssd_interface, ssd_form_factor, screen_diag_tenth_in, resolution, panel, refresh_hz, cpu_model, gpu_model | capacity_gb, modules, memory_gb, storage_gb, speed_mts | sealed, invoice_available |
| apparel | gender, fit, color, season, material, size_system, counterfeit_prone | size, size_system, size_inferred | authenticity_risk, authenticity_reasons |
| food | canonical_unit (null until a pack size is read) | pack_count, each_amount, each_unit, total_canonical | unit_price_chuf, shelf_unit_price_chuf, best_before, date_kind |
| home | kind, width/height/depth_mm, weight_g, energy_class, power_w, noise_db, tech_specs (JSON), bulky, assembly_required, installation_required | color | delivery_method, dimension_order_assumed |

Manufacturer, model and EAN/MPN/style code are not attribute columns: they live in
`products.brand/model_name` and `variant_identifiers` (MPN/style code stored brand-scoped,
e.g. `samsung|MZV9P2T0BW`, ADR-030). Condition and warranty are listing fields.

## 4. Sources, platforms, collection

**platforms** `STATE` — id, key, name, kind (`RETAILER`,`MARKETPLACE`,`CLASSIFIEDS`,`AUCTION`,
`PRICE_COMPARATOR`,`FLYER`,`OTHER`), url. A platform can be both a data source and a sell channel;
this table is the single place that names it.

**sources** `STATE` — id, key, platform_id FK, access_method (`OFFICIAL_API`,`FEED`,`PUBLIC_HTML`,
`PUBLIC_HTML_JS`,`MANUAL`), robots_checked_at, robots_allows, tos_reviewed_at, tos_note,
access_review_ok, status (`DISABLED`,`ACTIVE`,`DEGRADED`,`BLOCKED`), min_interval_s,
daily_request_cap, provides_completed_sales (bool), raw_retention_days.
CHECK: `status='ACTIVE'` ⇒ `access_review_ok=1`.

**source_runs** `IMMUTABLE` after finish — id, source_id, started_at, finished_at, status
(`OK`,`PARTIAL`,`FAILED`,`BLOCKED`), requests, fetched, parsed, failed, parse_success_bp, error_summary.

**raw_records** `IMMUTABLE` — id, source_run_id, external_ref, url, fetched_at, content_hash,
storage_path (null after pruning), http_status, parse_status.

**Implemented (0005):** `refresh_jobs` (scope SOURCE/CATEGORY/ALL, target, requested_by,
started_at, finished_at, status; mutable only while RUNNING), `source_runs` gained
`refresh_job_id`, `new_observations`, `duplicates`, `retries`, `cache_hits`, `error_kind`;
`source_run_errors` IMMUTABLE (source_run_id, at, kind, external_ref, message <= 500).
`listings.normalized` (JSON) keeps the normalized listing snapshot for re-evaluation.

## 5. Listings and offers (normalized offer model)

**listings** `STATE` — one page / ad / flyer item at one source.
| column | type | notes |
|---|---|---|
| id | int PK | |
| source_id | FK | |
| external_id | text | stable id from source; else `url:<sha1(canonical_url)>`; manual: `manual:<uuid>` |
| url, title | text | sanitized |
| listing_kind | enum | `RETAIL` (shop sells new), `MARKETPLACE` (3rd-party seller inside a shop), `CLASSIFIED` (private/negotiable ad), `AUCTION`, `FLYER` (store promotion) |
| category_hint | enum null | pre-match guess only; authoritative category is on the product |
| product_id | FK null | set only by an accepted match |
| match_status | enum | `UNMATCHED`,`PENDING_REVIEW`,`MATCHED`,`REJECTED`; CHECK `MATCHED` ⇔ `product_id` set |
| seller_kind | enum null | `RETAILER`,`BUSINESS_SELLER`,`PRIVATE` |
| seller_ref | text null | retailer/business name; **private sellers: salted hash only** (ADR-020) |
| condition | enum null | `NEW`,`OPEN_BOX`,`REFURBISHED`,`USED` (grade not stated),`USED_A`,`USED_B`,`USED_C`,`FOR_PARTS` |
| warranty_months | int null | |
| warranty_type | enum null | `MANUFACTURER_HU`,`MANUFACTURER_EU`,`SELLER`,`NONE` |
| price_is_net | bool null | true if the source shows net + VAT (B2B shops); normalized to gross on offers |
| location_text | text null | for pickup-only classifieds |
| category_attrs | JSON null | the category's ListingAttrs (validated by the module) |
| first_seen_at, last_seen_at, delisted_at | | `delisted_at` = no longer visible. **Not a sale.** |
| duplicate_of_id | FK listings null | reposted classifieds |
Unique (source_id, external_id).

**offers** `STATE` — the priced, buyable unit: one listing × one variant.
| column | type | notes |
|---|---|---|
| id | int PK | |
| listing_id | FK | |
| variant_id | FK null | resolved by the category module after the listing is matched |
| variant_key_raw | text | as seen on the source (e.g. `42`, `1 kg`, `16/512`) |
| currency | text | `HUF` normally |
| loyalty_only | bool | app/card-only price |
| min_quantity | int | multi-buy promos ("3-at-2") |
| valid_from, valid_to | null | flyer / promo validity |
| is_active | bool | |
Unique (listing_id, variant_key_raw).

Current price is **not** stored on offers; it is the latest `price_observations` row.

**price_observations** `IMMUTABLE` (ADR-039, migration 0003) - one row per check, **also when the
price did not change**. Time without a check is unknown and is never filled in.
| column | type | notes |
|---|---|---|
| id | int PK | |
| offer_id | FK | identity: source + listing external id + raw variant text |
| source_id | FK | snapshot (denormalized for fast benchmark queries) |
| observed_at | datetime | UTC; unique with offer_id |
| price_huf | int null | gross item price; NULL only if availability is OUT_OF_STOCK / UNKNOWN (CHECK) |
| shipping_huf | int null | delivery cost, separate; NULL = unknown, 0 = free |
| availability | enum | `IN_STOCK`,`LIMITED`,`PREORDER`,`OUT_OF_STOCK`,`UNKNOWN` |
| condition | enum null | snapshot of the listing's condition at this moment (NULL = not stated) |
| listing_kind | enum | snapshot: RETAIL / MARKETPLACE / CLASSIFIED / AUCTION / FLYER |
| loyalty_only, min_quantity | bool, int | snapshot of the offer's terms |
| raw_record_id | FK null | evidence |
Indexes: unique (offer_id, observed_at); (observed_at).
The offer's link to a variant is *not* snapshotted: benchmarks follow the current, audited match,
so correcting a wrong match also corrects history.

**match_candidates** `IMMUTABLE` except `status`/`decided_at`/`decided_by` — id, listing_id, product_id, method
(`GTIN`,`MPN`,`STYLE_CODE`,`RULE`,`FUZZY`,`USER`,`AI_SUGGESTED`), confidence (0–100), reason,
status (`OPEN`,`ACCEPTED`,`REJECTED`,`SUPERSEDED`), decided_at, decided_by (`SYSTEM`,`USER`).
The accepted match of a listing = its candidate with `status='ACCEPTED'`; a partial unique index
allows at most one. (v0.2 had `listings.accepted_match_id`; dropped in v0.3 — it duplicated this and
created a circular foreign key listings ↔ match_candidates.)

**fx_rates** `IMMUTABLE` — id, currency, rate_date, huf_per_unit (text decimal), source
(`MNB`,`USER`). No paid FX source. *Not in migration 0001*; arrives together with
`price_observations.price_original/currency/fx_rate_id` when the first non-HUF source is added.
Until then `record_observation` refuses non-HUF offers.

## 6. Benchmarks (computed on demand - ADR-040)

No benchmark table. `pricing/benchmarks.py` computes a benchmark from observations when asked;
evaluations (Phase 3/4) will snapshot the values they used in `inputs_json`.
Key: (variant incl. variants merged into it) x condition group x channel. See ARCHITECTURE.md §6.

## 7. Completed-sale evidence (ADR-006, revised)

Asking prices and completed sales are **different tables**, so they cannot be confused by a filter bug.

**observed_sales** `IMMUTABLE` — completed sales the user did not make.
| column | type | notes |
|---|---|---|
| id | int PK | |
| variant_id | FK | |
| platform_id | FK | |
| evidence | enum | `PLATFORM_FINAL_PRICE` (platform shows the final price), `USER_REPORTED` |
| condition | enum | |
| sale_price_huf | int > 0 | final item price |
| buyer_shipping_huf | int null | delivery paid by the buyer, separate |
| sold_at | text | |
| days_listed | int null | |
| source_ref | text, required | URL / note: where the evidence comes from |
| listing_id | FK null | if derived from a collected listing |
| entered_by, note, created_at | | |
Implemented in migration 0003. Own sales (ledger view) arrive with Phase 4.

**v_completed_sales** (SQL view) = `observed_sales` ∪ the user's own sales derived from
`transactions` (type `SALE`) joined to `inventory_items`. Own sales are **not** copied into a second
table — the ledger is the single source of truth.

Asking prices remain in `price_observations` of `CLASSIFIED`/`AUCTION` offers (channel
`SECONDHAND`). The resale engine's input type has no field that can receive them as expected sale price.

## 8. Evaluations (two tables — ADR-002)

**personal_evaluations** `IMMUTABLE`
id, offer_id, evaluated_at, code_version, rule_params_id, inputs_hash, inputs_json (benchmarks,
watchlist hit, condition, warranty, effective price used), verdict (`STRONG_DEAL`,`GOOD_DEAL`,
`FAIR_PRICE`,`NOT_A_DEAL`,`MANUAL_REVIEW`), effective_price_huf, discount_vs_median90_bp,
discount_vs_lowest_current_bp, reasons_json, missing_inputs_json, review_flags_json.
CHECK (SQLite JSON1): `verdict='MANUAL_REVIEW'` ⇔
`json_array_length(missing_inputs_json) + json_array_length(review_flags_json) > 0`.
Same columns and CHECK on `resale_evaluations`.

**resale_evaluations** `IMMUTABLE`
id, offer_id, evaluated_at, code_version, rule_params_id, fee_profile_id, tax_profile_id,
inputs_hash, inputs_json, verdict (`PROFITABLE`,`MARGINAL`,`NOT_PROFITABLE`,`MANUAL_REVIEW`,
`NOT_APPLICABLE`), target_platform_id, expected_sale_huf, net_profit_low_huf, net_profit_exp_huf,
net_profit_high_huf, roi_bp, completed_sales_used, liquidity (`HIGH`,`MEDIUM`,`LOW`,`UNKNOWN`),
est_days_to_sell, reasons_json, missing_inputs_json, review_flags_json.
CHECK: `verdict='PROFITABLE'` ⇒ `completed_sales_used >= 1` (the real minimum is a rule param, ≥ 1 is the DB floor).

No `is_current` flag (would violate immutability): "current" = highest `id` per offer, index
`(offer_id, id DESC)`. An evaluation is only written if `inputs_hash` differs from the latest one.

**rule_params** `IMMUTABLE` — id, engine (`PERSONAL`,`RESALE`), category, params_json, params_hash,
created_at, created_by. Rule *logic* is code (versioned by git, recorded as `code_version`);
rule *parameters* (thresholds) are data. Changing a threshold inserts a new row.

**Implemented (0005, ADR-053):** `personal_evaluations` (offer_id, evaluated_at, verdict,
effective_price_huf, benchmark_median_huf, discount_vs_median_bp, watchlist_relevance,
missing_json, flags_json, result_json) and `resale_evaluations` (offer_id, evaluated_at, verdict,
fee_profile_id, acquisition_cost_huf, expected_sale_huf, net_profit_huf, net_profit_low_huf,
roi_bp, provisional, liquidity, est_days_to_sell, missing_json, flags_json, result_json). Both
IMMUTABLE; CHECK `(verdict = 'MANUAL_REVIEW') = (json_array_length(missing_json) +
json_array_length(flags_json) > 0)`; resale: decided verdicts must carry net_profit_huf.
No rule_params / inputs_hash yet.

## 9. Fees and tax

**fee_profiles** `IMMUTABLE` (new version = new row) — id, platform_id, valid_from, valid_to,
commission_bp, commission_min_huf, commission_cap_huf, fixed_fee_huf, payment_fee_bp,
payment_fixed_huf, listing_fee_huf, default_outbound_shipping_huf, default_packaging_huf,
source_url, note, verified_at (null ⇒ every resale result using it is flagged `UNVERIFIED_FEES`).
Non-overlapping validity per platform is enforced in the service layer + test (SQLite cannot express it).

**tax_profiles** `IMMUTABLE` — id, key (`NONE_SELECTED`,`PRIVATE_OCCASIONAL`,`SOLE_PROPRIETOR`,
`COMPANY`,`CUSTOM`), params_json, verified_at, note. `NONE_SELECTED` or unverified ⇒ results flagged.

**Implemented (0005):** `fee_profiles` STATE (name unique, platform, commission_bp,
commission_min_huf, commission_cap_huf, commission_includes_shipping, fixed_fee_huf,
listing_fee_huf, payment_fee_bp, payment_fixed_huf, outbound_shipping_cost_huf, packaging_huf,
verified, active, note; changes audited). Default profile id in settings `resale.fee_profile_id`;
the tax profile is a settings value `resale.tax_profile` (kind, rate_bp, verified, note).

## 10. User workflow

**watchlists** / **watchlist_items** `STATE` — item targets a product or variant or a text query;
target_price_huf, max_price_huf, acceptable_conditions, required_attrs_json, notify.
**user_profile** lives in `settings` (apparel sizes per size system, pickup location — OPEN-13).

**decisions** `IMMUTABLE` — id, offer_id, decided_at, decision (`IGNORE`,`WATCH`,`BUY_PERSONAL`,
`BUY_RESALE`,`PASS`), personal_evaluation_id null, resale_evaluation_id null, note.

**ai_requests** `STATE` (status only) — id, offer_id, purpose (`RISK_REVIEW`,`ATTRIBUTE_EXTRACTION`,
`MATCH_SUGGESTION`), schema_version, mode (`CLIPBOARD`,`FILE`,`CLI`), prompt_sha256, created_at,
status (`PREPARED`,`ANSWERED`,`REJECTED`,`EXPIRED`), expires_at.
**ai_responses** `IMMUTABLE` — id, ai_request_id, received_at, raw_text (capped 64 KB), valid,
validation_error, parsed_json. Applying a suggestion = a `match_candidates` row with
`method=AI_SUGGESTED` decided by `USER`, or a user-confirmed attribute write — both audited.

**Implemented (migration 0004, ADR-048):** `ai_requests` (request_id unique, offer_id, schema_version,
mode, package_json, prompt_text, prompt_sha256, status PREPARED/ANSWERED/EXPIRED, created_at,
expires_at; IMMUTABLE except status) and `ai_responses` (ai_request_id, received_at, raw_text <= 64 KB,
valid, errors, parsed_json; IMMUTABLE; CHECK parsed_json set iff valid). Every pasted answer is kept.

**notifications** `STATE` (read/delivered flags) — id, created_at, kind, offer_id null,
source_id null, title, body, dedupe_key unique, channel, delivered_at, read_at.

**Implemented (0005):** `watchlists` STATE (name, category, variant_id / product_id /
query_text - at least one, target_price_huf <= max_price_huf, positive prices,
acceptable_conditions, notify, active). `offer_decisions` IMMUTABLE (offer_id, decided_at,
decision WATCH/REJECT/RESTORE/BOUGHT, reason - required for REJECT, note). `notifications` (kind,
title, body, offer_id, dedupe_key unique, created_at; mutable: read_at, telegram_status
NOT_CONFIGURED/SENT/FAILED, telegram_error).

## 11. Inventory and money ledger

**acquisitions** `STATE` — one purchase event (an order), id, platform_id, acquired_at, unit_count,
note. Lets one order with one shipping fee cover several units.

**inventory_items** `STATE` — one row per **physical unit**: id, acquisition_id, variant_id,
offer_id null (where bought), decision_id null, intent (`RESALE`,`PERSONAL`), condition, serial_no,
status (`IN_TRANSIT`,`IN_STOCK`,`LISTED`,`SOLD`,`RETURNED_TO_SELLER`,`RETURNED_BY_BUYER`,
`WRITTEN_OFF`,`PERSONAL_USE`), listed_platform_id, listed_price_huf, listed_at.
Cost basis is **not stored** — it is derived from the ledger (view `v_item_cost_basis`):
acquisition-level costs are allocated equally across its units, remainder HUF to the lowest id
(deterministic, tested).

**transactions** `LEDGER` — id, occurred_at, type (`PURCHASE`,`INBOUND_SHIPPING`,`SALE`,
`PLATFORM_FEE`,`PAYMENT_FEE`,`OUTBOUND_SHIPPING`,`PACKAGING`,`REFUND_RECEIVED`,`REFUND_GIVEN`,
`TAX`,`OTHER`), amount_huf (> 0, always positive), direction (`IN`,`OUT`), acquisition_id null,
inventory_item_id null, platform_id null, reference, note, reverses_id null.
CHECK: exactly one of acquisition_id / inventory_item_id is set (except `OTHER`/`TAX`);
CHECK type ↔ direction (e.g. `SALE`⇒`IN`, fees⇒`OUT`). Positive amount + explicit direction removes
sign-convention bugs.

**Implemented (0005, ADR-051):** `acquisitions` IMMUTABLE except note (acquired_at, seller,
offer_id, unit_count >= 1); `inventory_items` STATE (acquisition_id, title, category, variant_id,
intent RESALE/PERSONAL, condition, status IN_STOCK/LISTED/SOLD/RETURNED_TO_SELLER/WRITTEN_OFF/
PERSONAL_USE, status_changed_at); `transactions` LEDGER (occurred_at, type incl. OTHER_COST /
OTHER_INCOME, direction, amount_huf > 0, acquisition_id xor inventory_item_id, platform, note,
reverses_id unique, no self-reversal; CHECK type <-> direction). `observed_sales` CHECK
`no_own_sales` (ADR-050). Cost basis is computed in `ledger/calc.py`, not stored.

## 12. System

**settings** `STATE` — key PK, value_json, updated_at.
**audit_log** `IMMUTABLE` — id, at, actor (`USER`,`SYSTEM`), entity, entity_id, action,
before_json, after_json. Written for every `STATE` change originated by the user and for merges.

## 13. Indexes (initial)

`listings(source_id, external_id)` U · `listings(product_id)` · `offers(listing_id, variant_key_raw)` U ·
`offers(variant_id, is_active)` · `price_observations(offer_id, observed_at)` U ·
`price_observations(observed_at)` · `observed_sales(variant_id, sold_at)` · `variant_identifiers(id_type, value, source_id)` U ·
`personal_evaluations(offer_id, id)` · `resale_evaluations(offer_id, id)` ·
`observed_sales(variant_id, sold_at)` · `notifications(dedupe_key)` U · `benchmarks(variant_id, basis)` U.

## 14. Volume estimate

4 categories x ~5 sources x ~2 000 offers, checked once a day: ~40 000 observation rows/day,
~15 M/year (~1-1.5 GB). Acceptable for local SQLite with the indexes above; if it grows, old
observations can be compacted to one row per offer-day without changing any benchmark
(benchmarks already sample per offer-day). Decision deferred (OPEN-19). Comfortable for
SQLite. Raw files are the largest item; retention per source (default 30 days, OPEN-12).

## 15. Backups

`dealradar backup` uses the SQLite online backup API → `data/backups/dealradar-YYYYMMDD-HHMM.db`.
Automatic backup before every migration. `data/` is git-ignored.

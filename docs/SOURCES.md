# DealRadar HU — Sources and the Refresh Workflow

Status: v1.0 (2026-11-24). Matches `dealradar/sources/`, `dealradar/services/refresh.py`,
`dealradar/services/sources.py`.

## 1. Source registry

| Key | Name | Access method | Categories | Status | Verified access |
|---|---|---|---|---|---|
| `mock_shop` | Demó bolt (szintetikus) | `MOCK` | all four | demo only | n/a - in-process fixture, no network |
| `mock_shop_2` | Demó bolt 2 (szintetikus) | `MOCK` | all four | demo only | n/a - same catalog, +4 % prices, one synthetic flash sale |
| `mock_market` | Demó apróhirdetés (szintetikus) | `MOCK` | TECH, HOME | demo only | n/a - used-goods ads |

**There is no real source yet.** No real website has been reviewed, and DealRadar does not assume
any site permits automated collection. There is also no real HTTP transport in the code:
`sources/registry.transport_for` refuses every non-MOCK adapter (`ACCESS_NOT_PERMITTED`). The
transport is added together with the first verified real adapter.

Mock sources only run after an explicit demo opt-in (`dealradar demo seed
--i-understand-this-is-synthetic`, or Settings -> Demo data), which writes
`demo.mock_sources_allowed = true` into that database. Health checks and the Overview page warn
while synthetic sources are registered. Use a separate `DEALRADAR_DATA_DIR` for demo data.

## 2. Verification procedure for a real source (before any adapter is written)

1. **Official access first.** Look for an official API, feed or export (affiliate feed, open data,
   public JSON the site documents). Prefer it over HTML.
2. **Terms of service.** Read the current terms; record the date, the URL and the relevant clause in
   `sources.tos_note` / `tos_reviewed_at`. If automated access is prohibited, stop.
3. **robots.txt.** Record the check (`robots_checked_at`, `robots_allows`). The requester also
   checks robots.txt at run time and refuses disallowed paths.
4. **No access controls.** No login, no CAPTCHA, no paywall, no anti-bot challenge. If any exists,
   the source is not used. DealRadar never bypasses them (no proxies, no fingerprint spoofing, no
   CAPTCHA solving, no retry-to-evade).
5. **Politeness budget.** Choose `min_interval_s` (>= 5 s for HTML), `daily_request_cap`, cache TTL.
6. **Document** the source in the table above (access method, what was checked, when), write the
   adapter with golden-fixture tests (no network in tests), and only then set
   `access_review_ok = true` and `status = ACTIVE`.

Re-review: a `BLOCKED` source stays stopped until the user re-checks it and re-enables it with a
note (`services.sources.reactivate_source`, Sources page). Every re-activation is audited.

## 3. Requester rules (`sources/requester.py`, PoliteRequester)

| Situation | Behaviour |
|---|---|
| robots.txt | fetched once per run, disallowed paths raise `ROBOTS_DISALLOWED` |
| throttle | at least `min_interval_s` between requests to the source |
| daily cap | counted across today's runs; reaching it raises `DAILY_CAP_REACHED` |
| timeout / 5xx | at most 3 attempts, exponential backoff 2 s then 4 s |
| 429 | waits `Retry-After` (or the backoff) if <= 60 s and retries within the 3 attempts; longer -> `RATE_LIMITED`, run stops |
| 401 / 403 / 407 / challenge page | `BLOCKED`, never retried, source status set to `BLOCKED` |
| other 4xx | `CLIENT_ERROR`, not retried |
| cache | responses cached per source in `data/cache/<source>/` for the adapter's TTL; a cached response keeps its original fetch time, so it never creates a new observation |

## 4. Refresh workflow (`services/refresh.py`)

Scopes: one source, one category (all active sources that serve it), or all active sources.
Triggered manually: category pages, Overview ("Refresh all sources"), Sources page, or
`dealradar refresh [--source KEY | --category CAT | --all]`.

Per source:
1. **Preflight** - adapter registered, access review done, status ACTIVE/DEGRADED, adapter access
   method equals the reviewed one, demo opt-in for MOCK. Otherwise the run is recorded as FAILED
   with `ACCESS_NOT_PERMITTED` and nothing is fetched.
2. **Fetch** through the requester. Unusable records become `INVALID_RECORD` errors (kept with
   their external ref), never guessed prices.
3. **Per offer:** raw record (hash) -> normalize (category module) -> upsert listing / offer
   (listing keeps a JSON snapshot of the normalized listing) -> match (cascade; a product is
   auto-created only from a valid identifier, ADR-015; a new variant of a matched product is
   created from the category variant key) -> **price observation**.
4. **Duplicates:** an observation with the same offer and fetch time is skipped (cached responses
   keep their fetch time). Unchanged prices at a new fetch time are recorded - "price still X" is
   information (ADR-039).
5. **Evaluate** each offer with a new observation: both engines separately, both results stored.
6. **Notify** (in-app inbox; Telegram if configured): STRONG_DEAL, watchlist target met,
   PROFITABLE (labelled estimate), source BLOCKED / FAILED. Each once per dedupe key.

Recorded: `refresh_jobs` (scope, target, start, finish, status), `source_runs` (counts: requests,
fetched, parsed, failed, new observations, duplicates, retries, cache hits; error kind and summary),
`source_run_errors` (kind, external ref, message). An adapter crash fails only its own run.
Job status: OK (all OK), PARTIAL (some data), FAILED (none).

## 5. Staleness

A source is **stale** when its last OK/PARTIAL run is older than the shortest benchmark freshness
window of the categories it serves (`current_max_age_hours`: FOOD 24 h, TECH/HOME/APPAREL 48 h)
or it never ran. Stale sources are listed on the Overview and Sources pages and in `dealradar health`
and `dealradar sources list`. Benchmarks additionally mark stale current prices (ADR-041).

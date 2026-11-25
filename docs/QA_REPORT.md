# DealRadar HU — QA and Security Audit

Date: 2026-11-24. Scope: the whole application after the user-workflow step (migrations
0001-0005). Auditor: Claude Code. Environment: Windows 11, Python 3.13.3, SQLite 3.49.1,
Streamlit 1.67.0, dependencies exactly as in `requirements.lock.txt` (54 packages; verified
identical to the installed venv).

Every result below comes from a command that was actually run in this audit; nothing is
extrapolated. No new features were added during the audit. The defect fixes are listed in §3.

## 1. Tests executed

| Check | Command | Result |
|---|---|---|
| Unit / integration / UI tests | `python -m pytest` (caches cleared first) | **708 passed, 0 failed, 0 skipped, 0 errors** (98.95 s) |
| Lint | `ruff check .` | passed, no findings |
| Formatting | `ruff format --check dealradar tests` | 185 files formatted |
| Types | `mypy` (strict on the configured packages) | no issues in 144 source files |
| Dependency consistency | `pip check` | no broken requirements |
| Dependency vulnerabilities | `pip-audit -r <pip freeze> --no-deps --disable-pip -s osv`, run from a separate throw-away venv | **54 packages, 0 known vulnerabilities, 0 skipped** (OSV database at audit time) |
| Real browser | Playwright against `dealradar ui` on synthetic demo data | Overview, Offer details (price chart), Tech page refresh button: rendered and worked; 0 app console errors (see L-9) |
| Startup / shutdown | `dealradar ui --port 8511`, `netstat`, stop, `dealradar health` | listens on **127.0.0.1 only**; after stop the port is closed, writer lock acquirable, integrity ok |
| Backup / recovery | damaged a copy of a populated DB, `health`, `db backup`, manual restore | detected, refused, restored (after fixes D-3/D-4); automated in `tests/test_backup_recovery.py` |
| CLI end to end | `db upgrade`, `demo seed` (refused without the flag, then ran), `sources list`, `health`, `notify test` | all as documented |
| Data invariants on a populated DB | SQL checks on the demo DB (11 days, 3 mock sources) | see §2.3, 2.4, 2.6 |

Tests per file: pricing_benchmarks 55 · hu_parse 52 · costs 46 · ledger_calc 42 · claude_bridge 39 ·
units_identifiers 37 · engine_resale 37 · normalize_generic 35 · ui_app 34 · category_apparel 32 ·
engine_personal 31 · pricing_stats 28 · architecture 21 · category_tech 19 · category_food 19 ·
integrity 18 · money 17 · ledger_service 15 · category_persistence 13 · requester 12 ·
category_home 11 · pricing_service 10 · analysis_service 10 · refresh 9 · health_cli 9 ·
evaluation_service 9 · workflow 8 · repositories 8 · notify 8 · migrations 8 · docs_sync 4 ·
config_logging 4 · lock 3 · migration_constraints 2 · isolation 2 · backup_recovery 1.

**Tests passed: 708. Tests failed: 0.** (Intermediate runs during the audit failed only in tests
that were being written; they were fixed in the test or, where the code was wrong, in the code -
see §3.)

## 2. Audit areas

| # | Area | How it was checked | Result |
|---|---|---|---|
| 1 | Category modules | 94 category tests (parsing, normalization, matching rules, persistence); architecture test: categories never import each other, no `if category ==` outside them | OK |
| 2 | Personal and Resale engines | 68 engine tests + 46 cost tests with hand-computed HUF cases, verdict boundaries, missing-input matrices; architecture: pure, independent, no combined score | OK |
| 3 | Database integrity | CHECK constraints and ORM mutability guards (18 integrity + 2 constraint-survival tests); migrations 0001-0005 up/down; on the demo DB: `foreign_key_check` empty, `integrity_check` ok, 0 MANUAL_REVIEW rows without reasons | OK |
| 4 | Matching accuracy | matching tests per category; demo DB: 14 automatic matches, all by GTIN/MPN/style code, all correct (same brand, model and variant; sizes kept as separate variants); 6 ambiguous listings (1 TB vs 2 TB, 500 g vs 1 kg, no identifier) went to review, none auto-matched | OK - see L-4 |
| 5 | Historical price calculations | 93 pricing tests (offer-day sampling, MAD outliers, NO_DATA / INSUFFICIENT_DATA / STALE, variant isolation); price chart verified in the browser | OK |
| 6 | Financial formulas | 46 cost tests, 42 ledger-calculation tests incl. the cash-flow identity on 25 random ledgers, worked examples in docs checked by `test_docs_sync`; actual vs. estimated kept apart (separate functions, separate UI boxes; UI test) | OK |
| 7 | Missing or invalid data | unknown -> MANUAL_REVIEW tests; invalid purchases rejected; sale/transaction dates checked (D-2); unusable records stored as INVALID_RECORD errors, never guessed | Fixed D-2 |
| 8 | Prompt injection | 39 bridge tests (fenced untrusted text, delimiter spoofs, code fences, hidden characters, links); UI rendering of untrusted text | Fixed D-1 |
| 9 | AI response validation | strict schema `dealradar.analysis.v1` (extra fields forbidden, no BUY, no numeric fields), semantic rejections; test that an accepted answer changes no decision data | OK |
| 10 | Source adapter restrictions | 12 requester tests (robots, throttle, Retry-After, 401/403/407 and challenge pages = BLOCKED without retry, daily cap, cache); preflight refuses unreviewed / mismatched / non-opted-in sources; no real transport exists (`transport_for` refuses non-MOCK); architecture: `sources` cannot import db/services/engines | OK |
| 11 | Local startup / shutdown | see §1 | OK |
| 12 | Dependency security | see §1 (pip-audit) | OK - see L-6 |
| 13 | Error handling | adapter crash fails only its own run (test); evaluation errors do not stop a refresh; failed writes roll back (test: failed sale leaves no rows); UI forms show ValueErrors instead of crashing | OK |
| 14 | Backup and recovery | see §1 | Fixed D-3, D-4; procedure documented |
| 15 | UI functionality | 34 AppTest tests (every page on an empty and on a demo DB, refresh button, two engine lists, actual vs. estimated, rejection needs a reason, Markdown escaping) + browser check | OK - see L-9 |
| 16 | Telegram optionality | without credentials nothing touches the network (test with a poster that fails if called); configured but unreachable: refresh succeeds, notifications kept and marked FAILED, token never in stored errors (tests); architecture: no Telegram library, only `services/notify.py` | Fixed D-5 (test isolation) |
| 17 | No paid API dependencies | runtime deps: SQLAlchemy, Alembic, Pydantic, pydantic-settings, Streamlit (all free OSS); grep for API keys / paid scraping services / proxies: none; Claude only via manual copy-paste; Telegram Bot API is free | OK |

## 3. Defects found and fixed in this audit

| ID | Severity | Defect | Fix | Proof |
|---|---|---|---|---|
| D-1 | High (security) | Untrusted text (listing title, URL, source error message, Claude summary/evidence) was passed to Markdown-rendering widgets (`st.subheader`, `st.caption`, `st.write`). A title like `![x](http://tracker/...)` would make the browser load an external image (leaks that the user viewed it, and their IP); links, colour directives and LaTeX would render. Verified that such a title survives normalization unchanged. | `ui/views/widgets.plain()` backslash-escapes Markdown / directive / LaTeX characters; used for every untrusted string in Markdown widgets (offer, analysis, refresh messages). Tables, selectboxes and `st.text` were already plain. | `test_untrusted_listing_text_is_not_rendered_as_markdown` |
| D-2 | Medium | `record_sale` accepted a sale dated before the purchase; `record_item_transaction` accepted future dates. Both would distort realized results and days-to-sell. | Both rejected with a clear message. | `test_sale_dates_must_be_plausible` |
| D-3 | High (data safety) | `dealradar health` reported `db_connection OK` on a damaged database (the check never ran SQLite's integrity check). | `PRAGMA quick_check` added to the existing check. | `test_backup_restore_round_trip` |
| D-4 | High (data safety) | `dealradar db backup` (and the backup before every upgrade) copied a damaged database without noticing, producing a "backup" that cannot be restored. | The copy is verified with `quick_check`; a failed copy is deleted and an error stops the caller (so an upgrade does not proceed on a damaged DB). | same test |
| D-5 | Medium (test isolation) | Tests read the developer's `.env`. With real Telegram credentials there, refresh tests would have sent real messages and the "works without Telegram" test would fail. Only one test file blocked network access. | Suite-wide autouse fixture: Telegram variables emptied (environment beats `.env`), outbound connections and DNS refused (loopback allowed). | `tests/test_isolation.py` |
| D-6 | Low (usability) | Times were shown in UTC without saying so (CLI `sources list`, Sources page, deal lists, inbox). | "UTC" labels added. | manual check |
| D-7 | Low (docs) | No restore procedure was documented. | README "Backup and restore", the procedure is the one the test executes. | README |

No architectural changes were made. D-3/D-4 change the behaviour of two existing checks (they
can now fail); D-5 changes only the test harness.

### 3a. Follow-up (2026-11-25, Hungarian UI and UI kit)

Found while checking the redesigned UI in a real browser; fixed and covered by tests:

| ID | Severity | Defect | Fix | Proof |
|---|---|---|---|---|
| D-8 | High | Selectboxes identify options by their label. Two offers with the same title (same RAM in two shops) made "Részletek" open the other offer; the same would have hit inventory items of a multi-unit purchase (a sale could be booked on the wrong unit). | Unique labels everywhere (`unique_labels()`, item / transaction ids in labels). | `test_details_open_the_chosen_offer_even_with_equal_titles` |
| D-9 | Medium | The deal lists' "price incl. delivery" column showed the item price without delivery. | Column uses the Personal evaluation's effective price; the Resale list labels the asking price as such. | browser check |
| D-10 | Low | Offer page showed an empty table when an offer had no observation yet. | Table hidden; empty-state text only. | browser check |

Test run after the follow-up (2026-11-25, caches cleared): **750 passed, 0 failed, 0 skipped**; ruff, ruff format, mypy (145 files) and pip check clean. Pages checked in a real browser: Áttekintés, Ajánlat részletei (chart, tabs), Beállítások, Készlet és eredmény.

## 4. Unresolved defects

None known. All confirmed defects above are fixed and covered by tests.

## 5. Security concerns (residual risk)

- **S-1 Untrusted text, future pages.** The Markdown escaping (D-1) is applied per call site.
  A new page that passes listing text to a Markdown widget without `plain()` would reintroduce the
  issue. Recommendation: a static test that flags `st.write/subheader/caption/markdown` calls with
  non-literal arguments in `ui/` (not added: it is a new check, not a defect fix).
- **S-2 Listing URLs.** Offer pages show the source URL as escaped text (not a link). When real
  sources exist the user opens URLs manually; they are not validated against the source's domain.
- **S-3 Telegram token at rest.** The token lives in `.env` in plain text (standard for local
  apps; `.env` is git-ignored). It is never shown in the UI or logs and is scrubbed from stored
  errors (tested). Messages go to Telegram's servers: they contain offer titles and prices only.
- **S-4 Local UI without authentication.** Streamlit is bound to 127.0.0.1 and telemetry is off
  (verified). Any local user/process on the PC can open the UI; acceptable for a single-user PC.
- **S-5 Claude copy-paste.** The prompt contains listing text from third parties; prompt-injection
  defences are in place and the answer cannot change decisions, but the user should not paste the
  prompt into a Claude session that has tools or connectors enabled (CLAUDE.md rule 16).

## 6. Known limitations

- **L-1 No real source.** Only synthetic MOCK sources exist; real data needs the verification
  procedure in docs/SOURCES.md §2 and the user's choice of sources (OPEN-2). There is no real HTTP
  transport yet.
- **L-2 No PROFITABLE resale verdict is possible yet without your input:** a verified fee profile,
  a tax profile and enough completed sales are required (by design). On the demo data all resale
  results are MANUAL_REVIEW or NOT_APPLICABLE.
- **L-3 Manual ingestion and review UI are missing:** no CSV import / "add offer by hand", no match
  review queue page (open candidates exist in the DB), no UI to enter `observed_sales`.
- **L-4 Matching is only as good as identifiers.** Listings without GTIN/MPN/style code stay
  unmatched or in review; fuzzy matching is not tuned on real data.
- **L-5 Scalability.** Deal lists load all observations and evaluations each time (fine for
  thousands of rows, not for millions). Every evaluation run is stored (no `inputs_hash` dedupe).
- **L-6 Dependency audit** is a point-in-time check against OSV; the lock file is not hash-pinned
  (pip-audit warned about this). Re-run before upgrades.
- **L-7 Engine thresholds and risk assumptions** are proposals (OPEN-22), not measured values.
- **L-8 Tax treatment** must be confirmed with an accountant (OPEN-7); the app only applies the
  profile the user enters.
- **L-9 Browser console** shows two 404s when a page is opened by deep URL (e.g. `/tech`):
  Streamlit itself probes `/tech/_stcore/health` and `/tech/_stcore/host-config` before falling
  back. Harmless, not caused by the app.
- **L-10 The full-page screenshot** of Streamlit pages only captures the sidebar (Streamlit scrolls
  an inner container); page content was verified with accessibility snapshots and element
  screenshots instead.
- **L-11 Times are stored and shown in UTC.**

## 7. Recommended next steps

1. **Accept or reject** this step and answer the blocking open decisions: OPEN-2 (which real
   sources), OPEN-3 / OPEN-23 (your resale platforms and their current fees), OPEN-7 (tax).
2. **First real source**: pick one with an official API/feed or clearly permitted access, run the
   SOURCES.md §2 procedure, then add the transport + adapter with golden-fixture tests.
3. **Manual ingestion and review** (L-3): CSV import, "add offer by hand", match review queue,
   completed-sale entry - these let the app be useful before any automated source exists.
4. **Hardening**: the static UI check from S-1; hash-pinned lock file; `inputs_hash` to avoid
   storing identical evaluations; snapshot / cache pruning (OPEN-12).
5. **Real-data calibration**: after a few weeks of observations, review thresholds (OPEN-20/22)
   and the rejection-feedback page for systematic WRONG_MATCH / TOO_EXPENSIVE patterns.

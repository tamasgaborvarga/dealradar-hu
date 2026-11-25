# DealRadar HU

Local-first deal discovery for the Hungarian market (HUF). Finds unusually good offers in four
categories — **Tech**, **Clothing, shoes & sport**, **Food**, **Home** — and evaluates each offer
with two independent engines:

- **Personal Deal Engine** — is this a genuinely good purchase for my own use?
- **Resale Deal Engine** — can this be resold at a realistic net profit, based on *completed* sales?

The two results are never merged into one score.

> **Status:** the full local workflow is implemented (2026-11-24, awaiting user acceptance):
> manual refresh (one source / one category / all), price history, two independent evaluation
> engines with separate Personal and Resale lists, watchlists, offer details with price-history
> charts, decisions and rejection feedback, inventory and sales ledger with realized profit,
> manual Claude analysis, in-app notifications and optional Telegram.
> **No real website is connected yet** - only synthetic demo sources (docs/SOURCES.md). A real
> source is added only after its permitted access method is verified and documented.
> See [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) and
> [docs/QA_REPORT.md](docs/QA_REPORT.md).
>
> Existing databases: run `dealradar db upgrade` once to apply migrations up to `0005`.

## Language

The app (UI, CLI output, notifications) is Hungarian; code and developer documentation are
English (ADR-056). Evaluations stored before the Hungarian UI keep English reason texts until the
offer is re-evaluated ("Újraértékelés most" on the offer page, or the next refresh).

## Requirements

- Windows 10/11 (tested on Windows 11), macOS or Linux
- Python **3.12 or newer** (tested with 3.13.3)
- No accounts, API keys or paid services

## Installation (Windows, Git Bash or PowerShell)

Run every command from the project folder.

```bash
cd "C:\Users\<you>\Claude Code\DealRadar-HU"

# 1. Create a virtual environment
python -m venv .venv

# 2. Install the app with development tools
#    Git Bash:
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e ".[dev]"
#    PowerShell:
#    .venv\Scripts\python -m pip install --upgrade pip
#    .venv\Scripts\python -m pip install -e ".[dev]"

# Optional: install the exact versions that were tested
.venv/Scripts/python -m pip install -r requirements.lock.txt
```

If Hungarian characters look broken in the console, set `PYTHONUTF8=1`
(Git Bash: `export PYTHONUTF8=1`; PowerShell: `$env:PYTHONUTF8 = "1"`).

## First start

```bash
# 3. Create the database (explicit step — the app never migrates on its own)
.venv/Scripts/dealradar db upgrade

# 4. Check that everything is in order (expects "Overall: OK")
.venv/Scripts/dealradar health

# 5. Start the UI — opens on http://127.0.0.1:8501 (this computer only)
.venv/Scripts/dealradar ui
```

Stop the UI with `Ctrl+C`. Use another port with `dealradar ui --port 8502`.

(PowerShell: replace `.venv/Scripts/` with `.venv\Scripts\`. If the venv is activated —
`.venv\Scripts\activate` — plain `dealradar ...` works.)

## Commands

| Command | What it does |
|---|---|
| `dealradar db upgrade` | Backs up the existing database (if any), then migrates to the latest schema |
| `dealradar db status` | Shows schema state; exit code 1 if not up to date |
| `dealradar db backup` | Writes a consistent backup to `data/backups/` |
| `dealradar health` | Runs health checks; exit code 1 on any failure |
| `dealradar ui [--port N]` | Starts the Streamlit UI bound to 127.0.0.1 |
| `dealradar refresh [--all \| --category TECH \| --source KEY]` | Manual refresh with progress; exit 1 if every source failed |
| `dealradar sources list` | Sources with last successful refresh and staleness |
| `dealradar demo seed --i-understand-this-is-synthetic [--days N]` | Registers the synthetic mock sources and builds N days of fake history |
| `dealradar notify test` | Sends a Telegram test message (only if configured) |

## Trying it with demo data

Demo prices are synthetic. Keep them out of your real database by using a separate data folder:

```bash
export DEALRADAR_DATA_DIR=data-demo          # PowerShell: $env:DEALRADAR_DATA_DIR = "data-demo"
.venv/Scripts/dealradar db upgrade
.venv/Scripts/dealradar demo seed --i-understand-this-is-synthetic
.venv/Scripts/dealradar ui
```

The app shows a "Demo mode" warning while synthetic sources exist.

## Daily workflow

1. **Overview** - *Refresh all sources* (or refresh one category on its page). Progress, new
   observations and every source error are shown; blocked sources stop and are flagged.
2. **Category pages** - two separate lists: *Personal deals* and *Resale deals* (estimates).
   *Open details* on any offer.
3. **Offer details** - price-history chart (asking prices), both evaluations with reasons and
   missing inputs, your decision (watch / reject with a reason / restore), *I bought this*,
   Claude analyses for the offer.
4. **Inventory & results** - record sales with their real fees and costs, add costs, change
   statuses, reverse a wrong entry. Realized profit uses only recorded transactions; estimates
   are shown separately on the Overview and never added to it.
5. **Watchlists** - target prices; a met target is notified. **Rejected offers** - feedback by
   reason. **Settings** - your resale fee profiles and tax profile (no built-in fees), Telegram.

## Claude analysis (optional, manual)

Page **System -> Claude analysis**: pick an offer, click *Prepare analysis package*, copy the prompt
(copy button on the box, or *Download prompt*), click *Open Claude (claude.ai)*, paste it into a new
chat, then paste Claude's JSON answer back and click *Validate and save*. Invalid answers are stored
as rejected with reasons. No API key is used and nothing is sent automatically; the answer is a
second opinion only and never changes prices, matches or verdicts. Everything works without it.

## Configuration

Optional environment variables (or a `.env` file; see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DEALRADAR_DATA_DIR` | `data` (relative to the current folder) | Database, logs, backups |
| `DEALRADAR_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DEALRADAR_LOCK_TIMEOUT_S` | `10` | Seconds a writer waits for the single-writer lock |
| `DEALRADAR_TELEGRAM_BOT_TOKEN` | not set | Optional. Bot token from @BotFather (free Bot API) |
| `DEALRADAR_TELEGRAM_CHAT_ID` | not set | Optional. Your chat id; both must be set to enable Telegram |

Telegram is optional: without it every notification still appears in the app. Messages are plain
text; the token is never shown in the UI or logs. Test with `dealradar notify test`.

Files created at runtime (all inside the data folder, git-ignored):
`dealradar.db` (SQLite, WAL mode), `dealradar.lock`, `logs/dealradar.jsonl`, `backups/`,
`cache/` (polite-request cache per source).

## Backup and restore

`dealradar db backup` writes a copy to `data/backups/` and verifies it with SQLite's integrity
check; a damaged database is refused instead of being copied. `dealradar db upgrade` takes a
backup first. `dealradar health` runs the integrity check too (`db_connection ... integrity=ok`).

To restore (tested in `tests/test_backup_recovery.py`):
1. Stop the UI (`Ctrl+C`) and any running `dealradar` command.
2. In the data folder, delete `dealradar.db-wal` and `dealradar.db-shm` if they exist.
3. Copy the chosen `backups/dealradar-<date>-<label>.db` over `dealradar.db`
   (keep the damaged file elsewhere if you want to inspect it).
4. Run `dealradar db status` (upgrade if it says so) and `dealradar health`.

## Development

```bash
.venv/Scripts/python -m pytest             # tests (no network)
.venv/Scripts/ruff check .                 # lint
.venv/Scripts/ruff format --check dealradar tests
.venv/Scripts/mypy                         # strict type checking
```

New schema change: edit models → `alembic revision --autogenerate -m "..."` → review the file and
fill in its "Reviewed by" line → `dealradar db upgrade`. `tests/test_migrations.py` fails if models
and migrations differ.

## Principles

- Runs on your own PC. SQLite. No paid APIs, proxies, feeds, VPS or subscriptions.
- Recommends only — never buys, never logs in to shops, never messages sellers.
- Respects robots.txt and website terms; never bypasses anti-bot or access controls.
- Unknown or uncertain data → `MANUAL_REVIEW`. Nothing is invented.
- Claude (Pro subscription, no API) only for manually started, schema-validated, advisory analysis.

## Documentation

| Document | Content |
|---|---|
| [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) | Requirements, engines, categories, risks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Modules, dependency rules, data flow |
| [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) | Tables, constraints, mutability classes |
| [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) | Phases, status, open items |
| [docs/DECISIONS.md](docs/DECISIONS.md) | ADRs and open decisions |
| [docs/ENGINE_FORMULAS.md](docs/ENGINE_FORMULAS.md) | Every engine formula and default threshold; ledger formulas (§4) |
| [docs/SOURCES.md](docs/SOURCES.md) | Source registry, access verification procedure, refresh workflow |
| [docs/QA_REPORT.md](docs/QA_REPORT.md) | QA and security audit results |
| [docs/REVIEW_2026-11-24.md](docs/REVIEW_2026-11-24.md) | Architecture review findings → fixes |
| [CLAUDE.md](CLAUDE.md) | Working rules for Claude Code in this repo |

## Disclaimer

Resale estimates depend on user-entered fee and tax profiles and on completed-sale evidence;
they are estimates, not promises. Tax and legal
treatment of resale activity in Hungary must be verified with an accountant.

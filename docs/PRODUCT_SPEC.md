# DealRadar HU — Product Specification

Status: v0.2 (2026-11-24) — revised after architecture review (`REVIEW_2026-11-24.md`). Requirements unchanged by Phase 1; implementation status is tracked in `DEVELOPMENT_ROADMAP.md`.
Open items are marked **[OPEN-n]** and collected in §10 and in `DECISIONS.md`.

---

## 1. Purpose

DealRadar HU is a single-user, local-first desktop tool that finds unusually good offers on the
Hungarian market (HUF) and evaluates each relevant offer twice, independently:

| Engine | Question it answers | Output |
|---|---|---|
| **Personal Deal Engine** | "Is this a genuinely good purchase *for me to use*?" | `personal_verdict` + explanation |
| **Resale Deal Engine** | "Can this be bought and resold *at a realistic net profit*?" | `resale_verdict` + net-profit range + liquidity |

The two results are stored, displayed and filtered separately. **There is no combined score.**

The system *recommends*. It never buys, never logs in to shops on the user's behalf, never
places orders and never contacts sellers automatically.

## 2. Users and usage pattern

- One user, one Windows PC (current dev machine: Windows 11, Python 3.13 installed).
- App runs only while the PC is on. Collection happens on demand or on a local schedule.
- Claude Pro subscription is available; **no Anthropic API key and no API billing.**
  Claude analysis is always started manually by the user (see §6).

## 3. Categories

Four category modules, equal priority in the finished product. Each module owns its attribute
schema, normalization rules, matching keys and pricing method.

| Module | Scope | Primary comparison unit | Typical matching key | Hard parts |
|---|---|---|---|---|
| `tech` | CPU, GPU, RAM, SSD, laptop, monitor, electronics | price per item | manufacturer part number (MPN), EAN/GTIN, exact model + config | laptop configs (same name, different RAM/SSD); used vs. new; HU vs. imported warranty |
| `apparel` | clothing, sneakers, sportswear, sports equipment | price per item **per size** | brand + style code (e.g. sneaker SKU) + size + colour | sizes and size systems (EU/US/UK); counterfeits; seasonal pricing; availability per size |
| `food` | packaged food, groceries, bulk | **unit price** (HUF/kg, HUF/l, HUF/piece) | EAN/GTIN; brand + product + pack size | multipacks; "Clubcard/app-only" prices; best-before date; promo-flyer validity periods |
| `home` | appliances, furniture, kitchen, garden, DIY | price per item (+ unit price for consumables, e.g. HUF/m², HUF/l) | MPN/EAN; model number | bulky delivery cost; assembly; energy class; very sparse used-market data |

## 4. Functional requirements

### 4.1 Source collection
- FR-1 Sources are registered in a **source registry** with: access method (official API / feed /
  public HTML / manual import / user-entered), robots.txt result, ToS review note, review date,
  rate limit, enabled flag. A source cannot be enabled without a recorded access review.
- FR-2 Collectors respect robots.txt, rate limits and `Retry-After`; identify with an honest
  User-Agent; never use login, CAPTCHA solving, fingerprint spoofing, rotating IPs or proxies.
- FR-3 A collector that is blocked (403/429/CAPTCHA page) **stops and marks the source
  `BLOCKED`**; it does not retry with evasion.
- FR-4 Manual import is a first-class source: CSV upload, pasted URL + user-entered price,
  user-entered completed sale. This is the fallback for every source that cannot be collected.
- FR-5 Every collected record keeps its raw payload (or a hash + excerpt) and `fetched_at`,
  so every number shown in the UI can be traced back to its origin.

### 4.2 Normalization
- FR-6 Prices converted to integer HUF (gross, VAT-inclusive as displayed to consumers).
  Foreign-currency offers are stored in original currency + the FX rate used + its date.
- FR-7 Shipping cost, condition (new / open-box / refurbished / used + grade), seller type
  (retailer / marketplace seller / private), warranty months and warranty type are separate fields.
  Unknown = `NULL`, never a guessed default.
- FR-8 Food offers get pack size + unit parsed into a canonical unit (g→kg, ml→l). Parsing
  failures → `MANUAL_REVIEW`, not a guess.

### 4.3 Product matching
- FR-9 Identity has two levels: **product** (model/style) and **variant** (the 1:1 comparable unit:
  laptop configuration, apparel size, food pack size). A listing (page/ad) is matched to a product;
  each of its **offers** (one per size/pack/config shown) is resolved to a variant by the category
  module. Every match records method (`gtin`, `mpn`, `style_code`, `rule`, `fuzzy`, `user`,
  `ai_suggested`) and confidence. Products are auto-created only from offers carrying a valid identifier.
- FR-10 Only `gtin`, `mpn`, `user` and deterministic `rule` matches above a category-specific
  threshold may feed benchmarks automatically. `fuzzy` and `ai_suggested` matches require user
  confirmation before they influence any price statistic.
- FR-11 Wrong matches must be reversible (unmatch → benchmarks and evaluations recomputed);
  duplicate products can be merged.

### 4.4 Price history and benchmarks
- FR-12 Every check of an offer is stored as an immutable **price observation** - also when the
  price did not change - with source, condition, availability and delivery cost. Periods without
  a check (PC off) are *unknown*, never filled. Completed sales are stored separately.
- FR-13 Benchmarks per variant x condition group x channel (RETAIL / SECONDHAND / FLYER): median,
  trimmed median, quantiles, trimmed mean, delivery and landed price, lowest current price,
  confidence and an explicit NO_DATA / INSUFFICIENT_DATA / STALE status (ARCHITECTURE.md §6).
  Loyalty-only and multi-buy prices are flagged, not mixed in silently.
- FR-14 A benchmark with too few observations or stale data is flagged `INSUFFICIENT_DATA`,
  and evaluations depending on it fall back to `MANUAL_REVIEW`.
- FR-15 Fake-discount detection: the shop's "was" price is never trusted as a benchmark.
  The system compares against its *own* observed history.

### 4.5 Personal Deal Engine
- FR-16 Inputs: offer price incl. shipping, benchmark set, condition, warranty, seller type,
  user watchlist (target price, required specs, acceptable conditions), category rules.
- FR-17 Output verdicts: `STRONG_DEAL`, `GOOD_DEAL`, `FAIR_PRICE`, `NOT_A_DEAL`,
  `MANUAL_REVIEW`. Plus: discount vs. each benchmark, reasons list, blocking flags.
- FR-18 Hard rules (deterministic, cannot be overridden by AI):
  missing price, unmatched product, `INSUFFICIENT_DATA` benchmark, unknown condition on a
  non-new item → `MANUAL_REVIEW`.

### 4.6 Resale Deal Engine
- FR-19 Net profit = expected realized sale price
  − purchase price − inbound shipping − platform fee − payment fee − outbound shipping
  − packaging − expected return/defect cost − holding cost − tax effect (if configured).
  All fee and cost parameters live in versioned, user-editable **fee profiles** per platform.
- FR-20 **Expected sale price must come from completed sales only**: the user's own sales (from the
  ledger) and observed completed sales (a source that publicly shows final prices, or a sale the user
  reports). Completed sales and asking prices are stored in different places. Asking prices and
  disappeared ads (*not* proof of sale) are shown as context only and cannot influence the profit
  calculation. Minimum number of completed sales for `PROFITABLE` is a setting **[OPEN-15]**.
- FR-21 Output: `PROFITABLE`, `MARGINAL`, `NOT_PROFITABLE`, `MANUAL_REVIEW`, `NOT_APPLICABLE`;
  net-profit as a low/expected/high range; ROI; estimated days-to-sell; liquidity class; reasons.
- FR-22 `NOT_APPLICABLE` by default for: food (resale is regulated — see §7), any category the
  user disables for resale, and items with brand/counterfeit risk flags the user has not cleared.
- FR-23 Minimum profit thresholds (absolute HUF and %) are user settings. **[OPEN-6]**

### 4.7 Liquidity estimation
- FR-24 Liquidity class (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`) and days-to-sell estimate derived only from
  completed-sale evidence counts over time and the user's own sell-through history.
  No evidence → `UNKNOWN` → resale verdict cannot exceed `MANUAL_REVIEW`.

### 4.8 Manual Claude analysis
- FR-25 User selects an offer and clicks "Prepare Claude analysis". The app builds a prompt
  bundle (task, fixed instructions, sanitized offer data fenced as untrusted, required JSON schema).
- FR-26 User runs it in Claude (claude.ai chat, or the sandboxed CLI mode — **[OPEN-1]**)
  and pastes/imports the JSON answer back. One offer per request (Pro usage limits).
- FR-27 The answer is validated against a strict Pydantic schema. Invalid → rejected, stored as failed.
- FR-28 AI output is **advisory only**: it may add qualitative notes, risk flags, suggested
  match candidates or attribute extraction for the user to confirm. It can never change a
  price, a fee, a benchmark, a verdict produced by a hard rule, or mark a match confirmed.

### 4.9 Decisions, inventory, transactions
- FR-29 User records a decision per offer: `IGNORE`, `WATCH`, `BUY_PERSONAL`, `BUY_RESALE`, `PASS`,
  with a note. Decisions are the training signal for tuning thresholds later.
- FR-30 Inventory: one record per physical unit, grouped by acquisition (one order may contain
  several units sharing shipping); status `IN_TRANSIT`, `IN_STOCK`, `LISTED`, `SOLD`,
  `RETURNED_TO_SELLER`, `RETURNED_BY_BUYER`, `WRITTEN_OFF`, `PERSONAL_USE`. Cost basis is derived
  from the ledger, never typed in twice.
- FR-31 Transactions: purchases, sales, fees, shipping, returns — the ledger from which realized
  profit and the user's own completed-sale evidence are computed.

### 4.10 Notifications
- FR-32 In-app inbox (always). Optional free external channel **[OPEN-4]**.
- FR-33 Notify only on: watchlist hit, `STRONG_DEAL`, `PROFITABLE`, source `BLOCKED`, collection failure.
  Rate-limited, deduplicated per offer.

### 4.11 UI (Streamlit)
Pages: Dashboard (new candidates per category, two columns: Personal / Resale) · Offer detail
(both evaluations side by side, evidence, history chart) · Watchlists · Matching review queue ·
Manual review queue · Claude analysis (prepare / import) · Inventory & transactions · Sources
(registry, run log, health) · Settings (fee profiles, thresholds).

## 5. Non-functional requirements

- NFR-1 Zero recurring cost. No paid APIs, proxies, feeds, VPS, SaaS.
- NFR-2 Local data only (SQLite file + raw snapshot folder); backups are a file copy.
- NFR-3 Deterministic, reproducible evaluations: each evaluation stores code version, rule-parameter
  version and a snapshot (+hash) of the inputs it used, so a past verdict can be explained later.
- NFR-4 Business-critical calculations (fees, net profit, unit price, benchmarks, verdict rules)
  have unit tests with explicit HUF examples, including rounding.
- NFR-5 Polite collection: default ≤ 1 request / 5 s per host, daily caps per source.
- NFR-6 No secrets in the repo. `.env` (git-ignored) for an optional SMTP credential.
- NFR-7 The UI listens on 127.0.0.1 only and sends no usage telemetry.
- NFR-8 Personal data minimization: private sellers stored only as a salted hash, no contact data.

## 6. Claude integration model

Constraint: Claude Pro, no API. Three permitted modes, all user-initiated:

1. **Copy-paste (baseline, always available):** app produces a prompt text + schema; user pastes
   into claude.ai, copies the JSON back into the app.
2. **File hand-off:** app writes `data/ai_exchange/<id>.prompt.md`; the user pastes it into a
   claude.ai chat and saves/pastes the JSON answer back. **An interactive Claude Code session must
   not be used** for this: it has shell and file tools, and listing text is untrusted.
3. **Sandboxed local CLI (optional, [OPEN-1]):** a button runs `claude -p` with no tools, no MCP
   servers, an empty temporary working directory and a JSON schema for the output. One click per
   analysis; counts against Pro usage limits. Enabled only after a recorded test on this PC;
   otherwise modes 1–2 remain.

Prompt-injection defence: listing text is wrapped in clearly delimited data blocks, stripped of
HTML/control characters, length-capped; instructions state the content is untrusted data; the
response schema contains no free-form "action" fields; validation rejects extra fields.

## 7. Legal, tax and compliance assumptions (to be verified — not legal advice)

These must be confirmed by the user (and an accountant for tax) before the Resale engine is used
for real money. The app stores the chosen configuration; it does not decide legal status.

- **Website access:** each source's ToS and robots.txt are reviewed and recorded per source.
  Many retailers and classifieds sites restrict automated access in their terms; such sources stay
  manual-import only.
- **Resale and tax status:** occasional private resale vs. systematic, profit-oriented resale
  (which in Hungary generally requires a business form, e.g. sole proprietorship) have different
  tax treatment. The app models tax as a configurable profile (`NONE_SELECTED`, `PRIVATE_OCCASIONAL`,
  `SOLE_PROPRIETOR`, `COMPANY`, `CUSTOM`) and labels results "tax profile: X, unverified" until the user confirms.
- **Platform reporting:** EU DAC7 rules make online platforms report sellers above certain
  transaction thresholds to tax authorities. Relevant to any marketplace-based resale.
- **Food resale:** selling food generally falls under food-safety registration rules; resale
  engine defaults to `NOT_APPLICABLE` for food. **[OPEN-5]**
- **Consumer returns:** buying with the intent to return if unsold must not be modelled as a
  strategy. Return-risk cost models *buyer* returns on the user's sales only.
- **Price-reduction rules:** EU rules (Omnibus) require advertised "previous price" to reflect the
  lowest price of a prior period; still, the app relies only on its own observed history (FR-15).

## 8. Out of scope

Automatic purchasing, cart automation, auto-messaging sellers, account logins to shops,
CAPTCHA handling, proxies, multi-user, cloud hosting, mobile app, price prediction ML (later
phase at most), any paid data source.

## 9. Success criteria (v1)

- At least one enabled, access-reviewed source per category, plus manual import for all four.
- For a matched tech product with ≥ N observations, Personal verdict reproducible from stored inputs.
- Resale verdict never `PROFITABLE` without completed-sale evidence (enforced by test).
- Every `MANUAL_REVIEW` shows the concrete missing input(s).

## 10. Identified gaps, risks and contradictions

### 10.1 Missing requirements
1. Which concrete sources per category are wanted/allowed (no list given). **[OPEN-2]**
2. Resale channels the user will actually sell on (determines fee profiles). **[OPEN-3]**
3. Tax status for resale. **[OPEN-7]**
4. Definition of "unusually good": thresholds per category (e.g. ≥15 % below 90-day median?). **[OPEN-6]**
5. Collection frequency and whether the PC is expected to run unattended. **[OPEN-8]**
6. Used-goods handling for personal purchases (accept used tech? used apparel?). **[OPEN-9]**
7. Geography: delivery only, or also local pickup (Budapest radius)?
8. Retention policy for raw snapshots (disk use).
9. Backup expectations.
10. Language of the UI (Hungarian or English). **[OPEN-10]**

### 10.2 Contradictions / ambiguities
- **"Claude analysis manual" vs. a scalable pipeline:** manual analysis is a bottleneck by design;
  the deterministic engines must carry 100 % of routine evaluation. Claude is for edge cases only.
- **"Never confuse advertised with completed sales" vs. "no paid data":** most Hungarian
  second-hand venues show asking prices, not final prices. Realistic consequence: early on, the
  Resale engine will mostly return `MANUAL_REVIEW` until the user's own sales and permitted
  completed-sale sources build evidence. This is correct behaviour, not a bug.
- **"All four categories equally important" vs. "do not implement everything at once":**
  resolved by building the shared core + one thin vertical slice first, then adding modules;
  equal importance applies to the end state, not the build order. **[OPEN-11]**
- **"Playwright only when necessary and permitted":** JS-rendered sites that forbid automation in
  their ToS are simply not collected automatically.
- **Food in the Resale engine:** listed as a category for both engines, but food resale is
  legally constrained → default `NOT_APPLICABLE`.
- **"Local-first" + "notifications":** a laptop that is asleep cannot notify. Notifications are
  best-effort while the app/scheduler runs.

### 10.3 Data-quality risks
Mis-matches (laptop variants, apparel sizes), stale prices, flyer validity windows, loyalty-only
prices, VAT/shipping inconsistencies, marketplace sellers with fake warranties, counterfeit
apparel, delisted ≠ sold, survivorship bias in asking prices, duplicate ads (reposts),
parsing errors on HU number formats (`1 299 Ft`, `1.299,-`, `12 990 Ft/kg`).

### 10.4 Technical / scalability limits
SQLite single writer (fine for one user; collectors must write via one queue/process);
no 24/7 uptime; site layout changes break HTML parsers silently (needs parser health checks);
Streamlit reruns whole scripts (heavy computations must be precomputed, not done in the UI);
politeness limits cap collection volume to thousands, not millions, of observations per day.

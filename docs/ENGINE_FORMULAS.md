# DealRadar HU — Engine Formulas and Default Thresholds

Status: v1.1 (2026-11-24), matches the code in `dealradar/evaluation/costs.py`, `dealradar/ledger/calc.py`,
`dealradar/engines/personal/`, `dealradar/engines/resale/`, `dealradar/evaluation/params.py`
and the category modules. Any change to a formula or default must update this file in the same change.

**Two independent engines.** They never share a score, a verdict or a result type (ADR-002). Both
return recommendations with `decision_required = True`; nothing in the system buys or authorizes
a purchase.

**Number conventions.** Money is whole HUF (gross), rates are basis points (1 bp = 0.01 %,
10 000 bp = 100 %), arithmetic is `Decimal`. Each line item is rounded to whole HUF **half away from
zero** before summing, so every breakdown adds up exactly (tested on random inputs).

**Labels.** Every number in a result carries a kind (`ValueKind`):
`FACT` (observed price, recorded sale), `USER_INPUT` (fee/tax profile, watchlist, override),
`ESTIMATE` (derived from data: medians, days to sell), `ASSUMPTION` (unmeasured default: return
rate, capital cost). Results list them in `assumptions` with their source.

---

## 0. Shared formulas (`evaluation/costs.py`)

| Name | Formula | Notes |
|---|---|---|
| effective price | `price + inbound_shipping` | unknown shipping -> **None** (never 0); pickup-only -> `price` |
| discount_bp | `-(price - reference) / reference x 10 000` | + = cheaper than reference; reference must be > 0 |
| commission | `clamp(round(base x commission_bp / 10 000), min, cap)` | base = sale price (+ buyer shipping if `commission_includes_shipping`) |
| payment fee | `round((sale + buyer_shipping) x payment_fee_bp / 10 000) + payment_fixed` | |
| expected cost | `round(amount x rate_bp / 10 000)` | probability-weighted |
| holding cost | `round(capital x capital_bp_per_year x days / 10 000 / 365) + storage_per_day x days` | |
| tax | `PERCENT_OF_PROFIT`: `round(max(0, pre_tax) x rate)`; `PERCENT_OF_REVENUE`: `round(sale_price x rate)`; `NO_TAX_DECLARED`: 0; `NONE_SELECTED`: error | never negative; no tax credit for losses |
| ROI | `round(net_profit / invested x 10 000)` bp | `invested <= 0` -> **None** (undefined, not infinite) |
| capital exposure | `acquisition_cost + listing_fee + packaging` | cash out before any money comes back |

---

## 1. Personal Deal Engine (`engines/personal/evaluator.py`)

### 1.1 Inputs
Category evaluation inputs (price, shipping, condition, category missing inputs and review flags),
listing condition group, warranty months/type, pickup flag, match info, advertised-price benchmark
view (`AdvertisedView`: status, confidence, condition group, trimmed median, historical min, landed
median), optional watchlist (target price, max price, acceptable conditions), `PersonalParams`.

### 1.2 Comparisons
- **Basis.** If the benchmark has a landed median (item + delivery) and the effective price is
  known -> compare `effective_price` with `landed_median` (`LANDED`). Otherwise compare the item
  price with the item median (`ITEM`) and say so in the reasons. Categories with
  `require_landed_comparison` (HOME) -> missing landed benchmark is a review flag.
- `discount_vs_median_bp = discount_bp(median, compared_price)`.
- `discount_vs_min_bp = discount_bp(historical_min, item_price)`; `at_or_below_historical_min =
  item_price <= historical_min` (historical min = minimum of outlier-free samples in the window).

### 1.3 Missing inputs -> MANUAL_REVIEW
category missing inputs; `price`; `shipping` (unknown and not pickup - checked by the engine itself
too); `product_match` (not matched); `price_benchmark` (none, NO_DATA, INSUFFICIENT_DATA).

### 1.4 Review flags -> MANUAL_REVIEW
category review flags (e.g. `authenticity_high`, `expired_use_by`); `match_not_confirmed` (FUZZY /
AI match not confirmed by the user); `match_confidence_low` (< `min_match_confidence`, unless user
confirmed); `benchmark_stale`; `benchmark_confidence_low` (< `min_benchmark_confidence`);
`benchmark_condition_mismatch`; `landed_benchmark_missing`; `too_good_to_be_true`
(`discount >= suspicious_discount_bp` - possible error, fake or wrong match);
`new_without_warranty` (NEW item with warranty type NONE, if `flag_new_without_warranty`).

### 1.5 The user's limits -> NOT_A_DEAL (if no review is needed)
condition not in the watchlist's acceptable conditions; effective price above the watchlist max;
warranty months below `min_warranty_months_new` / `_used`.
`watchlist` relevance: NOT_WATCHED / WATCHED / TARGET_MET (effective <= target) /
ABOVE_MAX_PRICE / CONDITION_NOT_ACCEPTED. TARGET_MET is reported even when the verdict is
MANUAL_REVIEW.

### 1.6 Verdict (in this order)
1. any missing input or review flag -> `MANUAL_REVIEW`
2. any user limit violated -> `NOT_A_DEAL`
3. `discount >= strong_discount_bp`, or (`at_or_below_historical_min` and `discount >= good_discount_bp`)
   -> `STRONG_DEAL` if benchmark confidence >= `strong_requires_confidence`, else `GOOD_DEAL` (reason given)
4. `discount >= good_discount_bp` -> `GOOD_DEAL`
5. `discount >= -fair_tolerance_bp` -> `FAIR_PRICE`
6. otherwise `NOT_A_DEAL`

### 1.7 Defaults (`PersonalParams`, all ASSUMPTIONS)
| Parameter | Default | TECH | APPAREL | FOOD | HOME |
|---|---|---|---|---|---|
| strong_discount_bp | 2 000 (20 %) | = | = | = | = |
| good_discount_bp | 1 000 (10 %) | = | = | = | = |
| fair_tolerance_bp | 300 (3 % above median) | = | = | = | = |
| suspicious_discount_bp | 5 000 (50 %) | = | = | = | = |
| min_match_confidence | 90 | = | = | = | = |
| min_benchmark_confidence | MEDIUM | = | = | = | = |
| strong_requires_confidence | HIGH | = | = | = | = |
| require_landed_comparison | false | = | = | = | **true** |
| min_warranty_months_new | 0 | = | = | = | = |
| min_warranty_months_used | 0 | = | = | = | = |
| flag_new_without_warranty | true | = | = | = | = |

---

## 2. Resale Deal Engine (`engines/resale/`)

### 2.1 Price source
**Only completed sales** (`SoldView`, built from `observed_sales`; own sales later from the
ledger). Asking prices are not an input of any calculation; `context_asking_median` is display-only
and a test proves changing it never changes a result. Expected sale price range:
`low = p25`, `expected = trimmed median`, `high = p75` of completed sales (same variant, same
condition group, outliers removed - see ARCHITECTURE.md §6).

### 2.2 Acquisition cost
`acquisition = item price + inbound shipping`; pickup-only: `item price + pickup_travel_cost_huf`
(must be configured; otherwise missing input). Unknown shipping -> missing input.

### 2.3 Per-scenario profit (one scenario per sale price: low / expected / high)
```
income        = sale_price + buyer_shipping_charge
commission    = clamp(round(sale_price[+buyer_shipping] x commission_bp), min, cap)
payment_fee   = round(income x payment_fee_bp) + payment_fixed
fixed_fees    = fixed_fee_per_sale + listing_fee
outbound      = fee_profile.outbound_shipping_cost_huf      (carrier cost paid by the seller)
packaging     = fee_profile.packaging_huf
return_cost   = round(return_rate_bp x return_cost_huf)
defect_cost   = round(defect_rate_bp x round(sale_price x defect_loss_bp))
holding       = round(acquisition x capital_cost_bp_per_year x days / 365) + storage_per_day x days
pre_tax       = income - acquisition - commission - payment_fee - fixed_fees - outbound
                - packaging - return_cost - defect_cost - holding
tax           = tax profile formula (§0) on sale_price / max(0, pre_tax)
net_profit    = pre_tax - tax
ROI           = net_profit / acquisition
```
`buyer_shipping_charge` = median buyer-paid shipping of the completed sales (ESTIMATE); if unknown,
**0** (ASSUMPTION, conservative).
Worked example (tests/test_costs.py): sale 60 000, buyer shipping 1 500, acquisition 40 000,
10 days, 10 % commission (min 200), 1.5 % + 50 payment, shipping 1 990, packaging 500, returns
3 % x 3 000, defects 2 % x 50 %, capital 8 %/year, tax 15 % of profit -> **net 9 570 HUF, ROI 2 393 bp**.

### 2.4 Liquidity and time to sell (`engines/resale/liquidity.py`)
```
sales_per_30d = n_completed_sales x 30 / window_days
days_to_sell  = median days listed            if >= 3 sales have days_listed   (ESTIMATE)
              = round(30 / sales_per_30d)      otherwise, confidence capped at LOW (ESTIMATE)
HIGH   if sales_per_30d >= liquidity_high_sales_per_30d   and days <= liquidity_high_max_days
MEDIUM if sales_per_30d >= liquidity_medium_sales_per_30d and days <= liquidity_medium_max_days
LOW    otherwise;   UNKNOWN without completed sales
```
Liquidity confidence = the completed-sales benchmark confidence (or LOW for the frequency fallback).

### 2.5 Critical inputs - missing -> MANUAL_REVIEW **without any profit numbers**
category missing inputs; `price`; `shipping`; `condition`; `pickup_travel_cost` (pickup-only);
`product_match`; `completed_sales` (none, NO_DATA, INSUFFICIENT_DATA, or fewer than
`min_completed_sales`); `fee_profile`; `outbound_shipping_cost`; `packaging_cost`; `tax_profile`
(none or NONE_SELECTED); `time_to_sell`.

### 2.6 Review flags - numbers computed but `provisional = true`, verdict MANUAL_REVIEW
category review flags; `match_not_confirmed`; `sales_condition_mismatch`; `completed_sales_stale`;
`completed_sales_confidence_low` (< `min_sales_confidence`); `fee_profile_unverified`;
`tax_profile_unverified`.

### 2.7 Verdict
1. category not resale-applicable (FOOD) -> `NOT_APPLICABLE`
2. any missing critical input -> `MANUAL_REVIEW` (no numbers)
3. any review flag -> `MANUAL_REVIEW` (provisional numbers)
4. expected net profit <= 0 -> `NOT_PROFITABLE`
5. `PROFITABLE` only if **all**: expected net >= `min_net_profit_huf`; ROI >= `min_roi_bp`;
   low-scenario (p25) net >= 0; liquidity HIGH or MEDIUM; days to sell <= `max_days_to_sell`
6. otherwise `MARGINAL`, with every failed criterion listed

### 2.8 Defaults (`ResaleParams`, all ASSUMPTIONS - not measured)
| Parameter | Default | TECH | APPAREL | FOOD | HOME |
|---|---|---|---|---|---|
| min_completed_sales | 3 | = | = | n/a | = |
| min_sales_confidence | MEDIUM | = | = | n/a | = |
| min_net_profit_huf | 5 000 | = | **3 000** | n/a | = |
| min_roi_bp | 1 500 (15 %) | = | = | n/a | = |
| max_days_to_sell | 60 | = | = | n/a | **90** |
| return_rate_bp | 300 (3 %) | 300 | **1 000** | n/a | 300 |
| return_cost_huf | 3 000 | 3 000 | **2 500** | n/a | **15 000** |
| defect_rate_bp | 200 (2 %) | 200 | **100** | n/a | **300** |
| defect_loss_bp | 5 000 (50 % of price) | 5 000 | **3 000** | n/a | **6 000** |
| capital_cost_bp_per_year | 800 (8 %) | = | = | n/a | = |
| storage_cost_huf_per_day | 0 | = | = | n/a | = |
| pickup_travel_cost_huf | none (must be set) | = | = | n/a | = |
| liquidity_high_sales_per_30d | 4 | = | = | n/a | = |
| liquidity_high_max_days | 14 | = | = | n/a | = |
| liquidity_medium_sales_per_30d | 1 | = | = | n/a | = |
| liquidity_medium_max_days | 45 | = | = | n/a | = |

### 2.9 Fee and tax profiles - user input only
No platform fee or tax rate is built in. `FeeProfile` fields (all entered by the user):

| Field | Meaning | Missing / default |
|---|---|---|
| commission_bp | commission rate | required |
| commission_min_huf | minimum commission per sale | 0 |
| commission_cap_huf | maximum commission per sale | none (no cap) |
| commission_includes_shipping | commission also charged on buyer-paid shipping | false |
| fixed_fee_huf | fixed fee per completed sale | 0 |
| listing_fee_huf | paid up front, also if the item does not sell | 0 |
| payment_fee_bp | payment provider rate on everything the buyer pays | 0 |
| payment_fixed_huf | fixed payment fee per sale | 0 |
| outbound_shipping_cost_huf | what the seller pays the carrier | **missing -> MANUAL_REVIEW** |
| packaging_huf | packaging per item | **missing -> MANUAL_REVIEW** |
| verified | user checked the numbers against the platform's current terms | false -> review flag | `TaxProfile`: `NONE_SELECTED` (-> MANUAL_REVIEW), `NO_TAX_DECLARED`,
`PERCENT_OF_PROFIT`, `PERCENT_OF_REVENUE` with a rate, `verified`. Tax treatment must be confirmed
with an accountant (OPEN-7); the app labels unverified profiles and keeps the verdict at MANUAL_REVIEW.

---

## 3. Changing parameters

Category defaults live in `categories/<cat>/__init__.py` (`PERSONAL_PARAMS`, `RESALE_PARAMS`).
User overrides: `services.evaluation.set_overrides(db, "personal"|"resale", category, {...})` - stored
in `settings` under `engine.<engine>.<CATEGORY>`, audited, validated (unknown keys, wrong types and
negative numbers are rejected). Results then show `source = "user override (settings)"`.
Benchmark policies (windows, minimum samples, outlier limits) are in ARCHITECTURE.md §6 / ADR-041.

---

## 4. Actual results from recorded transactions (`ledger/calc.py`)

These are **ACTUAL** numbers: they use only transactions the user recorded. Resale engine results
are ESTIMATES and are never added to them (ADR-051).

- Every transaction: `amount > 0` and a direction. `signed = +amount` (IN) or `-amount` (OUT).
  IN types: SALE, REFUND_RECEIVED, OTHER_INCOME. All others are OUT.
- **Reversals:** a row with `reverses_id` cancels the referenced row; both are left out.
- **Order money** (on the acquisition: PURCHASE, INBOUND_SHIPPING, REFUND_RECEIVED from the
  seller): `order_cost = -sum(signed)`, split over the order's units:
  `base, r = divmod(order_cost, units)`; the `r` lowest item ids get `base + 1`, the rest `base`.
  Shares always sum exactly.
- Per item: `cost_basis = allocated_order_cost + item OUT transactions` (fees, shipping,
  packaging, tax, refunds given, other costs); `income = item IN transactions` (sale price,
  buyer-paid shipping as OTHER_INCOME, other income).
- `realized_profit = income - cost_basis`, **only** for RESALE items with status SOLD,
  RETURNED_TO_SELLER or WRITTEN_OFF. Open items have no realized profit.
- Portfolio: `realized_profit` = sum over closed items; `realized_roi_bp =
  round_half_up(realized_profit x 10 000 / realized_cost_basis)` (none if the basis is 0);
  `capital_in_stock` = cost basis of open resale items; `personal_spend` = cost basis of PERSONAL
  items (spending, never profit); `cash_in`, `cash_out`, `net_cash_flow = cash_in - cash_out`;
  `unallocated` = order money with no items (should be 0).
- Identity (tested on random ledgers): when every resale item is closed and there are no personal
  items, `realized_profit = net_cash_flow`.

Worked example (tests/test_ledger_calc.py): bought 40 000 + 1 490 delivery; sold 60 000; platform
fee 6 000, payment fee 973, shipping 1 990, packaging 500 -> cost basis 50 953, realized profit
**9 047 HUF**, ROI 9 047 / 50 953 = **1 776 bp** (17.76 %).

Own completed sales also feed the sold benchmark as `OWN_SALE` evidence (ADR-050).

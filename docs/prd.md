# PRD: In-House Supplement Ordering (Vertical Slice)

_Last updated: 2026-10-05 · Owner: Taylor Clements · Status: Approved for build_
_Rationale for every decision below lives in [`decisions.md`](decisions.md) (D1–D10)._

---

## 1. Problem

Cerbo's providers (functional medicine, direct-pay, and cash practices) recommend supplements as part of treatment plans. Today they order them on third-party marketplaces: the provider pays up front, the product ships to the patient, and the patient reimburses the provider separately. That means:

- Providers front money and chase reimbursement.
- Patients get a disjointed experience, disconnected from their care.
- None of it is reflected in the clinical record or the practice's finances.
- The margin and transaction fees go to a third party.

## 2. What we're building

A **working vertical slice** in which:

1. A provider assembles a supplement order for a patient and sets the patient price per item.
2. The patient pays Cerbo directly (stubbed payment).
3. The system computes and permanently records the money split: **COGS** (to Cerbo, which holds the inventory), **provider payout** (the provider's margin, net of fee), and **Cerbo's 75 bps platform fee**.
4. Every cent of a paid order is auditable.
5. Providers can see what they've sold and manage the products they offer; Cerbo admins manage stock.

Priorities, in order: **integrity of the money flow > clarity of judgment > breadth.** Styling and catalog UX are not goals.

## 3. Goals and success metrics

| ID | Goal |
|---|---|
| G1 | Correct, auditable money: every cent of a paid order is accounted for and explainable |
| G2 | Clean seams: external dependencies are stubbed behind replaceable interfaces |
| G3 | Pragmatic scope: buildable in 1–2 days |
| G4 | Measurable: GMV and platform fee revenue can be reported cleanly |
| G5 | Explainable: every decision is documented and defensible |

**Business metrics the data model must support (G4):**
- **GMV processed in-house** = sum of subtotals of paid orders.
- **Platform fee revenue** = sum of platform fees of paid orders (≈ 0.75% of GMV).
- **Volume** = number of paid orders and units, per provider and per product (leading indicator of migration off third-party marketplaces).

## 4. Users and roles

| Role | Can do | Cannot do |
|---|---|---|
| **Provider** | Manage their product list (enable/disable, default prices); build, confirm, and cancel orders for patients; view their own orders, sales, and earnings | See other providers' orders or earnings; change stock or COGS; change orders after creation |
| **Patient** | View orders addressed to them; pay | See other patients' orders; change prices |
| **Cerbo admin** | View and update stock levels and COGS | Act as a provider or patient |

Authentication is stubbed (role switcher), but **role and ownership rules are enforced on every request** (D10).

## 5. Scope

### In scope
- Seeded catalog of a few supplements (name, COGS, suggested retail price, stock).
- Provider product list with default prices.
- Order builder with live split preview, review-and-confirm step.
- Patient order page and stubbed payment, including decline and retry.
- Money split computation, persistence, and ledger.
- Stock decremented at payment.
- Provider dashboard (sales, earnings, pending orders) and per-order audit view.
- Admin stock/COGS page.

### Out of scope (per brief)
Real payments, auth, email, or shipping; catalog browsing, search, and imagery; styling beyond a tidy themed default; tax; shipping cost; regulatory/compliance; multi-state and international; warehouses.

## 6. Money rules

These rules are the core of the system. All amounts are **integer cents** (D2).

### 6.1 Definitions
- `line_total = unit_price × qty`
- `subtotal = Σ line_total` — this is **GMV** and the **fee base**.
- `cogs_total = Σ (unit_cogs × qty)`
- `platform_fee = round_half_up(subtotal × 75 / 10,000)`, computed **once per order** (D1, D2)
- `provider_payout = subtotal − cogs_total − platform_fee` (the **remainder**: the provider absorbs rounding) (D2)

**Invariant:** `subtotal = cogs_total + provider_payout + platform_fee`, exactly, for every order.

### 6.2 Fee base
The fee is charged on the **merchandise subtotal only**, deducted from the provider's share. The patient pays exactly the price the provider set. Tax and shipping, if ever added, sit **on top** of the subtotal and are **outside** the split and the fee base (D1).

### 6.3 Rounding
Integer math: `fee = (subtotal × 75 + 5,000) // 10,000`. This is the only rounding step in the system (D2).

### 6.4 Worked examples

| Case | Subtotal | COGS | Fee | Provider payout | Notes |
|---|---|---|---|---|---|
| Basic | $40.00 | $20.00 | $0.30 | $19.70 | |
| Per-order rounding | $20.20 (2 × $10.10) | $10.00 | $0.15 | $10.05 | Per-line rounding would give $0.16 (rejected) |
| Rounds up | $10.10 | $5.00 | $0.08 | $5.02 | 7.575¢ → 8¢ |
| Exact half-cent tie | $2.00 | $1.00 | $0.02 | $0.98 | 1.5¢ → 2¢ |
| Fee rounds to zero | $0.66 | $0.30 | $0.00 | $0.36 | Orders under $0.67 incur no fee (see §10) |
| Payout exactly $0 | $100.00 | $99.25 | $0.75 | $0.00 | **Accepted** |
| Payout −1¢ | $100.00 | $99.26 | $0.75 | −$0.01 | **Rejected** (each line still ≥ COGS) |

### 6.5 Pricing rules (D3)
- The provider enters the **patient-facing unit price**. Margin, fee, and payout are derived and shown live.
- **Per line:** `unit_price ≥ unit_cogs`. (Error `LINE_BELOW_COGS`.)
- **Per order:** `provider_payout ≥ 0`, checked by running the same split function used for real money. (Error `NEGATIVE_PAYOUT`, message: "Price too low to cover the platform fee.")
- Quantity is an integer ≥ 1; prices are positive integer cents; an order has ≥ 1 line.
- The same rules validate a provider's **default prices** when saved (evaluated at qty 1).

## 7. Functional requirements

Each requirement has acceptance criteria (AC) that the tests are written from.

### FR1. Provider product list
The provider sees all catalog products with stock status, and can enable/disable each and set a default patient price.
- AC1.1: Enabled products with their default prices appear in the order builder; disabled ones don't.
- AC1.2: Saving a default price that would produce a negative payout at qty 1 is rejected with an explanation.
- AC1.3: Stock is shown as "N in stock" / "Out of stock". Providers cannot edit stock.

### FR2. Build and confirm an order
The provider selects a patient, adds lines (product, qty, unit price pre-filled from default), sees a live preview, reviews, and confirms.
- AC2.1: The preview shows per-line price, COGS, and margin, plus order subtotal, COGS, platform fee, and "you receive", all computed by the backend.
- AC2.2: Invalid pricing shows the specific error (`LINE_BELOW_COGS`, `NEGATIVE_PAYOUT`, etc.) and blocks confirmation.
- AC2.3: Confirming creates the order in `pending_payment` with **prices, COGS, and the fee rate copied onto the order** (D4).
- AC2.4: After creation, the provider sees the patient's order link; the notification stub is called.
- AC2.5: Later changes to catalog COGS or default prices do **not** change existing orders.
- AC2.6: A provider can cancel their own `pending_payment` order. Paid orders cannot be cancelled or edited.

### FR3. Patient pays
The patient opens their order, sees an itemized list and total, and pays with a (fake) payment method.
- AC3.1: The page shows items, quantities, prices, total, and "Prices set by your provider on {date}".
- AC3.2: A successful payment moves the order to `paid`, decrements stock, writes ledger entries, and calls the fulfillment stub. All database changes happen in **one transaction**.
- AC3.3: A declined payment changes nothing; the order stays `pending_payment`; the patient can retry.
- AC3.4: If any line is out of stock, payment fails with `OUT_OF_STOCK`, nothing is charged or written, and the order stays `pending_payment`.
- AC3.5: Paying twice (double-click, retry, concurrent requests) results in **one** charge, **one** paid order, and **one** set of ledger entries; the repeat request returns the original receipt.
- AC3.6: Two patients paying for the last unit at the same time: exactly one succeeds.
- AC3.7: Cancelled orders cannot be paid.

### FR4. Money split recorded and auditable
- AC4.1: Every paid order stores `subtotal`, `cogs_total`, `fee_bps`, `platform_fee`, `provider_payout`, and per-line `unit_price`, `unit_cogs`, `qty`.
- AC4.2: Every paid order has exactly four ledger entries: patient payment (= subtotal), Cerbo COGS, Cerbo fee, provider payable. The three allocations sum to the patient payment.
- AC4.3: Ledger entries equal the order's split columns for every paid order.
- AC4.4: An audit view for a paid order shows lines, split, ledger entries, and integrity checks confirming the stored fee matches the formula, the split adds up, and the ledger matches the split.
- AC4.5: Paid orders and ledger entries are never updated or deleted.

### FR5. Provider dashboard
- AC5.1: Shows totals for the provider: GMV (sum of paid subtotals), platform fees, and earnings (sum of provider payable), sourced from the ledger.
- AC5.2: Lists paid orders (date, patient, subtotal, fee, payout) with links to the audit view.
- AC5.3: Shows units sold per product.
- AC5.4: Lists pending orders with a cancel action.
- AC5.5: Shows only the current provider's data.

### FR6. Admin stock and COGS
- AC6.1: Admin can view all products with stock and COGS, and set stock (≥ 0) and COGS (positive cents).
- AC6.2: Non-admins are rejected.
- AC6.3: COGS changes affect only orders created afterward (see AC2.5).

## 8. Stubs (D10)

| Seam | Stub | Real version later |
|---|---|---|
| Auth | Role switcher sends a user ID header; real role/ownership checks | OAuth/SSO; patient magic links |
| Payments | `FakePaymentProvider`: approves by default; `fake_card_decline` declines; replays the same attempt (key + amount + method) without charging twice; after a decline, a different card is a new attempt | Stripe with a per-attempt idempotency key + webhooks |
| Notifications | Console log; patient link shown in provider UI | Email/SMS; portal messaging |
| Fulfillment | Console log after payment commits | Warehouse/shipping integration |

## 9. Assumptions

- US-only, single currency (USD). No tax, no shipping cost.
- Cerbo holds the inventory; COGS is Cerbo's revenue line in the split.
- Fee rate is 75 bps for all orders, stored on each order so historical orders remain correct if the rate changes.
- Card processing fees are ignored (payments are stubbed); see §10.
- One provider can order for any patient in the seed data (no practice/patient-panel modeling).

## 10. Open questions and next steps (not in this build)

- **Card processing fees:** real processors typically charge more than 75 bps. Who absorbs them (provider payout, COGS markup, or Cerbo)? Needs a business decision; the ledger can take an extra allocation line.
- **Minimum platform fee of 1¢:** orders under $0.67 incur no fee. A 1¢ minimum is a simple option if desired; not adopted because it breaks "fee = exactly 0.75%" for no realistic gain.
- **Price ceiling:** large markups raise conflict-of-interest concerns; Cerbo may want a cap (e.g. ≤ suggested retail). Policy decision.
- **Price changes before payment:** re-pricing at payment only in the payer's favor, or order expiry after N days.
- **Refunds and payouts:** modeled later as new reversing/settlement ledger entries.
- **Fulfillment states:** shipped, delivered.
- **Change history** for provider product settings.
- **Production hardening:** PostgreSQL, migrations, DB-level append-only enforcement, payment webhook reconciliation.

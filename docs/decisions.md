# Decision Log: In-House Supplement Ordering

_Running log of product and architecture decisions. Feeds `prd.md` and `architecture.md`, and the "key decisions & trade-offs" section of the final writeup._

## Goals every decision is judged against

| ID | Goal | Source in brief |
|---|---|---|
| G1 | **Correct, auditable money**: every cent of a paid order is accounted for and explainable | Functional req. 3–4 |
| G2 | **Clean seams**: payments, auth, email, shipping stubbed behind interfaces that a real version could replace | "keep the seams clean and tell us what's stubbed" |
| G3 | **Pragmatic scope**: shippable in 1–2 days by one person and AI agents | Time constraint, "smallest thing that proves you understand" |
| G4 | **Measurable**: GMV and the 75 bps fee can be reported cleanly | Impact metrics |
| G5 | **Explainable**: decisions are easy to defend in the writeup | Performance benchmarks |

## Decision agenda

| # | Decision | Status |
|---|---|---|
| 1 | Platform fee: what it's charged on, and who bears it | ✅ A: 0.75% of merchandise subtotal, from provider payout |
| 2 | Rounding and granularity (per line vs. per order, leftover cents) | ✅ Integer cents, per-order fee, round half up, payout is the remainder |
| 3 | Pricing input (provider sets price or margin) and guardrails | ✅ Provider sets unit price; line price ≥ COGS and order payout ≥ 0 |
| 4 | How the split is recorded (snapshot columns vs. ledger) | ✅ Snapshot at creation; split columns plus a minimal ledger; append-only |
| 5 | Order lifecycle and payment idempotency | ✅ pending_payment → paid or cancelled; payment safe to retry |
| 6 | Inventory scope for the dashboard | ✅ Provider product list plus Cerbo-owned stock reduced at payment; input checks |
| 7 | Stack: language and backend framework | ✅ Python + FastAPI, React frontend, pytest, uv |
| 8 | Stack: database | ✅ SQLite (Postgres-ready) + SQLAlchemy 2.0, seed script |
| 9 | Stack: frontend approach | ✅ React + Vite + TS; Pico.css themed with Cerbo brand tokens; cents-only API |
| 10 | Stubs and seams (auth, payments, notifications) | ✅ Interface + fake for auth, payments, notifications, fulfillment; real ownership checks |

---

## Decisions

### D1. Platform fee: base and who bears it
**Status:** Decided

**Options considered**
- **A. Fee is 0.75% of the merchandise subtotal, deducted from the provider's payout.** _(chosen)_
- B. Fee is added on top for the patient: an extra line on a clinical recommendation, and an ambiguous base (0.75% of price, or of price + fee?).
- C. Fee is charged on the provider margin only: it isn't "on the transaction," doesn't match the GMV × 75 bps metric, and earns half the revenue.

**Decision:** A.
- **Fee base = merchandise subtotal**, the sum of the patient-facing line prices.
- **Excluded from the base:** sales tax (pass-through money owed to the state, not revenue) and shipping. Both are out of scope for this build, but they're excluded by definition so that adding them later can't silently change the fee.
- **Order of operations:** line prices → subtotal (= fee base = GMV) → platform fee → provider payout = subtotal − COGS − fee. Tax and shipping would later be added on top of the subtotal and are not part of the split.
- **Invariant:** `subtotal = COGS + provider_payout + platform_fee`, exact to the cent.
- COGS goes to Cerbo, which holds the inventory.

**Why:** It's the only option where the fee is exactly 0.75% of GMV (G4) and the split adds up with no extra rules (G1). The patient sees a single clean price, which matches the standard marketplace model where the seller absorbs the platform fee (G5). The negative-margin risk is handled in D3.

**Known gap, for the writeup:** card processing fees. Real processors typically charge a few percent of the charge, which is more than our 75 bps. Payments are stubbed here, so this is out of scope, but in production Cerbo would need to decide who absorbs processing costs: the provider's payout, the COGS markup, or Cerbo. The data model should leave room for an extra split line. This is a business decision, not something to settle in this build.

### D2. Rounding and granularity
**Status:** Decided

**2a. Money representation: integer cents.** All amounts are stored and calculated as integers in cents (`4000` = $40.00). The fee rate is stored as integer basis points (`75`), not `0.0075`. No floats anywhere in the money path.
- Rejected: DECIMAL types (exact, but support varies by language and DB, and floats slip in easily), floats (inexact).
- Why: Exact, works in any language or database, and is the industry convention (e.g. Stripe uses minor units) (G1, G5).

**2b. Granularity: the fee is calculated once per order, on the subtotal.**
- Rejected: per line then summed (rounding drift; e.g. 2 × $10.10 gives a 16¢ fee per line vs. 15¢ per order), and per order then split back across lines (correct, but more code than the brief needs; can be added later without changing order totals).
- Why: Exactly matches "0.75% of the transaction" with a single rounding step (G1, G4); simplest (G3). Per-line price, COGS, and margin are still recorded, and only the fee is order-level.

**2c. Rounding rule: round half up**, in integer math: `fee_cents = (subtotal_cents × fee_bps + 5000) // 10000`.
- Rejected: banker's rounding (unbiased, but less intuitive), always round down (provider-friendly, Cerbo forgoes < 1¢/order).
- Why: Familiar and easy to explain (G5).
- Known bias, for the writeup: ups and downs mostly cancel, but exact half-cent ties always round up. With a 75 bps rate, a tie happens only when the subtotal is $2, $6, $10, $14… (≡ $2 mod $4), roughly 1 in 400 orders, each +0.5¢ in Cerbo's favor. Negligible, and documented.

**2d. Where the rounding lands: the provider payout is the remainder.**
- Line totals (`unit_price × qty`) and COGS are exact integers. **The fee is the only place a fraction of a cent appears, so it is the only rounding step.**
- `payout = subtotal − COGS − fee_rounded`. Whatever fraction of a cent rounding added to or removed from the fee comes out of, or goes back to, the provider payout. The provider absorbs it, consistent with D1.
- The invariant `subtotal = COGS + payout + fee` therefore holds by construction.
- Auditability: each paid order stores `subtotal`, `fee_bps`, `fee_cents`, and the rounding rule, so anyone can recompute the fee and confirm it.

### D3. Pricing input and guardrails
**Status:** Decided

**3a. The provider enters the patient-facing unit price** (integer cents). It is the stored source of truth. Margin, fee, and payout are calculated from it and shown in a live preview ("you'll receive $X"). Prices may be pre-filled from a suggested retail price in the seeded catalog.
- Rejected: margin in dollars (shows a number the provider won't actually receive, because the fee comes out of it), markup % (adds a second rounding step and odd prices), both modes (more UI, little benefit).
- Why: The simplest model for patient and provider alike, with a single source of truth and no extra rounding (G1, G3, G5).

**3b. Price floor: two checks, both required to create an order.**
1. **Per line: `unit_price ≥ unit_COGS`.** No item is sold at a loss with another item making up the difference, which keeps per-product reporting sensible.
2. **Per order: `provider_payout ≥ 0`**, checked by running the **same split function** that calculates the real money, so the validation and the actual calculation can't disagree.
- If either check fails, the order is rejected with a clear message (e.g. "price too low to cover the platform fee").
- Rejected: no floor (a negative payout means the provider owes Cerbo, which recreates the reimbursement-chasing problem), and price ≥ COGS alone (at price = COGS, payout = −fee), and price ≥ COGS + a fixed buffer (the fee grows with price, so a fixed buffer like 1¢ doesn't cover it; e.g. COGS $20.00, price $20.01 → fee 15¢ → payout −14¢).
- Test cases to include: price = COGS on every line (must be rejected); price just high enough that payout = 0 (must be accepted).
- Why: It closes the negative-payout hole with no special cases (G1), and it's one function reused, not a second formula (G3, G5).

**Considered for later: a minimum platform fee of 1¢.** With round-half-up at 75 bps, the fee rounds to 0¢ on orders under $0.67. A 1¢ minimum would guarantee Cerbo earns something on every transaction. Not adopted, because it breaks "fee = exactly 0.75% of subtotal" (D2), adds a rule to explain and test, and no realistic supplement order is under $0.67. Cerbo still receives full COGS on those orders, so it never loses money. Note in the writeup as a deliberate option.

**3c. Basic validation:** quantity is a whole number ≥ 1; prices are positive integer cents; an order has ≥ 1 line.

**Open product question (not for this build):** a price ceiling. Large provider markups on supplements raise conflict-of-interest concerns, and Cerbo may want a cap, such as no more than suggested retail. That's a policy decision, and compliance is out of scope.

### D4. How the split is recorded
**Status:** Decided

**4a. Snapshot at order creation.** Unit price, unit COGS, quantity, and the fee rate (bps) are copied onto the order and its lines when the order is created. The order is a self-contained record; later catalog changes never touch existing orders. Once paid, the order is frozen.
- Rejected: referencing the live catalog (a COGS change would silently rewrite past splits), and snapshotting at payment (the patient could see one split and pay another).
- **Interface note:** the patient's order page shows that prices are locked as of the order date (e.g. "Prices set by your provider on Oct 5"), and the provider UI notes that later catalog changes don't affect orders already sent.

**4b. Two records with distinct roles:**
- **Order split columns = what was agreed** (the calculation): `subtotal`, `cogs_total`, `fee_bps`, `fee_cents`, `provider_payout` on the order; `unit_price`, `unit_cogs`, `qty` on each line.
- **Ledger = what money moved.** A minimal append-only `ledger_entries` table, written **in the same DB transaction** as the payment: one row for +subtotal received from the patient, and three allocation rows (Cerbo COGS, Cerbo fee, provider payable) that sum to it.
- **Invariant test:** for every paid order, its ledger rows exactly equal its split columns.
- Payoff: "where did every cent go" is one query, the provider's "you're owed $X" is a sum over the ledger, and future refunds and payouts are new rows, never edits.
- Rejected: split columns only (simplest, and the fallback if time gets tight, but no record of money movement), and a ledger only (most work to model and explain in 1–2 days).
- Why: Strongest auditability (G1), clean reporting for GMV and fees (G4), and it reflects how real payment systems work (G5), for one small extra table.

**4c. Append-only.** Paid orders and ledger rows are never updated or deleted, and corrections are new entries. Enforced in application code for this build (no update path). Next step: database-level enforcement (e.g. permissions or triggers).

**Considered for later: price changes before payment.** Because of the snapshot, a catalog change after an order is sent doesn't affect it. Possible future behavior: at payment, re-check the catalog and apply any change only if it's in the patient's/provider's favor (never charging more than shown). Open questions: the provider sets the patient price, so a COGS drop doesn't lower it on its own. Who benefits, the patient (lower price) or the provider (bigger margin)? That's a product decision. A simpler common alternative is for unpaid orders to expire after N days, so they're rebuilt with current prices. Not in this build.

### D5. Order lifecycle and payment idempotency
**Status:** Decided

**5a. Minimal states:** `pending_payment` → `paid`, or `pending_payment` → `cancelled`.
- No draft state: orders are locked at creation (D4), so to change one the provider cancels it and creates a new one.
- A failed (stubbed) payment leaves the order in `pending_payment`, and the patient can retry.
- `paid` is the hand-off point to a stubbed fulfillment step.
- Rejected: a full lifecycle (draft → sent → paid → fulfilled → refunded). Shipping and refunds are out of scope; it means more states, tests, and UI (G3).
- Next steps: fulfillment states, and refunds as reversing ledger rows (fits D4's append-only design), plus order expiry (see D4).

**5b. Payment can be safely retried (idempotent). Three layers:**
1. **Conditional update in a single DB transaction:** set `paid` *only if* the status is currently `pending_payment`, and write the ledger rows in the same transaction. If no row was updated, the order was already paid, so return the existing result.
2. **Uniqueness rule on the ledger:** the DB rejects a second set of entries for the same order (backstop).
3. **Idempotency key on the payment call:** the stub payment interface takes the order ID as an idempotency key, so a real processor that supports keys (e.g. Stripe) won't double-charge on retry (G2).
- Rejected: check-then-update in application code (race condition: two requests can both pass the check).
- **Test:** fire two concurrent payment calls at one order and expect exactly one paid order, one set of ledger rows, and one stub charge.
- Why: Prevents double charges and double ledger writes (G1), each layer is small (G3), and it keeps the payment seam ready for real use (G2).
- **Refinement (during T7/T8):** using the order ID as the key conflicted with retry-after-decline (AC3.3). The fake replays only the *same attempt* (same key, amount, and payment method); an approval is permanent; a decline followed by a different payment method is a new attempt. Double-pay protection still holds through layers 1 and 2. Production would use a per-attempt key (e.g. `order-12-attempt-2`), since real processors treat a reused key as the same request.
- Known gap, for the writeup: with a real processor, the charge could succeed and then the DB write fail. Production would reconcile using processor webhooks. Out of scope with stubbed payments.

### D6. Inventory scope
**Status:** Decided

**Ambiguity in the brief (name it in the writeup):** the requirements say the *provider* dashboard should "update inventory," while out-of-scope says Cerbo holds the inventory and stock levels are optional. A provider editing warehouse stock is an ownership mismatch, because Cerbo owns the stock.

**Resolution: split by ownership.**
- **Provider's product list (what the provider controls):** turn supplements on/off for their practice and set a default patient price for each. No stock counts.
- **Stock levels (what Cerbo controls):** a per-product stock count owned by Cerbo, *not* editable by providers. Included in scope even though the brief marks it optional.
- **"What's been sold" view:** paid orders, units per product, GMV, and provider earnings, all from the ledger (D4).

**6b. Stock mechanics: reduce at payment.**
- Stock is reduced inside the payment transaction (D5) with an "only if enough stock" conditional update. If any line is short, the whole payment fails cleanly: no charge, no ledger rows, and the order stays `pending_payment`, with a clear out-of-stock message.
- Stock levels are shown on the provider's product list and order builder ("12 in stock" / "out of stock") so providers rarely recommend unavailable items.
- Only Cerbo updates stock, via a minimal admin view ("admin" is a stubbed role, D10). Starting counts come from seed data.
- Rejected: reserving at order creation (abandoned orders hold stock forever without expiry/release logic, which means more states, timers, and tests (G3)).
- **Test:** two patients paying for the last unit at the same time: exactly one succeeds.

**6c. Checking provider input:**
1. **Default prices are validated on save** with the D3 guardrail (same split function), so a default can't produce a negative payout.
2. **Review-and-confirm before order creation:** the provider sees the full breakdown (patient pays · COGS · platform fee · **you receive**) and explicitly confirms. Orders are locked at creation with no draft state (D4/D5), so this is the place to catch mistakes.
3. **Patient confirmation page:** an itemized list of what the provider recommended, with the "prices locked on [date]" note (D4), shown before paying.
- Next step (not in this build): an append-only change history for the provider's product list (who changed which default price or on/off setting, and when).

**Why:** It resolves the brief's ambiguity by who owns what (G5), keeps stock consistent using the same transactional pattern as payment (G1, G3), and catches provider mistakes before they become locked orders (G1).

### D7. Stack: language and backend framework
**Status:** Decided

**Decision: Python + FastAPI backend, with a separate React frontend** (frontend specifics in D9).
- **Backend:** Python 3.12+, FastAPI, Pydantic for request/response validation. FastAPI's automatic API docs page (`/docs`) doubles as a demo and debugging tool.
- **Tests:** pytest.
- **Dependencies:** `uv` (fast, modern Python package and environment manager; one command to install and run).
- **Project rule: money logic is a pure Python module** (e.g. `backend/app/domain/money.py`) with no FastAPI or database imports. The split calculation, rounding, and guardrails (D2, D3) live only there. The order builder's live preview calls a backend **preview endpoint** that uses this module; the frontend never re-implements the math.
- Rejected: TypeScript + Next.js (one language and AI-fluent, but harder for the owner to read and review, and has advanced-feature pitfalls), Django (free admin panel, but heavier conventions and a clunkier interactive order builder).
- Why: The owner can read and review Python comfortably, which matters most when AI agents write the code (G5). FastAPI is simple and well known to AI tools (G3), and the pure money module keeps the core logic easy to test and isolated from frameworks (G1, G2). Accepted cost: two languages and two apps to run, and one network call for the live preview.

### D8. Stack: database
**Status:** Decided

**Decision: SQLite for this build, written so switching to PostgreSQL is a config change.**
- **SQLite settings:** STRICT tables (enforce integer columns for money) and foreign keys turned on.
- **Database access:** SQLAlchemy 2.0. It supports SQLite and Postgres alike, and makes the conditional "mark paid only if pending" and "reduce stock only if enough" updates (D5, D6) explicit.
- **Constraints in the DB, not just in code:** uniqueness on ledger entries per order (D5), stock ≥ 0, quantity ≥ 1, money columns are integers.
- **Schema setup:** tables are created on startup; a **seed script** loads a few supplements (with COGS and suggested retail), one provider, one patient, one admin, and starting stock.
- Rejected: PostgreSQL now (production-grade, but needs Docker or a local install for the developer and the grader, which costs setup time (G3)), SQLModel (newer, and AI tools mix up versions), raw SQL (more repetitive code).
- Why: zero setup, so anyone can clone and run (G3), it supports every guarantee the money flow needs (G1), and there's a clear production path (G2, G5).
- **Known limitation, for the writeup:** SQLite handles one write at a time, so the concurrency tests (double pay, last unit of stock) are less demanding than they'd be against production Postgres. The guarantees rely on conditional updates and constraints, which work the same on Postgres.
- Next steps: Alembic migrations; Postgres in production; DB-level append-only enforcement (D4).

### D9. Stack: frontend approach
**Status:** Decided

**9a. React + Vite + TypeScript.** Screens: provider order builder (live preview → confirm), provider dashboard (sales, earnings, product list), patient order review and payment page, admin stock page. TypeScript types for API calls are generated from FastAPI's OpenAPI schema, so the frontend and backend can't silently drift (G2).
- Rejected: plain JavaScript (no safety net on API shapes), Python-rendered pages + htmx (single language, but less suited to the interactive order builder, and less familiar to AI tools).

**9b. Styling: Pico.css (classless) themed with Cerbo's public brand tokens**, so the slice looks like a natural part of Cerbo's product rather than a generic demo. Source: the CSS variables on cer.bo's marketing site (retrieved Oct 5, 2026).
- Primary blue `#1570ef` (hover/darker `#175cd3`, light tint `#eff8ff`); secondary magenta `#D70073`, used sparingly for one accent (e.g. the "you receive" figure); gray scale `#101828` (headings) → `#667085` (body text) → `#eaecf0` (borders).
- Font: Inter (free, Google Fonts). Corner radius: 8px. Their display serif ("Doyle") is a licensed font and is **not** used.
- Caveat: these are marketing-site tokens; Cerbo's in-app EHR UI may differ. Good enough to signal product fit; styling isn't graded.
- Product-fit note for the writeup: Cerbo already advertises in-house inventory management for supplements (with a Fullscript integration) and patient payments through its portal, so this feature extends existing product surfaces rather than inventing new ones.

**9c. Money in the frontend:**
- The API sends and receives **integer cents only**.
- The frontend converts to dollars **only for display**.
- Typed prices ("19.99") are converted to cents by **one small, tested function that parses the text**, never `value * 100` (in JavaScript, `19.99 * 100 = 1998.9999…`).
- The frontend never computes the split; it calls the backend preview endpoint (D7).

### D10. Stubs and seams
**Status:** Decided

**Pattern:** each external dependency is a small interface plus a fake implementation, selected in **one config spot**. Swapping in a real implementation changes only that spot.

| Seam | Stub in this build | Real version later |
|---|---|---|
| **Auth** | A role switcher in the UI sends a user ID header. The backend has one `current_user` dependency. **Every endpoint enforces role and ownership** (providers see only their orders, patients only theirs, admin only admin screens). | Real login (OAuth/SSO); patient magic links (unguessable per-order links) |
| **Payments** | `PaymentProvider.charge(amount_cents, idempotency_key, payment_method)`. `FakePaymentProvider` approves by default; test tokens (e.g. `fake_card_decline`) simulate a decline. Same key + amount + method → same result; an approval is permanent; after a decline, a different method is a new attempt (see D5). | Stripe or similar, using the order ID as idempotency key; webhooks for reconciliation |
| **Notifications** | `Notifier` interface; the fake logs to the console. The provider UI shows the patient's order link to copy. | Email/SMS service; Cerbo patient portal messaging |
| **Fulfillment** | `Fulfillment.ship(order)` is called after payment commits; the fake logs "would ship order #N". | Warehouse/shipping partner integration |

- Rejected: a fake login page (more UI, proves nothing extra), Stripe test mode (needs keys and setup; the brief says to fake it), a fake email inbox page (extra UI).
- **Why ownership checks matter with fake auth:** the login is fake, but the permission rules are real, and real auth would rely on them (G1, G2). The reviewer's security pass checks them.
- The README includes a **"What's stubbed"** table mirroring the one above.

---

## Phase 6 decisions (2026-10-09, after deployment)

### D11. Clinical notes are written by the provider, never generated
**Status:** Decided

Each order line carries **dosing instructions** (pre-filled from a per-product default in the catalog, editable) and an optional **"why I recommend this"** note. Both are plain text the provider types; the patient sees them on the order page and receipt. Nothing in the app is generated: every number comes from the integer-cents formulas and every word of clinical text comes from a person.
- Rejected: AI-suggested dosing or notes. For clinical content, "the provider wrote it" is the correct answer; a generated dose is a liability, not a feature.
- Text is snapshotted on the line at creation like prices, rendered as plain text (no HTML), with length limits (dosing ≤ 200 chars, note ≤ 500).

### D12. Research donations: 5% of the provider's margin, matched to each product
**Status:** Decided

- **Where it goes:** each product maps to one research fund (seeded below). An order's donation can therefore split across several funds, one per product line.
- **How much:** a single on/off switch per order, fixed at **5% (500 bps) of the provider's margin on each line**. When on, each line's donation is `floor(line_margin_cents × 500 / 10000)` where `line_margin = line_total − line_cogs`. Rounded **down, per line**, so the donation never exceeds 5% and each fund's amount is exactly traceable to its line. Lines whose product has no fund donate 0.
- **Who pays:** the provider, out of their payout. The patient's price, the COGS, and the 75 bps fee (still on the full subtotal) are unchanged. New invariant: `subtotal = COGS + fee + donation + provider payout`. Guardrail: payout after donation must be ≥ 0, otherwise `DONATION_EXCEEDS_PAYOUT`.
- **Recorded like everything else:** the rate and per-line donation and fund (name + URL) are snapshotted at creation; payment writes one `research_donation` ledger row **per fund**; the audit gains a fourth check, *donation matches rate*.
- **What the patient sees:** that their provider is donating part of their earnings from this order, and to which funds (with links). **Not the amount**: 5% of margin would reveal the provider's markup.
- **Demo honesty:** no money is sent anywhere. The fund list is labeled as example organizations, not affiliated, no donations made. In production this needs a disbursement partner, tax-receipt handling, and a check of charitable-solicitation rules.
- Rejected: a patient round-up (changes what the patient pays, contradicting D1/D3, and puts an ask inside a clinical recommendation); a popup per item (friction in a daily workflow); a free-entry percentage (more validation, little value for a demo).

Seed funds (links checked 2026-10-09):

| Product | Fund | Link |
|---|---|---|
| Omega-3 Fish Oil | American Heart Association: research programs | https://professional.heart.org/en/research-programs |
| Vitamin D3 + K2 | ASBMR Fund for Research and Education (bone and mineral research) | https://www.asbmr.org/About/Fund-for-Research-and-Education |
| Probiotic 50B | Crohn's & Colitis Foundation: research | https://www.crohnscolitisfoundation.org/research |
| Magnesium Glycinate | American Migraine Foundation | https://americanmigrainefoundation.org/ |

The Migraine Research Foundation was considered for magnesium and rejected: its domain currently serves unrelated gambling content.

### D13. Patients can remove items before paying
**Status:** Decided

While an order is `pending_payment`, its patient can remove a line ("I already have D3"). At least one line must remain (otherwise: "At least one item must remain. Ask your provider to cancel the order."). The server recomputes the order's subtotal, COGS, fee, donation, and payout from the **remaining lines' stored prices and the order's stored rates**, using the same money functions; nothing is re-read from the catalog. Removed lines are kept (`removed_at`), excluded from totals, stock, ledger, and units sold, and shown to the provider as "Removed by patient" on the dashboard and audit.
- Concurrency: removal uses the same conditional-update pattern as pay and cancel, so remove-vs-pay has exactly one winner.
- Rejected: patient asks, provider approves (round trips for a decision that's the patient's to make); undo (not needed for the demo; the provider can rebuild the order).

### D14. Input limits
**Status:** Decided

Request models cap `qty` at 1–1,000 and `unit_price_cents` at ≤ 1,000,000 ($10,000); one product may appear on only one line per order (`DUPLICATE_PRODUCT`). Ordering more than current stock stays allowed (stock is enforced at payment, D6) but the preview returns available stock per line and the builder warns. Found while reviewing the walkthrough recording: an absurd quantity previously overflowed SQLite's integer column with a 500.

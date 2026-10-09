# Tasks: In-House Supplement Ordering

_Last updated: 2026-10-05 · Source of truth: [`prd.md`](prd.md), [`architecture.md`](architecture.md)_

Work **one task at a time, in order**, following `.cursor/rules/workflow.mdc` (tests first → implement → verifier → reviewer → diagrammer → report). A task is done only when verifier says **VERIFIED** and reviewer says **No blocking issues**.

**Conventions for every task**
- Architecture §3 rules are Blocking if violated (no floats in money, pure money module, snapshot orders, append-only, ownership checks, stubs chosen only in `config.py`, thin routers).
- Backend tests: `cd backend && uv run pytest`. Frontend: `cd frontend && npm run build && npm run lint && npm test`.
- In your report, list anything where you had to correct an AI suggestion or guessed at an API (e.g. a library option that didn't exist). The owner copies these into `docs/ai-log.md`.
- UI tasks (T12–T15): write tests only for logic; verify the UI with the manual checklist in the task.

---

## Phase 1: Foundation

### T0. Scaffold the repo
Create `backend/` (uv project: FastAPI, Uvicorn, SQLAlchemy 2.0, Pydantic v2; dev: pytest, Hypothesis, ruff, mypy) and `frontend/` (Vite React TypeScript; Vitest; ESLint). Add `GET /health`. Add a root `.gitignore` and a README with run/test commands.
**Done when:**
- [x] `uv run pytest` passes a test for `GET /health` → `{"status": "ok"}`.
- [x] `uv run ruff check` and `uv run mypy app` pass.
- [x] `npm run build`, `npm run lint`, `npm test` pass (one trivial Vitest test).
- [x] README documents how to install, run both apps, and run tests.

### T1. Money module (`backend/app/domain/money.py`)
Implement architecture §4: `compute_fee`, `compute_split`, `validate_order`, `PricingError` with codes. Pure Python, no framework imports.
**Done when tests prove:**
- [x] Every row of PRD §6.4 (fee and payout exact to the cent), including the $2.00 tie → 2¢, $0.66 → 0¢, $0.67 → 1¢.
- [x] 2 × $10.10 gives a fee of 15¢ (per-order rounding), not 16¢.
- [x] Price = COGS on every line → `NEGATIVE_PAYOUT`.
- [x] $100.00 / COGS $99.25 → accepted, payout 0. $100.00 / COGS $99.26 → `NEGATIVE_PAYOUT`.
- [x] A line priced below COGS → `LINE_BELOW_COGS` with the right `line_index`, even when the order total would be positive.
- [x] `EMPTY_ORDER`, `INVALID_QUANTITY` (0, −1), `INVALID_PRICE` (0, negative).
- [x] Hypothesis property: for random valid inputs, `subtotal == cogs_total + platform_fee + provider_payout` and `platform_fee == compute_fee(subtotal, fee_bps)`.
- [x] A test (or lint check) confirms `money.py` imports nothing from fastapi, sqlalchemy, or `app.*`.

### T2. Database, models, seed
`db.py` (engine; pragmas `foreign_keys=ON`, `busy_timeout=5000`; STRICT tables or the CHECK fallback; `BEGIN IMMEDIATE` transaction recipe), `models.py` (architecture §5), `seed.py` (idempotent).
**Done when tests prove:**
- [x] Seed creates the users and products from architecture §5; running it twice doesn't duplicate.
- [x] The DB rejects: stock −1, qty 0, unit price < unit COGS on a line, an order whose split doesn't add up, negative payout, a second `cerbo_fee` ledger row for the same order, an unknown status/role/entry type, a non-integer money value.
- [x] Tests use a fresh temp **file** database per test (shared fixture).

### T3. Auth seam
`seams/auth.py`: `current_user` from `X-User-Id`, `require_role`, `require_order_access`. `GET /users`, `GET /me`.
**Done when tests prove:**
- [x] Missing or unknown `X-User-Id` → 401.
- [x] `require_role("provider")` blocks a patient → 403.
- [x] `GET /users` lists seed users with roles; `GET /me` returns the caller.

---

## Phase 2: Core money flow (backend)

### T4. Catalog and provider product list
`GET /products`, `GET /provider/products`, `PUT /provider/products/{product_id}` (enabled, default price; validated with `validate_order` at qty 1).
**Done when tests prove:**
- [x] A provider sees their list with stock; a patient gets 403.
- [x] A default price that would make the payout negative at qty 1 → 422 with `NEGATIVE_PAYOUT`; a valid one saves.
- [x] A provider can't change another provider's list.

### T5. Order preview
`POST /orders/preview` → `OrderSplit` or a pricing error. No DB writes.
**Done when tests prove:**
- [x] The response matches `compute_split` for a multi-line order (all cents exact).
- [x] Pricing errors return 422 with code and `line_index`.
- [x] A product not enabled for this provider → `PRODUCT_UNAVAILABLE`.
- [x] Row counts in all tables are unchanged after a preview.

### T6. Create, view, and cancel orders
`POST /orders` (snapshot price, COGS, name, fee_bps; status `pending_payment`; call `Notifier.order_created`; return patient link), `GET /orders/{id}`, `GET /patient/orders`, `POST /orders/{id}/cancel`.
**Done when tests prove:**
- [x] The created order's stored split equals the preview for the same input.
- [x] Changing a product's COGS or the provider's default price afterward does **not** change the order (AC2.5).
- [x] The notifier fake was called once with the patient link.
- [x] The patient can view their order; another patient and another provider get **404**.
- [x] The patient ID must belong to a `patient` user.
- [x] Cancel works on `pending_payment`; cancelling a cancelled order → 409 `ORDER_NOT_CANCELLABLE`.

### T7. Payment seam
`seams/payment_provider.py`: `PaymentProvider` protocol and `FakePaymentProvider` (architecture §8), wired via `config.py`.
**Done when tests prove:**
- [x] `fake_card_ok` approves with a ref; `fake_card_decline` declines with a reason.
- [x] Same idempotency key + amount + payment method → same result, and `charge_count` doesn't increase. An approval is permanent; after a decline, a different payment method is a new attempt (decisions.md D5).

### T8. Pay endpoint ⭐ (most important task)
`POST /orders/{id}/pay` implementing architecture §7 exactly.
**Done when tests prove:**
- [x] Happy path: status `paid`, `paid_at` and `payment_ref` set, stock decremented by each line's qty, exactly 4 ledger rows; `patient_payment == subtotal`; the three allocations sum to it and equal the order's `cogs_total`, `platform_fee`, `provider_payout` (AC4.2, AC4.3); fulfillment fake called once.
- [x] Decline: 402; order still `pending_payment`; stock unchanged; 0 ledger rows; a retry with `fake_card_ok` then succeeds.
- [x] Out of stock (order 2 × Probiotic with stock 1): 409 `OUT_OF_STOCK`; nothing charged (`charge_count` 0) or written.
- [x] Paying an already-paid order returns 200 with the same receipt; still one charge and 4 ledger rows.
- [x] **Concurrent double pay** (two threads, same order): one charge, one paid order, 4 ledger rows; both responses succeed with the same receipt.
- [x] **Last unit race** (two patients, two orders, one Probiotic left, concurrent): exactly one succeeds; stock ends at 0, never negative.
- [x] Cancelled order → 409 `ORDER_NOT_PAYABLE`. Another patient → 404. A provider → 403.

### T9. Reporting: dashboard and audit
`GET /provider/dashboard`, `GET /orders/{id}/audit` (architecture §6), totals sourced from `ledger_entries`.
**Done when tests prove:**
- [x] With a known scenario (e.g. 2 paid, 1 pending, 1 cancelled), totals for GMV, fees, and earnings are exact; units per product are correct; only paid orders count.
- [x] Pending orders are listed separately; cancelled ones aren't in totals.
- [x] A provider sees only their own data.
- [x] The audit returns lines, split, ledger rows, and `recomputed_fee_matches: true`; for an unpaid order, ledger is empty.
- [x] Follow-up: the audit also returns `split_adds_up` and `ledger_matches_split`, true for a paid and a pending order.

### T10. Admin stock and COGS
`GET /admin/products`, `PUT /admin/products/{id}`.
**Done when tests prove:**
- [x] Admin can set stock and COGS; non-admins → 403.
- [x] Stock −1 or COGS 0 → 422.
- [x] A COGS change doesn't affect existing orders (re-asserts AC2.5 through this endpoint).

---

## Phase 3: Frontend

### T11. Frontend foundation
Generate API types from `/openapi.json` (`openapi-typescript`, npm script `gen:api`); small fetch client that adds `X-User-Id` and surfaces `error.code`/`message`; `RoleSwitcher`; routing shell; Pico + `theme.css` (architecture §9); `lib/money.ts`.
**Done when:**
- [x] Vitest proves `parseDollarsToCents`: "19.99" → 1999, "20" → 2000, "0.5" → 50, "$1,234.56" → 123456; rejects "1.999", "-5", "abc", "". And `formatCents`: 1999 → "$19.99", 5 → "$0.05", 123456 → "$1,234.56".
- [x] No `* 100` or `parseFloat` in `lib/money.ts`.
- [x] Manual: switching roles changes `GET /me` and the visible nav.

### T12. Provider: product list page
**Manual checklist:** toggle enabled; edit default price (typed as dollars) with an inline "you'd receive $X at qty 1" from the preview endpoint; a rejected price shows the error; stock shown as "N in stock" / "Out of stock".

### T13. Provider: order builder → confirm → created
**Manual checklist:** pick a patient; add/remove lines from enabled products (stock shown); prices pre-filled; live preview updates (subtotal, COGS, fee, **you receive** in the accent color); errors show on the right line and disable Continue; the review screen shows the full breakdown and requires an explicit Confirm; the created screen shows the patient link with a copy button.

### T14. Patient: order, pay, receipt
**Manual checklist:** "My orders" lists the patient's orders with status; the order page shows items, total, and "Prices set by your provider on {date}"; payment method selector (OK / decline test card); decline shows a clear message and allows retry; out of stock shows a clear message; double-clicking Pay produces one payment (button disabled while pending, and the backend is idempotent anyway); the receipt shows paid status.

### T15. Provider dashboard, audit view, admin page
**Manual checklist:** dashboard totals, paid orders table linking to the audit view, units per product, pending orders with Cancel; the audit view shows lines, split, ledger rows, and the three ✓ integrity checks (fee matches formula, split adds up, ledger matches split); the admin page edits stock and COGS, and providers/patients can't reach it.

---

## Phase 4: Wrap-up

### T16. End-to-end check and README
- [x] An API-level pytest runs the full flow: provider creates order → patient declines → patient pays → dashboard and audit reflect it to the cent.
- [x] README: one-paragraph overview, setup and run commands, demo walkthrough (with seed users), **"What's stubbed"** table (PRD §8), links to `docs/`.
- [x] Diagrammer has produced `docs/diagrams/` (overview, data model, pay flow).

### T17. Writeup (owner + Claude, not Cursor)
Key decisions and tradeoffs (from `decisions.md`), what was cut and what's next (PRD §10, architecture §11), and how AI was used (from `docs/ai-log.md`).

---

## Phase 5: Interface polish (optional, post-submission-ready)

Design source of truth: [`ui-design.md`](ui-design.md). **Frontend only.** No backend, API, or `money.py` changes; the frontend still never computes the split (bar widths are display proportions of API-returned cents). No new pages; no change to what any page fetches or sends.

### T18. Design system, app shell, and the split bar
Replace Pico with a small hand-written stylesheet built on the tokens in `ui-design.md` (add `@fontsource-variable/inter`; remove `@picocss/pico`). Build the app shell (top bar, nav, demo role switcher marked as a demo tool) and the shared components: `SplitBar` (full + compact), `StatusPill`, `Money`, button styles, inline error, empty state.
**Done when:**
- [x] Every existing page still renders and works (manual click-through of the T12–T15 checklists), now in the new shell.
- [x] Vitest covers `SplitBar` proportions: widths from `cogs/subtotal`, `fee/subtotal`, `payout/subtotal`; fee segment never under its minimum width; labels print `formatCents` of the props, unchanged.
- [x] `npm run build`, `npm run lint`, `npm test` pass; backend tests untouched and passing.
- [x] Keyboard focus visible on every control; layout works at 375px.

### T19. Apply the design to every page
Order builder (two columns, sticky summary with live split bar), review/created, patient order page (receipt layout, no split bar), dashboard (lead sentence, totals bar, tables with compact bars and status pills), audit (ledger table + three-item checklist), admin (dense inline-edit table), products page.
**Done when:**
- [x] Manual click-through of the README demo walkthrough on a fresh database: every number matches the README to the cent.
- [x] Each page matches its description in `ui-design.md`; screenshots of each page at desktop width attached to the report.
- [x] Builds, lint, and all tests pass.

---

## Phase 6: Post-deploy features (2026-10-09)

Decisions: D11–D14 in [`decisions.md`](decisions.md). Same workflow and rules as before: tester → implement → verifier → reviewer; **no git branches, commits, resets, or pushes**; the frontend never computes money; every new money path is integer cents through `money.py`. No migrations: schema changes ship with `create_all`, so delete `backend/cerbo.db` locally after pulling (the live demo resets on deploy and on login). Do the tasks in order; T23 and T24 both touch the split.

### T20. Deploy packaging and demo login (done 2026-10-09, before this plan)
One Docker image serves the API under `/api` and the built frontend at `/`; `POST /demo/reset` exists only with `DEMO_MODE`; **Log in** and **Log out** reset the shared demo data. Live on DigitalOcean App Platform at https://cerbowk1-e3z6c.ondigitalocean.app/, redeployed on every push to the GitHub mirror.

### T21. Input limits and a fuller receipt
- Strict request limits: `qty` 1–1,000, `unit_price_cents` ≤ 1,000,000; reject a second line for the same product with `DUPLICATE_PRODUCT` (line_index of the duplicate). Applies to preview and create.
- Preview returns `stock_available` per line; the builder shows a non-blocking "Only N in stock. Payment will fail unless stock is added." when qty > stock.
- Audit response and page add `payment_ref` and `paid_at`. Patient receipt shows payment reference, paid date, and a "What happens next" line (Cerbo ships the order; stubbed).
- Decline message on the patient page: "Payment was declined. Try a different card."
- Products page: label the per-unit earnings "at qty 1".
**Done when:**
- [x] Tests: qty 0 / 1,001 / 10^17 and price 1,000,001 → 422 (never 500); duplicate product → `DUPLICATE_PRODUCT`; qty > stock previews and creates, fails at pay as before.
- [x] Audit and receipt show payment reference and paid date for a paid order.
- [x] All existing tests pass; lint/build pass.

### T22. Dosing instructions and provider notes (D11)
- `products.default_dosing` (seeded, e.g. "Example: 1 capsule daily with a meal"; admin can edit it on the admin page).
- `order_lines.dosing` (≤ 200 chars, required, pre-filled from the product default) and `order_lines.note` (≤ 500, optional, "Why I recommend this"). Trimmed; snapshotted at creation like prices.
- Builder: dosing input and an optional note per line; review step shows both. Patient order page and receipt show them under each item. Plain text only.
**Done when:**
- [x] Tests: defaults pre-fill via the catalog response; over-length and blank dosing rejected; later catalog edits don't change existing orders' text; text containing `<script>` is stored and rendered as text.
- [x] Click-through: provider writes a note, patient sees it with the dosing.

### T23. Research donations (D12)
- `research_funds` table (id, name, url, description) seeded with the four funds in D12; `products.research_fund_id` (nullable).
- `money.py`: extend the split with a `donation_bps` input (0 or 500). Per line `donation = (line_margin × donation_bps) // 10000` when the product has a fund, else 0. Payout = subtotal − COGS − fee − total donation. New pricing error `DONATION_EXCEEDS_PAYOUT` if payout < 0. Property test: the four-way split always adds up and donation ≤ 5% of margin.
- Schema: `orders.donation_bps`, `orders.donation_cents`; `order_lines.donation_cents`, `fund_id`, `fund_name`, `fund_url` (snapshots). DB CHECK: `subtotal = cogs + fee + donation + payout`, `donation_cents >= 0`.
- Ledger: new entry type `research_donation` with a nullable `fund_id`; one row per fund with a donation > 0. Replace the single unique constraint with partial unique indexes: `(order_id, entry_type)` where entry_type ≠ `research_donation`, and `(order_id, fund_id)` where it is.
- Preview/create accept `donate: bool`. Audit adds `donation_matches_rate` (recomputed per line from stored amounts) and includes donation in `split_adds_up` and `ledger_matches_split`. Dashboard adds "Donated to research" total.
- UI: an on/off switch in the order summary ("Donate 5% of my margin to medical research"), remembered per browser as the provider's default; the split bar gets a fourth segment; each line shows its fund name, clickable to reveal the description and an external "Learn more" link (`target="_blank" rel="noopener noreferrer"`). Patient page: "Dr. {name} is donating part of their earnings from this order to medical research:" plus the fund names and links, **no amounts**. A small note wherever funds are listed: "Example organizations for this demo. Not affiliated; no donations are made."
**Done when:**
- [x] Money tests: worked example with donation on and off, recomputed by hand in the test docstring; rounding-down case; product without a fund; `DONATION_EXCEEDS_PAYOUT` case; property test.
- [x] DB rejects a split that doesn't add up with donation included; ledger allows one donation row per fund and rejects a duplicate for the same fund.
- [x] Audit shows four ✓ checks; a tampered donation flips `donation_matches_rate` and `ledger_matches_split`.
- [x] Patient page never shows a donation amount.
- [x] README walkthrough gains a donation step with exact numbers.

### T24. Patient removes items before paying (D13)
- `order_lines.removed_at` (nullable). `POST /orders/{id}/lines/{line_id}/remove`: patient of the order only (others 404), order must be `pending_payment` (conditional update, same pattern as pay/cancel), at least one active line must remain (`LAST_LINE`). Recompute and store the order's split from the remaining lines' stored prices and the order's stored `fee_bps` and `donation_bps` via `money.py`.
- Pay, stock, ledger, dashboard units, and audit use active lines only; removed lines are listed separately as "Removed by patient".
- Patient page: a "Remove" button per line (with an "Are you sure?" inline step, not a browser dialog) while unpaid; totals update from the API response.
**Done when:**
- [x] Tests: removal recomputes fee and donation exactly; can't remove the last line; can't remove after paid or cancelled; another patient gets 404; concurrent remove vs pay has exactly one winner and the charge equals the final stored total.
- [x] Provider dashboard and audit show the removed line, struck through, excluded from totals; all integrity checks still ✓.

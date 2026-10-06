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

# Architecture: In-House Supplement Ordering

_Last updated: 2026-10-09 · Owner: Taylor Clements · Status: Approved for build_
_What and why: [`prd.md`](prd.md). Decision rationale: [`decisions.md`](decisions.md). Changes to this file need owner approval._
_Updated for D12 (research donations) and D13 (patient line removal)._

---

## 1. Stack

| Layer | Choice | Decision |
|---|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2 | D7 |
| Database | SQLite (file), SQLAlchemy 2.0; Postgres-ready | D8 |
| Backend tests | pytest, plus Hypothesis for property tests of the money module | D7 |
| Python tooling | `uv` | D7 |
| Frontend | React + Vite + TypeScript | D9 |
| API types | Generated from FastAPI's OpenAPI schema (`openapi-typescript`) | D9 |
| Frontend tests | Vitest (logic only: money parsing/formatting) | D9 |
| Styling | Pico.css, themed with Cerbo brand tokens | D9 |

## 2. Repo layout

```
cerbo_wk1/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py              # FastAPI app factory, router registration
│   │   ├── config.py            # settings + the ONE place stubs are chosen
│   │   ├── db.py                # engine, session, SQLite pragmas, BEGIN IMMEDIATE
│   │   ├── models.py            # SQLAlchemy tables + constraints
│   │   ├── domain/
│   │   │   └── money.py         # PURE: fee, split, pricing guardrails
│   │   ├── services/            # business operations (use domain + db + seams)
│   │   │   ├── catalog.py
│   │   │   ├── orders.py        # preview, create, cancel, get, remove line
│   │   │   ├── payments.py      # the pay transaction
│   │   │   ├── reporting.py     # dashboard, audit
│   │   │   └── admin.py
│   │   ├── seams/               # interfaces + fake implementations
│   │   │   ├── auth.py
│   │   │   ├── payment_provider.py
│   │   │   ├── notifier.py
│   │   │   └── fulfillment.py
│   │   ├── api/                 # thin FastAPI routers: parse, auth, call service, map errors
│   │   └── seed.py
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/                 # generated types + small fetch client
│       ├── lib/money.ts         # parseDollarsToCents, formatCents (tested)
│       ├── components/          # RoleSwitcher, SplitBreakdown, ...
│       ├── pages/
│       └── theme.css            # Pico overrides with Cerbo tokens
├── docs/
└── README.md
```

## 3. Rules (reviewer treats violations as Blocking)

1. **No floats in the money path.** Money is `int` cents everywhere: Python, SQL columns, JSON, TypeScript. The fee rate is `int` basis points. No `float()`, `Decimal` round-trips, or `* 100` on a parsed number.
2. **`domain/money.py` is pure.** No imports from FastAPI, SQLAlchemy, `app.services`, or `app.seams`. It is the **only** place the fee, split, and pricing guardrails are computed.
3. **The frontend never computes the split.** It calls `POST /orders/preview`. It only parses and formats amounts.
4. **Orders are snapshots.** Order lines copy `unit_price`, `unit_cogs`, product name, dosing/note, and research-fund fields; orders copy `fee_bps` and `donation_bps`. Nothing reads the live catalog to compute an existing order's money (including after a patient removes a line — recompute from remaining snapshots + stored rates).
5. **Append-only after payment.** No code path updates or deletes a paid order, its lines, or ledger entries. Before payment, a patient may soft-remove a line (`removed_at`); the row stays for audit.
6. **Every endpoint checks role and ownership** via `seams/auth.py`.
7. **Stubs are chosen only in `config.py`.** Services receive seams through FastAPI dependencies, never by importing a fake directly.
8. **Routers are thin.** Business logic lives in `services/`, money logic in `domain/money.py`.

## 4. Money module (`domain/money.py`)

```python
FEE_BPS_DEFAULT = 75
DONATION_BPS_OFF = 0
DONATION_BPS_ON = 500   # 5% of per-line margin when the provider opts in (D12)

@dataclass(frozen=True)
class LineInput:
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    has_research_fund: bool = False

@dataclass(frozen=True)
class LineSplit:
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int    # unit_price × qty
    line_cogs_cents: int     # unit_cogs × qty
    line_margin_cents: int   # line_total − line_cogs
    donation_cents: int      # floor(margin × donation_bps / 10000) if fund else 0

@dataclass(frozen=True)
class OrderSplit:
    lines: tuple[LineSplit, ...]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    donation_bps: int
    donation_cents: int
    provider_payout_cents: int

def compute_fee(subtotal_cents: int, fee_bps: int) -> int:
    # Round half up, integer only. Fee is once on the full subtotal.
    return (subtotal_cents * fee_bps + 5_000) // 10_000

def compute_split(lines, fee_bps, donation_bps=DONATION_BPS_OFF) -> OrderSplit: ...
def validate_order(lines, fee_bps, donation_bps=DONATION_BPS_OFF) -> OrderSplit:
    """compute_split + guardrails. Raises PricingError(code, detail, line_index | None)."""
```

**Four-way split (D12):** `provider_payout = subtotal − cogs_total − platform_fee − donation`. Donation is paid by the provider out of margin; the patient's price and the 75 bps fee (still on the full subtotal) are unchanged.

**Validation order** (first failure wins, reported with line index where applicable):
`INVALID_DONATION_BPS` → `EMPTY_ORDER` → `INVALID_QUANTITY` → `INVALID_PRICE` → `LINE_BELOW_COGS` → `DONATION_EXCEEDS_PAYOUT` (payout < 0 and donation > 0) or `NEGATIVE_PAYOUT`.

**Property tests (Hypothesis):** for random valid inputs, `subtotal == cogs + fee + donation + payout`, fee matches `compute_fee`, and donation ≤ 5% of total margin.

## 5. Data model

All money columns are `INTEGER` cents. SQLite runs with `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`, and **STRICT** tables. (Verify the installed SQLAlchemy version supports the `sqlite_strict` table option; if not, add `CHECK (typeof(col) = 'integer')` on money columns instead.)

```
users
  id              INTEGER PK
  name            TEXT NOT NULL
  role            TEXT NOT NULL CHECK (role IN ('provider','patient','admin'))

research_funds                             -- example orgs for D12 (demo; no real disbursement)
  id              INTEGER PK
  name, url, description   TEXT NOT NULL

products                                   -- Cerbo's catalog + stock (admin-owned)
  id                       INTEGER PK
  sku                      TEXT UNIQUE NOT NULL
  name                     TEXT NOT NULL
  unit_cogs_cents          INTEGER NOT NULL CHECK (unit_cogs_cents > 0)
  suggested_price_cents    INTEGER NOT NULL CHECK (suggested_price_cents > 0)
  stock_qty                INTEGER NOT NULL CHECK (stock_qty >= 0)
  default_dosing           TEXT NOT NULL
  research_fund_id         INTEGER FK research_funds NULL

provider_products                          -- each provider's offered list (provider-owned)
  provider_id              INTEGER FK users  ┐ PK
  product_id               INTEGER FK products ┘
  enabled                  INTEGER NOT NULL CHECK (enabled IN (0,1))
  default_price_cents      INTEGER NOT NULL CHECK (default_price_cents > 0)

orders
  id                       INTEGER PK
  provider_id              INTEGER FK users NOT NULL
  patient_id               INTEGER FK users NOT NULL
  status                   TEXT NOT NULL CHECK (status IN ('pending_payment','paid','cancelled'))
  fee_bps                  INTEGER NOT NULL CHECK (fee_bps >= 0)
  donation_bps             INTEGER NOT NULL CHECK (donation_bps IN (0, 500))
  subtotal_cents           INTEGER NOT NULL CHECK (subtotal_cents > 0)
  cogs_total_cents         INTEGER NOT NULL CHECK (cogs_total_cents > 0)
  platform_fee_cents       INTEGER NOT NULL CHECK (platform_fee_cents >= 0)
  donation_cents           INTEGER NOT NULL CHECK (donation_cents >= 0)
  provider_payout_cents    INTEGER NOT NULL CHECK (provider_payout_cents >= 0)
  payment_ref              TEXT NULL
  created_at, paid_at, cancelled_at
  CHECK (subtotal = cogs + fee + donation + payout)

order_lines
  id                       INTEGER PK
  order_id                 INTEGER FK orders NOT NULL
  product_id               INTEGER FK products NOT NULL
  product_name             TEXT NOT NULL      -- snapshot
  qty                      INTEGER NOT NULL CHECK (qty >= 1)
  unit_price_cents, unit_cogs_cents  INTEGER NOT NULL
  dosing                   TEXT NOT NULL
  note                     TEXT NULL
  donation_cents           INTEGER NOT NULL
  fund_id, fund_name, fund_url       -- fund snapshot (nullable when no fund)
  removed_at               TEXT NULL         -- D13: soft-removed by patient
  CHECK (unit_price_cents >= unit_cogs_cents)

ledger_entries                             -- append-only record of money movement
  id                       INTEGER PK
  order_id                 INTEGER FK orders NOT NULL
  entry_type               TEXT NOT NULL CHECK (entry_type IN
                             ('patient_payment','cerbo_cogs','cerbo_fee',
                              'provider_payable','research_donation'))
  amount_cents             INTEGER NOT NULL CHECK (amount_cents >= 0)
  created_at               TEXT NOT NULL
  fund_id                  INTEGER FK research_funds NULL
                             -- required iff entry_type = research_donation
  -- Partial unique indexes (D12): one non-donation row per (order, entry_type);
  -- one research_donation row per (order, fund_id).
```

**Ledger convention:** amounts are non-negative. For each paid order: `patient_payment = subtotal`, and `cerbo_cogs + cerbo_fee + research_donation(s) + provider_payable = patient_payment`. One `research_donation` row per fund with a donation > 0. Active lines only (D13): stock, ledger, and units sold ignore `removed_at IS NOT NULL`.

**Note:** the DB-level `CHECK` on the order invariant and `provider_payout_cents >= 0` duplicate the money module's guarantees on purpose. If application code ever computes a bad split, the write fails loudly.

**Schema setup:** `create_all` at startup; `seed.py` creates seed data idempotently (safe to re-run). Migrations (Alembic) are a next step.

### Seed data
- Users: **Dr. Maya Patel** (provider), **Jane Doe** and **Sam Lee** (patients), **Cerbo Admin** (admin).
- Research funds (D12): American Heart Association research programs; ASBMR Fund for Research and Education; Crohn's & Colitis Foundation research; American Migraine Foundation.
- Products (each mapped to one fund):

| SKU | Name | COGS | Suggested | Stock | Fund |
|---|---|---|---|---|---|
| MAG-GLY | Magnesium Glycinate | $12.00 | $24.00 | 50 | American Migraine Foundation |
| D3-K2 | Vitamin D3 + K2 | $9.00 | $18.00 | 40 | ASBMR |
| OMEGA3 | Omega-3 Fish Oil | $18.50 | $36.00 | 25 | AHA research programs |
| PROBIO50 | Probiotic 50B | $21.00 | $42.00 | **1** | Crohn's & Colitis Foundation |

- Dr. Patel has all four enabled at suggested prices.

## 6. API

All amounts are integer cents. Auth via header `X-User-Id` (D10). Errors return `{"error": {"code": "...", "message": "...", "line_index": n | null}}`.

| Method & path | Role | Purpose |
|---|---|---|
| `GET /health` | any | Liveness |
| `GET /users` | none (dev only) | Populate role switcher |
| `GET /me` | any | Current user |
| `GET /products` | provider, admin | Catalog with stock |
| `GET /provider/products` | provider | Own product list (enabled, default price, stock) |
| `PUT /provider/products/{product_id}` | provider | Set enabled / default price (validated at qty 1) |
| `POST /orders/preview` | provider | Validate + compute split (`donate: bool`); **no writes** |
| `POST /orders` | provider | Create order (snapshot, `donate: bool`); notify; return order + patient link |
| `GET /orders/{id}` | owning provider or patient | Order with active `lines`, `removed_lines`, and split |
| `POST /orders/{id}/cancel` | owning provider | Pending → cancelled |
| `POST /orders/{id}/lines/{line_id}/remove` | owning patient | Soft-remove line while pending (D13); recompute split via `money.py` from remaining stored prices + stored `fee_bps`/`donation_bps` |
| `POST /orders/{id}/pay` | owning patient | Pay; idempotent (§7); active lines only for stock/ledger |
| `GET /patient/orders` | patient | Own orders |
| `GET /provider/dashboard` | provider | GMV, fees, **donated to research**, earnings; paid orders; units (active lines); pending |
| `GET /orders/{id}/audit` | owning provider | Active lines, `removed_lines` ("Removed by patient"), split, ledger, four integrity flags: `recomputed_fee_matches`, `donation_matches_rate`, `split_adds_up` (subtotal = COGS + fee + donation + payout), `ledger_matches_split` (including per-fund `research_donation` rows) |
| `GET /admin/products` | admin | Stock + COGS |
| `PUT /admin/products/{id}` | admin | Set stock (≥ 0) and/or COGS (> 0) |

**Status codes:** 401 missing/unknown user · 403 wrong role · **404** for orders/lines the user doesn't own (don't reveal existence) · 422 pricing/validation errors · 409 `OUT_OF_STOCK`, `ORDER_NOT_PAYABLE`, `ORDER_NOT_CANCELLABLE`, `ORDER_NOT_REMOVABLE`, `LAST_LINE` · 402 `PAYMENT_DECLINED`.

**Order creation also checks:** the patient exists with role `patient`; every product is enabled for this provider (`PRODUCT_UNAVAILABLE`). Stock is **not** checked at creation (it's shown in the UI and enforced at payment, D6).

**Line removal (D13):** at least one active line must remain (`LAST_LINE`). Conditional update on `status = pending_payment` so remove-vs-pay has exactly one consistent winner; charge equals the final stored subtotal.

**Pay request:** `{"payment_method": "fake_card_ok" | "fake_card_decline"}`.

## 7. The payment transaction (D5, D6)

```mermaid
sequenceDiagram
  participant P as Patient
  participant API as POST /orders/{id}/pay
  participant DB as SQLite (one transaction)
  participant Pay as PaymentProvider
  participant F as Fulfillment
  P->>API: pay(payment_method)
  API->>DB: BEGIN IMMEDIATE
  API->>DB: load order (ownership check)
  alt already paid
    API->>DB: ROLLBACK
    API-->>P: 200 original receipt
  else cancelled
    API->>DB: ROLLBACK
    API-->>P: 409 ORDER_NOT_PAYABLE
  end
  API->>DB: UPDATE orders SET status='paid' WHERE id=? AND status='pending_payment'
  Note over API,DB: 0 rows → another request won; rollback, return its receipt
  API->>DB: per active line: UPDATE products SET stock_qty=stock_qty-? WHERE id=? AND stock_qty>=?
  Note over API,DB: any 0 rows → ROLLBACK, 409 OUT_OF_STOCK (nothing charged); removed_at lines skipped
  API->>Pay: charge(stored subtotal, idempotency_key=order_id, payment_method)
  alt declined
    API->>DB: ROLLBACK
    API-->>P: 402 PAYMENT_DECLINED (order still pending)
  end
  API->>DB: set payment_ref, paid_at; INSERT ledger rows (4 base + research_donation per fund)
  API->>DB: COMMIT
  API->>F: ship(order)  (after commit; failure is logged, not fatal)
  API-->>P: 200 receipt
```

**Why this order:** stock is checked before charging, so an out-of-stock order is never charged. The charge happens inside the transaction, so a decline rolls back the status and stock changes.

**SQLite specifics:** use `BEGIN IMMEDIATE` (via SQLAlchemy's documented pysqlite transaction-control recipe) so the write lock is taken at the start. This avoids lock-upgrade deadlocks between concurrent payers. Concurrency tests must use a **file-based** temp database; `:memory:` databases are per-connection.

**Known tradeoff:** calling an external service inside a DB transaction holds the write lock for the duration of the call. That's fine for a stub. In production, use authorize-then-capture: authorize outside, commit, capture, and reconcile via webhooks.

## 8. Seams (D10)

```python
# seams/payment_provider.py
class PaymentProvider(Protocol):
    def charge(self, amount_cents: int, idempotency_key: str, payment_method: str) -> ChargeResult: ...
# ChargeResult: approved: bool, ref: str | None, decline_reason: str | None

class FakePaymentProvider:
    # Approves unless payment_method == "fake_card_decline".
    # Replays the SAME attempt: same idempotency_key + amount + payment_method → stored result,
    #   no second charge. An approval is permanent for that key. A stored decline followed by a
    #   different payment_method is a new attempt (lets a patient retry after a decline, AC3.3).
    #   Real processors treat a reused key as the same request; production would use a key per
    #   attempt (e.g. order-12-attempt-2). See decisions.md D5.
    # Exposes charge_count for tests.
```

- `seams/auth.py`: `current_user` dependency reads `X-User-Id`; helpers `require_role(...)`, `require_order_access(order, user)`.
- `seams/notifier.py`: `Notifier.order_created(order, patient_link)`. Fake logs to console.
- `seams/fulfillment.py`: `Fulfillment.ship(order)`. Fake logs "would ship order #N".
- `config.py` builds the fakes; FastAPI dependencies hand them to services. Tests override dependencies to inspect calls.

## 9. Frontend

- **Role switcher** in the header (from `GET /users`); the selected user ID is sent as `X-User-Id` on every request.
- **Pages:** Provider: Products · New order (builder with donate switch → review & confirm → created, with patient link) · Dashboard · Order audit (includes removed lines). Patient: My orders · Order & pay (can remove lines while unpaid) · Receipt. Admin: Stock & COGS.
- **Live preview:** the order builder calls `POST /orders/preview` (debounced ~300 ms, `donate` flag) and renders the returned four-way split; errors appear inline on the offending line.
- **Patient remove:** inline confirm (not a browser dialog); totals refresh from the API response. Patient UI never shows donation amounts.
- **`lib/money.ts`:** `parseDollarsToCents("19.99") → 1999` via string parsing (reject more than 2 decimals, negatives, and non-numeric input); `formatCents(1999) → "$19.99"`. Vitest covers both.
- **Theme (`theme.css`):** Pico variables overridden with Cerbo tokens: primary `#1570ef` (hover `#175cd3`, tint `#eff8ff`), accent `#D70073` used only for the "You receive" figure, text `#101828`/`#667085`, borders `#eaecf0`, Inter font, 8px radius.

## 10. Testing strategy

- **Money module:** example table from PRD §6.4, plus boundaries and Hypothesis property tests. Highest priority.
- **Services and API:** pytest with a fresh temp SQLite file per test and dependency overrides for seams. Cover every AC in PRD §7, especially the concurrency cases (AC3.5, AC3.6) using threads.
- **Constraints:** direct DB tests prove the CHECK/UNIQUE constraints reject bad rows.
- **Frontend:** Vitest for `lib/money.ts` only. UI tasks are verified by build + typecheck + lint and a manual checklist in the task. Component tests are out of scope.

## 11. Known limitations (for the writeup)

- SQLite serializes writes, so the concurrency tests are less demanding than production Postgres. The guarantees come from conditional updates and constraints, which behave the same on Postgres.
- Append-only is enforced in application code only.
- An external payment call inside a DB transaction (see §7).
- Fake auth: `X-User-Id` is trivially spoofable. The ownership rules are real; identity is not.
- No migrations; schema is created at startup.

# Architecture: In-House Supplement Ordering

_Last updated: 2026-10-05 · Owner: Taylor Clements · Status: Approved for build_
_What and why: [`prd.md`](prd.md). Decision rationale: [`decisions.md`](decisions.md). Changes to this file need owner approval._

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
│   │   │   ├── orders.py        # preview, create, cancel, get
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
4. **Orders are snapshots.** Order lines copy `unit_price`, `unit_cogs`, and product name; orders copy `fee_bps`. Nothing reads the live catalog to compute an existing order's money.
5. **Append-only after payment.** No code path updates or deletes a paid order, its lines, or ledger entries.
6. **Every endpoint checks role and ownership** via `seams/auth.py`.
7. **Stubs are chosen only in `config.py`.** Services receive seams through FastAPI dependencies, never by importing a fake directly.
8. **Routers are thin.** Business logic lives in `services/`, money logic in `domain/money.py`.

## 4. Money module (`domain/money.py`)

```python
FEE_BPS_DEFAULT = 75

@dataclass(frozen=True)
class LineInput:
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int

@dataclass(frozen=True)
class LineSplit:
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int    # unit_price × qty
    line_cogs_cents: int     # unit_cogs × qty
    line_margin_cents: int   # line_total − line_cogs (pre-fee; display only)

@dataclass(frozen=True)
class OrderSplit:
    lines: tuple[LineSplit, ...]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    provider_payout_cents: int

def compute_fee(subtotal_cents: int, fee_bps: int) -> int:
    # Round half up, integer only. subtotal_cents >= 0, so // is safe.
    return (subtotal_cents * fee_bps + 5_000) // 10_000

def compute_split(lines: Sequence[LineInput], fee_bps: int) -> OrderSplit: ...
def validate_order(lines: Sequence[LineInput], fee_bps: int) -> OrderSplit:
    """compute_split + guardrails. Raises PricingError(code, detail, line_index | None)."""
```

**Payout is the remainder:** `provider_payout = subtotal − cogs_total − platform_fee`.

**Validation order** (first failure wins, reported with line index where applicable):
`EMPTY_ORDER` → `INVALID_QUANTITY` (qty < 1) → `INVALID_PRICE` (price ≤ 0 or COGS ≤ 0) → `LINE_BELOW_COGS` → `NEGATIVE_PAYOUT`.

**Property tests (Hypothesis):** for random valid inputs, the invariant `subtotal == cogs_total + platform_fee + provider_payout` holds, and `platform_fee == compute_fee(subtotal, fee_bps)`.

## 5. Data model

All money columns are `INTEGER` cents. SQLite runs with `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`, and **STRICT** tables. (Verify the installed SQLAlchemy version supports the `sqlite_strict` table option; if not, add `CHECK (typeof(col) = 'integer')` on money columns instead.)

```
users
  id              INTEGER PK
  name            TEXT NOT NULL
  role            TEXT NOT NULL CHECK (role IN ('provider','patient','admin'))

products                                   -- Cerbo's catalog + stock (admin-owned)
  id                       INTEGER PK
  sku                      TEXT UNIQUE NOT NULL
  name                     TEXT NOT NULL
  unit_cogs_cents          INTEGER NOT NULL CHECK (unit_cogs_cents > 0)
  suggested_price_cents    INTEGER NOT NULL CHECK (suggested_price_cents > 0)
  stock_qty                INTEGER NOT NULL CHECK (stock_qty >= 0)

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
  subtotal_cents           INTEGER NOT NULL CHECK (subtotal_cents > 0)
  cogs_total_cents         INTEGER NOT NULL CHECK (cogs_total_cents > 0)
  platform_fee_cents       INTEGER NOT NULL CHECK (platform_fee_cents >= 0)
  provider_payout_cents    INTEGER NOT NULL CHECK (provider_payout_cents >= 0)
  payment_ref              TEXT NULL          -- from PaymentProvider on success
  created_at, paid_at, cancelled_at          -- ISO-8601 UTC text; paid_at/cancelled_at nullable
  CHECK (subtotal_cents = cogs_total_cents + platform_fee_cents + provider_payout_cents)

order_lines
  id                       INTEGER PK
  order_id                 INTEGER FK orders NOT NULL
  product_id               INTEGER FK products NOT NULL
  product_name             TEXT NOT NULL      -- snapshot
  qty                      INTEGER NOT NULL CHECK (qty >= 1)
  unit_price_cents         INTEGER NOT NULL CHECK (unit_price_cents > 0)
  unit_cogs_cents          INTEGER NOT NULL CHECK (unit_cogs_cents > 0)
  CHECK (unit_price_cents >= unit_cogs_cents)

ledger_entries                             -- append-only record of money movement
  id                       INTEGER PK
  order_id                 INTEGER FK orders NOT NULL
  entry_type               TEXT NOT NULL CHECK (entry_type IN
                             ('patient_payment','cerbo_cogs','cerbo_fee','provider_payable'))
  amount_cents             INTEGER NOT NULL CHECK (amount_cents >= 0)
  created_at               TEXT NOT NULL
  UNIQUE (order_id, entry_type)            -- backstop against double-writes (D5)
```

**Ledger convention:** amounts are non-negative. For each paid order: `patient_payment = subtotal` (money in), and `cerbo_cogs + cerbo_fee + provider_payable = patient_payment` (where it went). Future refunds and payouts would add new entry types (e.g. `refund`, `provider_payout_settled`) rather than editing rows.

**Note:** the DB-level `CHECK` on the order invariant and `provider_payout_cents >= 0` duplicate the money module's guarantees on purpose. If application code ever computes a bad split, the write fails loudly.

**Schema setup:** `create_all` at startup; `seed.py` creates seed data idempotently (safe to re-run). Migrations (Alembic) are a next step.

### Seed data
- Users: **Dr. Maya Patel** (provider), **Jane Doe** and **Sam Lee** (patients), **Cerbo Admin** (admin).
- Products:

| SKU | Name | COGS | Suggested | Stock |
|---|---|---|---|---|
| MAG-GLY | Magnesium Glycinate | $12.00 | $24.00 | 50 |
| D3-K2 | Vitamin D3 + K2 | $9.00 | $18.00 | 40 |
| OMEGA3 | Omega-3 Fish Oil | $18.50 | $36.00 | 25 |
| PROBIO50 | Probiotic 50B | $21.00 | $42.00 | **1** (to demo out-of-stock and the last-unit race) |

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
| `POST /orders/preview` | provider | Validate + compute split; **no writes** |
| `POST /orders` | provider | Create order (snapshot); notify; return order + patient link |
| `GET /orders/{id}` | owning provider or patient | Order with lines and split |
| `POST /orders/{id}/cancel` | owning provider | Pending → cancelled |
| `POST /orders/{id}/pay` | owning patient | Pay; idempotent (§7) |
| `GET /patient/orders` | patient | Own orders |
| `GET /provider/dashboard` | provider | Totals, paid orders, units per product, pending orders |
| `GET /orders/{id}/audit` | owning provider | Lines, split, ledger, and three integrity flags: `recomputed_fee_matches` (fee = formula), `split_adds_up` (subtotal = COGS + fee + payout), `ledger_matches_split` (paid: exactly the 4 ledger rows, each equal to the stored split; unpaid: empty ledger) |
| `GET /admin/products` | admin | Stock + COGS |
| `PUT /admin/products/{id}` | admin | Set stock (≥ 0) and/or COGS (> 0) |

**Status codes:** 401 missing/unknown user · 403 wrong role · **404** for orders the user doesn't own (don't reveal existence) · 422 pricing/validation errors · 409 `OUT_OF_STOCK`, `ORDER_NOT_PAYABLE` (cancelled), `ORDER_NOT_CANCELLABLE` · 402 `PAYMENT_DECLINED`.

**Order creation also checks:** the patient exists with role `patient`; every product is enabled for this provider (`PRODUCT_UNAVAILABLE`). Stock is **not** checked at creation (it's shown in the UI and enforced at payment, D6).

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
  API->>DB: per line: UPDATE products SET stock_qty=stock_qty-? WHERE id=? AND stock_qty>=?
  Note over API,DB: any 0 rows → ROLLBACK, 409 OUT_OF_STOCK (nothing charged)
  API->>Pay: charge(subtotal, idempotency_key=order_id, payment_method)
  alt declined
    API->>DB: ROLLBACK
    API-->>P: 402 PAYMENT_DECLINED (order still pending)
  end
  API->>DB: set payment_ref, paid_at; INSERT 4 ledger_entries
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
- **Pages:** Provider: Products · New order (builder → review & confirm → created, with patient link) · Dashboard · Order audit. Patient: My orders · Order & pay · Receipt. Admin: Stock & COGS.
- **Live preview:** the order builder calls `POST /orders/preview` (debounced ~300 ms) and renders the returned split; errors appear inline on the offending line.
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

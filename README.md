# In-house supplement ordering

A provider builds a supplement order for a patient, Cerbo charges the patient, and the order's price, cost, platform fee, and provider payout are stored in integer cents so the dashboard and audit match to the cent. Auth, card charging, notifications, and fulfillment are stubs; role checks and the money split are real. The API seeds its users and catalog on startup.

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js `^20.19.0` or `>=22.12.0`

The backend pins Python 3.12 in `backend/.python-version`.

## Backend

Install dependencies and start the API (this creates `backend/cerbo.db` and loads the seed data):

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

The API listens on http://127.0.0.1:8000. Liveness is `GET /health`.

Run tests, lint, and the type check:

```bash
cd backend
uv run pytest
uv run ruff check
uv run mypy app
```

## Frontend

Install dependencies and start the app (start the API first; Vite proxies `/api` to port 8000):

```bash
cd frontend
npm install
npm run dev
```

The app listens on http://127.0.0.1:5173.

Run tests, lint, and the production build:

```bash
cd frontend
npm test
npm run lint
npm run build
```

## Demo walkthrough

The amounts below assume a fresh database. To reset, stop the API, delete `backend/cerbo.db`, and start it again (it re-seeds on startup).

Open http://127.0.0.1:5173. The header **Role** menu lists the seed users:

| Name | Role |
|---|---|
| Dr. Maya Patel | provider |
| Jane Doe | patient |
| Sam Lee | patient |
| Cerbo Admin | admin |

Dr. Patel's catalog is already enabled at the suggested prices. This walkthrough uses Dr. Maya Patel and Jane Doe.

1. Select **Dr. Maya Patel (provider)**. Open **New order**.
2. Choose patient **Jane Doe**. Add **Magnesium Glycinate** and set Qty to `2` (unit price stays `$24.00`). Add **Vitamin D3 + K2** and leave Qty at `1` (unit price `$18.00`).
3. The live preview should show subtotal **$66.00**, COGS **$33.00**, platform fee **$0.50**, and you receive **$32.50**. Click **Continue**, then **Confirm**.
4. The created screen shows a patient link such as `/orders/1`.
5. Switch **Role** to **Jane Doe (patient)**. The app opens **My orders**. Open the new order.
6. Set **Payment method** to **Decline test card** and click **Pay**. The page shows "Payment was declined." and the status stays **Pending payment**.
7. Set **Payment method** to **OK test card** and click **Pay**. The page becomes a receipt with status **Paid** and total **$66.00**.
8. Switch **Role** back to **Dr. Maya Patel (provider)** and open **Dashboard**. GMV is **$66.00**, platform fees **$0.50**, and earnings **$32.50**. Paid orders lists Jane Doe with those same amounts. Units sold are Magnesium Glycinate **2** and Vitamin D3 + K2 **1**. Pending orders is empty.
9. Click **Audit** on that paid order. Lines, the split, and the ledger (patient payment $66.00, Cerbo COGS $33.00, Cerbo fee $0.50, provider payable $32.50) match. All three integrity checks are marked ✓: fee matches formula, split adds up, and ledger matches split.

## What's stubbed

From [PRD §8](docs/prd.md). Role and ownership checks still run on every request.

| Seam | Stub | Real version later |
|---|---|---|
| Auth | Role switcher sends a user ID header; real role/ownership checks | OAuth/SSO; patient magic links |
| Payments | `FakePaymentProvider`: approves by default; `fake_card_decline` declines; replays the same attempt (key + amount + method) without charging twice; after a decline, a different card is a new attempt | Stripe with a per-attempt idempotency key + webhooks |
| Notifications | Console log; patient link shown in provider UI | Email/SMS; portal messaging |
| Fulfillment | Console log after payment commits | Warehouse/shipping integration |

## Known limitations

From [architecture §11](docs/architecture.md):

- SQLite serializes writes, so the concurrency tests are less demanding than production Postgres. The guarantees come from conditional updates and constraints, which behave the same on Postgres.
- Append-only is enforced in application code only.
- An external payment call runs inside a database transaction (architecture §7).
- Fake auth: `X-User-Id` is trivially spoofable. The ownership rules are real; identity is not.
- No migrations; the schema is created at startup.

## Docs

- [Product requirements](docs/prd.md)
- [Architecture](docs/architecture.md)
- [Tasks](docs/tasks.md)
- [Decisions](docs/decisions.md)
- [AI log](docs/ai-log.md)
- [Cursor agent workflow setup](docs/cursor-agent-workflow-setup.md)
- [Assignment brief](docs/Cebro_wk1_overview.pdf)
- [Diagrams](docs/diagrams/overview.md)
  - [System overview](docs/diagrams/overview.md)
  - [Data flow](docs/diagrams/data-flow.md)
  - [Data model](docs/diagrams/data-model.md)
  - [Auth](docs/diagrams/flows/auth.md)
  - [Provider products](docs/diagrams/flows/provider-products.md)
  - [Order preview](docs/diagrams/flows/order-preview.md)
  - [Orders](docs/diagrams/flows/orders.md)
  - [Pay](docs/diagrams/flows/pay.md)
  - [Reporting](docs/diagrams/flows/reporting.md)
  - [Admin products](docs/diagrams/flows/admin-products.md)
  - [Frontend shell](docs/diagrams/flows/frontend-shell.md)

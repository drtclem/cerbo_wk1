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

The app listens on http://localhost:5173.

Run tests, lint, and the production build:

```bash
cd frontend
npm test
npm run lint
npm run build
```

## Run with Docker

Build and run the single production image (API under `/api`, SPA at `/`, demo reset enabled):

```bash
docker build -t cerbo .
docker run -p 8080:8080 -e DEMO_MODE=true cerbo
```

Open http://localhost:8080. Click **Log in** to reset the shared demo database and sign in as Dr. Maya Patel. Use **Log out** when you are done (that resets the database again).

Local two-process development is unchanged: `uvicorn app.main:app` on port 8000 and `npm run dev` on port 5173. Without `DEMO_MODE=true`, `POST /demo/reset` is not registered; the UI still logs in and out, and ignores a 404 from that endpoint.

## Live demo

URL TBD.

Auth is fake (a role switcher, not real login). All seed data and orders are made up. Logging out calls the demo reset endpoint and clears the shared demo database for everyone using that deployment.

## Demo walkthrough

Prefer a fresh database. With Docker (`DEMO_MODE=true`), **Log in** and **Log out** each reset the data. With the local API, delete `backend/cerbo.db` and restart, or start with `DEMO_MODE=true`.

Open http://localhost:8080 (Docker) or http://localhost:5173 (dev). Click **Log in**. You start as **Dr. Maya Patel**. The header **Viewing as** menu lists the seed users (switching roles does not reset data):

| Name | Role |
|---|---|
| Dr. Maya Patel | provider |
| Jane Doe | patient |
| Sam Lee | patient |
| Cerbo Admin | admin |

Dr. Patel's catalog is already enabled at the suggested prices. This walkthrough uses Dr. Maya Patel and Jane Doe.

1. Open **New order**.
2. Choose patient **Jane Doe**. Add **Magnesium Glycinate** and set Qty to `2` (unit price stays `$24.00`). Add **Vitamin D3 + K2** and leave Qty at `1` (unit price `$18.00`).
3. In the order summary, turn **on** **Donate 5% of my margin to medical research** (remembered in this browser as the provider default). Margins are **$24.00** and **$9.00** → donations **$1.20** (American Migraine Foundation) and **$0.45** (ASBMR) → total donation **$1.65**. The live preview should show subtotal **$66.00**, COGS **$33.00**, platform fee **$0.50**, research donation **$1.65**, and you receive **$30.85**. Each line shows its fund name (click for description and Learn more). Note: *Example organizations for this demo. Not affiliated; no donations are made.* Click **Continue**, then **Confirm**.
4. The created screen shows a patient link such as `/orders/1`.
5. Switch **Viewing as** to **Jane Doe (patient)**. The app opens **My orders**. Open the new order. The page says Dr. Maya Patel is donating part of their earnings to medical research and lists the fund names with links — **no donation amounts**.
6. Set **Payment method** to **Decline test card** and click **Pay**. The page shows "Payment was declined." and the status stays **Pending payment**.
7. Set **Payment method** to **OK test card** and click **Pay**. The page becomes a receipt with status **Paid** and total **$66.00** (still no donation amounts for the patient).
8. Switch **Viewing as** back to **Dr. Maya Patel (provider)** and open **Dashboard**. GMV is **$66.00**, platform fees **$0.50**, donated to research **$1.65**, and earnings **$30.85**. Paid orders lists Jane Doe with those same amounts. Units sold are Magnesium Glycinate **2** and Vitamin D3 + K2 **1**. Pending orders is empty.
9. Click **Audit** on that paid order. Lines, the split, and the ledger match: patient payment **$66.00**, Cerbo COGS **$33.00**, Cerbo fee **$0.50**, research donation **$1.20** (American Migraine Foundation), research donation **$0.45** (ASBMR), provider payable **$30.85**. All four integrity checks are marked ✓: fee matches formula, donation matches the rate, split adds up, and ledger matches split.
10. Click **Log out**. The login screen returns and the database is reset for the next visitor.

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

- [Writeup: decisions, cuts, and AI usage](docs/WRITEUP.md)
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

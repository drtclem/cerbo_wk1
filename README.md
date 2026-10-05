# In-house supplement ordering

A vertical slice where a provider builds a supplement order and the patient pays Cerbo directly. Requirements and architecture are in [`docs/`](docs/).

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js `^20.19.0` or `>=22.12.0`

The backend pins Python 3.12 in `backend/.python-version`.

## Backend

Install dependencies and start the API:

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

Install dependencies and start the app:

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

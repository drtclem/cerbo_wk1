# syntax=docker/dockerfile:1

FROM node:20-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/app ./app
RUN uv sync --frozen --no-dev

COPY --from=frontend /frontend/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH"
ENV DEMO_MODE=true
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.serve:app --host 0.0.0.0 --port ${PORT:-8080}"]

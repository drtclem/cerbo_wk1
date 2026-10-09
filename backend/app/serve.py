"""Production ASGI app: API under /api, built SPA at /."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

from app.main import create_app


def _default_dist_dir() -> Path:
    app_dir = Path(__file__).resolve().parent
    for base in (app_dir.parent, app_dir.parent.parent):
        candidate = base / "frontend" / "dist"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "frontend/dist not found. Build the frontend (`cd frontend && npm run build`) "
        "or pass dist_dir= to create_serve_app."
    )


def create_serve_app(
    *,
    database_url: str | None = None,
    dist_dir: Path | None = None,
    demo_mode: bool | None = None,
) -> FastAPI:
    api = create_app(database_url=database_url, demo_mode=demo_mode)
    static_root = dist_dir if dist_dir is not None else _default_dist_dir()
    index_html = static_root / "index.html"
    if not index_html.is_file():
        raise RuntimeError(f"Missing SPA entrypoint: {index_html}")

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        # Mounted sub-apps do not run their own lifespan; drive the API's here.
        async with api.router.lifespan_context(api):
            yield

    application = FastAPI(title="Cerbo supplement ordering", lifespan=lifespan)
    application.mount("/api", api)

    assets = static_root / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> Response:
        if full_path:
            candidate = static_root / full_path
            try:
                candidate.resolve().relative_to(static_root.resolve())
            except ValueError as exc:
                raise HTTPException(status_code=404) from exc
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index_html)

    return application


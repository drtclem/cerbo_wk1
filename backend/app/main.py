from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.users import router as users_router
from app.config import database_url as default_database_url
from app.db import init_db, make_engine, make_session_factory
from app.seams.auth import APIError
from app.seed import seed


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    engine = make_engine(application.state.database_url)
    try:
        init_db(engine)
        factory = make_session_factory(engine)
        application.state.session_factory = factory
        session = factory()
        try:
            seed(session)
            session.commit()
        finally:
            session.close()
        yield
    finally:
        engine.dispose()


def create_app(database_url: str | None = None) -> FastAPI:
    application = FastAPI(title="Cerbo supplement ordering", lifespan=_lifespan)
    application.state.database_url = (
        default_database_url if database_url is None else database_url
    )

    @application.exception_handler(APIError)
    async def _handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "line_index": exc.line_index,
                }
            },
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(users_router)
    return application


app = create_app()

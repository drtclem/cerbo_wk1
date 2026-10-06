from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.catalog import router as catalog_router
from app.api.orders import router as orders_router
from app.api.reporting import router as reporting_router
from app.api.users import router as users_router
from app.config import build_fulfillment, build_notifier, build_payment_provider
from app.config import database_url as default_database_url
from app.db import init_db, make_engine, make_session_factory
from app.domain.money import PricingError
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
    application.state.notifier = build_notifier()
    application.state.payment_provider = build_payment_provider()
    application.state.fulfillment = build_fulfillment()

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

    @application.exception_handler(PricingError)
    async def _handle_pricing_error(_request: Request, exc: PricingError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.detail,
                    "line_index": exc.line_index,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request",
                    "line_index": None,
                }
            },
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(users_router)
    application.include_router(catalog_router)
    application.include_router(admin_router)
    application.include_router(orders_router)
    application.include_router(reporting_router)
    return application


app = create_app()

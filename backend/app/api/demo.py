from fastapi import APIRouter, Request, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import init_db
from app.models import Base
from app.seams.payment_provider import FakePaymentProvider
from app.seed import seed

router = APIRouter(tags=["demo"])


@router.post("/demo/reset", status_code=204, response_class=Response)
def demo_reset(request: Request) -> Response:
    """Drop every table, recreate the schema, re-seed, and clear the fake processor. No auth."""
    engine: Engine = request.app.state.engine
    factory: sessionmaker[Session] = request.app.state.session_factory
    Base.metadata.drop_all(engine)
    init_db(engine)
    session = factory()
    try:
        seed(session)
        session.commit()
    finally:
        session.close()
    # The fake processor keys attempts by order ID, which restart at 1 after a
    # rebuild; clear it too or the next visitor's order 1 replays an old approval.
    provider = request.app.state.payment_provider
    if isinstance(provider, FakePaymentProvider):
        provider.reset()
    return Response(status_code=204)

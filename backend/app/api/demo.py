from fastapi import APIRouter, Request, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import init_db
from app.models import Base
from app.seed import seed

router = APIRouter(tags=["demo"])


@router.post("/demo/reset", status_code=204, response_class=Response)
def demo_reset(request: Request) -> Response:
    """Drop every table, recreate the schema, and re-seed. No auth."""
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
    return Response(status_code=204)

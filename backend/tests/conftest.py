from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, make_session_factory


@pytest.fixture(scope="function")
def db_session(tmp_path: Path) -> Iterator[Session]:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(url)
    init_db(engine)
    factory = make_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()

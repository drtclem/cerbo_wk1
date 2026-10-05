from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Order, User

_UNAUTHENTICATED = "Missing or unknown user"
_SQLITE_MAX_INT = 9_223_372_036_854_775_807


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        line_index: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.line_index = line_index
        super().__init__(message)


def current_user(
    session: Annotated[Session, Depends(get_session)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> User:
    if x_user_id is None:
        raise APIError(401, "UNAUTHENTICATED", _UNAUTHENTICATED)
    header = x_user_id.strip()
    # SQLite stores INTEGER as a signed 64-bit value. A larger id overflows the driver.
    if not header.isascii() or not header.isdigit() or int(header) > _SQLITE_MAX_INT:
        raise APIError(401, "UNAUTHENTICATED", _UNAUTHENTICATED)
    user = session.get(User, int(header))
    if user is None:
        raise APIError(401, "UNAUTHENTICATED", _UNAUTHENTICATED)
    return user


def require_role(*roles: str) -> Callable[..., User]:
    def _require_role(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise APIError(403, "FORBIDDEN", "Wrong role")
        return user

    return _require_role


def require_order_access(order: Order, user: User) -> None:
    if user.id not in (order.provider_id, order.patient_id):
        raise APIError(404, "NOT_FOUND", "Not found")

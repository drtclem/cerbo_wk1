from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.seams.auth import current_user

router = APIRouter()


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: str


@router.get("/users", response_model=list[UserResponse])
def list_users(session: Annotated[Session, Depends(get_session)]) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user

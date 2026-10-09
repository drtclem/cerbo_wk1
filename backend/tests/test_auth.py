from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Order, User
from app.seams.auth import APIError, require_order_access, require_role

_CREATED_AT = "2026-10-05T16:00:00Z"
_SEED_USERS = (
    ("Dr. Maya Patel", "provider"),
    ("Jane Doe", "patient"),
    ("Sam Lee", "patient"),
    ("Cerbo Admin", "admin"),
)
_UNAUTHENTICATED = {
    "error": {
        "code": "UNAUTHENTICATED",
        "message": "Missing or unknown user",
        "line_index": None,
    }
}
_FORBIDDEN = {
    "error": {
        "code": "FORBIDDEN",
        "message": "Wrong role",
        "line_index": None,
    }
}


def _assert_int(value: object) -> None:
    assert isinstance(value, int) and not isinstance(value, bool)


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'auth.db'}")


def _user_id(client: TestClient, name: str) -> int:
    response = client.get("/users")
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    matches = [user for user in users if user["name"] == name]
    assert len(matches) == 1
    user_id = matches[0]["id"]
    _assert_int(user_id)
    return user_id


@contextmanager
def _provider_probe(tmp_path: Path) -> Iterator[TestClient]:
    application = _application(tmp_path)

    @application.get("/provider-only-probe")
    def provider_only(user: User = Depends(require_role("provider"))) -> dict[str, int]:
        return {"id": user.id}

    with TestClient(application) as client:
        yield client


@contextmanager
def _seeded_order(tmp_path: Path) -> Iterator[tuple[Order, dict[str, User]]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        patient_id = _user_id(client, "Jane Doe")
        session: Session = application.state.session_factory()
        try:
            session.add(
                Order(
                    provider_id=provider_id,
                    patient_id=patient_id,
                    status="pending_payment",
                    fee_bps=75,
                    donation_bps=0,
                    subtotal_cents=100,
                    cogs_total_cents=40,
                    platform_fee_cents=10,
                    donation_cents=0,
                    provider_payout_cents=50,
                    created_at=_CREATED_AT,
                )
            )
            session.commit()
            order = session.scalars(select(Order)).one()
            _assert_int(order.id)
            assert order.provider_id == provider_id
            assert order.patient_id == patient_id
            assert order.status == "pending_payment"
            assert order.fee_bps == 75
            assert order.subtotal_cents == 100
            assert order.cogs_total_cents == 40
            assert order.platform_fee_cents == 10
            assert order.provider_payout_cents == 50
            assert order.created_at == _CREATED_AT
            for amount in (
                order.fee_bps,
                order.subtotal_cents,
                order.cogs_total_cents,
                order.platform_fee_cents,
                order.provider_payout_cents,
            ):
                _assert_int(amount)

            users = {
                name: session.scalars(select(User).where(User.name == name)).one()
                for name, _role in _SEED_USERS
            }
            assert users["Dr. Maya Patel"].id == provider_id
            assert users["Dr. Maya Patel"].role == "provider"
            assert users["Jane Doe"].id == patient_id
            assert users["Jane Doe"].role == "patient"
            assert users["Sam Lee"].role == "patient"
            assert users["Sam Lee"].id != patient_id
            assert users["Cerbo Admin"].role == "admin"
            yield order, users
        finally:
            session.close()


def _assert_not_found(error: APIError) -> None:
    assert isinstance(error, Exception)
    assert error.status_code == 404
    assert error.code == "NOT_FOUND"
    assert error.message == "Not found"
    assert error.line_index is None


def test_get_users_lists_seed_users_with_roles_ordered_by_id(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        response = client.get("/users")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert [(user["name"], user["role"]) for user in body] == list(_SEED_USERS)
    ids = [user["id"] for user in body]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(_SEED_USERS)
    for user in body:
        assert set(user) == {"id", "name", "role"}
        _assert_int(user["id"])
        assert isinstance(user["name"], str)
        assert isinstance(user["role"], str)


def test_get_users_returns_seed_users_when_a_user_header_is_sent(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        open_list = client.get("/users")
        with_header = client.get("/users", headers={"X-User-Id": "999999"})

    assert open_list.status_code == 200
    assert with_header.status_code == 200
    assert with_header.json() == open_list.json()


def test_get_me_returns_the_caller(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        listed = client.get("/users")
        assert listed.status_code == 200
        users = listed.json()
        assert [(user["name"], user["role"]) for user in users] == list(_SEED_USERS)
        for user in users:
            _assert_int(user["id"])
            response = client.get("/me", headers={"X-User-Id": str(user["id"])})
            assert response.status_code == 200
            assert response.json() == {
                "id": user["id"],
                "name": user["name"],
                "role": user["role"],
            }


def test_get_me_rejects_a_missing_user_id(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == _UNAUTHENTICATED


@pytest.mark.parametrize("user_id", ["", "   ", "\t"], ids=["blank", "spaces", "tab"])
def test_get_me_rejects_a_blank_or_whitespace_user_id(tmp_path: Path, user_id: str) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        response = client.get("/me", headers={"X-User-Id": user_id})

    assert response.status_code == 401
    assert response.json() == _UNAUTHENTICATED


def test_get_me_rejects_an_unknown_user_id(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        response = client.get("/me", headers={"X-User-Id": "999999"})

    assert response.status_code == 401
    assert response.json() == _UNAUTHENTICATED


def test_get_me_rejects_a_non_integer_user_id(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        response = client.get("/me", headers={"X-User-Id": "abc"})

    assert response.status_code == 401
    assert response.json() == _UNAUTHENTICATED


def test_get_me_rejects_a_user_id_sqlite_cannot_store(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        response = client.get("/me", headers={"X-User-Id": "9223372036854775808"})

    assert response.status_code == 401
    assert response.json() == _UNAUTHENTICATED


def test_require_role_provider_blocks_a_patient(tmp_path: Path) -> None:
    with _provider_probe(tmp_path) as client:
        patient_id = _user_id(client, "Jane Doe")
        response = client.get("/provider-only-probe", headers={"X-User-Id": str(patient_id)})

    assert response.status_code == 403
    assert response.json() == _FORBIDDEN


def test_require_role_provider_allows_a_provider(tmp_path: Path) -> None:
    with _provider_probe(tmp_path) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        response = client.get("/provider-only-probe", headers={"X-User-Id": str(provider_id)})

    assert response.status_code == 200
    assert response.json() == {"id": provider_id}


def test_require_role_provider_rejects_a_missing_user_id(tmp_path: Path) -> None:
    with _provider_probe(tmp_path) as client:
        response = client.get("/provider-only-probe")

    assert response.status_code == 401
    assert response.json() == _UNAUTHENTICATED


def test_require_order_access_allows_the_owning_provider(tmp_path: Path) -> None:
    with _seeded_order(tmp_path) as (order, users):
        assert require_order_access(order, users["Dr. Maya Patel"]) is None


def test_require_order_access_allows_the_owning_patient(tmp_path: Path) -> None:
    with _seeded_order(tmp_path) as (order, users):
        assert require_order_access(order, users["Jane Doe"]) is None


def test_require_order_access_hides_the_order_from_another_patient(tmp_path: Path) -> None:
    with _seeded_order(tmp_path) as (order, users):
        with pytest.raises(APIError) as raised:
            require_order_access(order, users["Sam Lee"])
    _assert_not_found(raised.value)


def test_require_order_access_hides_the_order_from_an_admin(tmp_path: Path) -> None:
    with _seeded_order(tmp_path) as (order, users):
        with pytest.raises(APIError) as raised:
            require_order_access(order, users["Cerbo Admin"])
    _assert_not_found(raised.value)

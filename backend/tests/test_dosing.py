"""T22 / D11: default dosing, snapshotted dosing/notes on order lines."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import OrderLine, Product

_VALIDATION_ERROR = {
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid request",
        "line_index": None,
    }
}
_DEFAULT = "Example: 1 capsule daily with a meal"


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'dosing.db'}")


def _user_id(client: TestClient, name: str) -> int:
    response = client.get("/users")
    assert response.status_code == 200
    matches = [user for user in response.json() if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


@contextmanager
def _seeded(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient, int, int, int, str]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        patient_id = _user_id(client, "Jane Doe")
        catalog = client.get("/products", headers=_headers(provider_id))
        assert catalog.status_code == 200
        mag = next(row for row in catalog.json() if row["sku"] == "MAG-GLY")
        yield (
            application,
            client,
            provider_id,
            patient_id,
            _require_int(mag["id"]),
            mag["default_dosing"],
        )


def test_catalog_and_provider_products_include_seeded_default_dosing(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, _patient, _pid, default):
        assert default == _DEFAULT
        catalog = client.get("/products", headers=_headers(provider_id))
        assert catalog.status_code == 200
        for row in catalog.json():
            assert row["default_dosing"] == _DEFAULT

        provider = client.get("/provider/products", headers=_headers(provider_id))
        assert provider.status_code == 200
        for row in provider.json():
            assert row["default_dosing"] == _DEFAULT


def test_create_rejects_blank_and_overlong_dosing_and_overlong_note(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, patient_id, product_id, default):
        base = {
            "product_id": product_id,
            "qty": 1,
            "unit_price_cents": 2_400,
            "dosing": default,
            "note": None,
        }
        for bad in (
            {**base, "dosing": ""},
            {**base, "dosing": "   "},
            {**base, "dosing": "x" * 201},
            {**base, "note": "y" * 501},
        ):
            response = client.post(
                "/orders",
                headers=_headers(provider_id),
                json={"patient_id": patient_id, "lines": [bad]},
            )
            assert response.status_code == 422, bad
            assert response.json() == _VALIDATION_ERROR


def test_create_snapshots_trimmed_dosing_and_note_including_script_text(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, provider_id, patient_id, product_id, _d):
        dosing = "  Take 2 capsules at bedtime  "
        note = '  Why: <script>alert("x")</script> deficiency  '
        response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": patient_id,
                "lines": [
                    {
                        "product_id": product_id,
                        "qty": 1,
                        "unit_price_cents": 2_400,
                        "dosing": dosing,
                        "note": note,
                    }
                ],
            },
        )
        assert response.status_code == 200
        body = _require_dict(response.json())
        line = _require_dict(body["lines"][0])
        assert line["dosing"] == "Take 2 capsules at bedtime"
        assert line["note"] == 'Why: <script>alert("x")</script> deficiency'
        assert "<script>" in line["note"]

        session: Session = application.state.session_factory()
        try:
            stored = session.get(OrderLine, 1)
            assert stored is not None
            assert stored.dosing == "Take 2 capsules at bedtime"
            assert stored.note == 'Why: <script>alert("x")</script> deficiency'
        finally:
            session.close()


def test_later_catalog_dosing_edit_does_not_change_existing_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, provider_id, patient_id, product_id, default):
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": patient_id,
                "lines": [
                    {
                        "product_id": product_id,
                        "qty": 1,
                        "unit_price_cents": 2_400,
                        "dosing": default,
                        "note": "Baseline note",
                    }
                ],
            },
        )
        assert created.status_code == 200
        order_id = _require_int(_require_dict(created.json())["id"])
        snapshotted = _require_dict(created.json()["lines"][0])["dosing"]

        admin_id = _user_id(client, "Cerbo Admin")
        updated = client.put(
            f"/admin/products/{product_id}",
            headers=_headers(admin_id),
            json={"default_dosing": "Example: 2 capsules with breakfast"},
        )
        assert updated.status_code == 200
        assert _require_dict(updated.json())["default_dosing"] == (
            "Example: 2 capsules with breakfast"
        )

        session: Session = application.state.session_factory()
        try:
            product = session.get(Product, product_id)
            assert product is not None
            assert product.default_dosing == "Example: 2 capsules with breakfast"
        finally:
            session.close()

        fetched = client.get(f"/orders/{order_id}", headers=_headers(provider_id))
        assert fetched.status_code == 200
        line = _require_dict(_require_dict(fetched.json())["lines"][0])
        assert line["dosing"] == snapshotted == default
        assert line["note"] == "Baseline note"


def test_omitted_note_is_null_on_order_line(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, patient_id, product_id, default):
        response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": patient_id,
                "lines": [
                    {
                        "product_id": product_id,
                        "qty": 1,
                        "unit_price_cents": 2_400,
                        "dosing": default,
                    }
                ],
            },
        )
        assert response.status_code == 200
        line = _require_dict(_require_dict(response.json())["lines"][0])
        assert line["dosing"] == default
        assert line["note"] is None

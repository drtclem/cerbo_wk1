"""T21 / D14: request caps, duplicate products, preview stock_available, audit payment fields."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Product

_VALIDATION_ERROR = {
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid request",
        "line_index": None,
    }
}
_AUDIT_KEYS = {
    "id",
    "status",
    "payment_ref",
    "paid_at",
    "lines",
    "removed_lines",
    "subtotal_cents",
    "cogs_total_cents",
    "fee_bps",
    "platform_fee_cents",
    "donation_bps",
    "donation_cents",
    "provider_payout_cents",
    "ledger",
    "recomputed_fee_matches",
    "donation_matches_rate",
    "split_adds_up",
    "ledger_matches_split",
}


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'input_limits.db'}")


def _user_id(client: TestClient, name: str) -> int:
    response = client.get("/users")
    assert response.status_code == 200
    matches = [user for user in response.json() if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _product_id(client: TestClient, provider_id: int, sku: str) -> int:
    response = client.get("/products", headers=_headers(provider_id))
    assert response.status_code == 200
    matches = [row for row in response.json() if row["sku"] == sku]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


_DEFAULT_DOSING = "Example: 1 capsule daily with a meal"


def _line(product_id: int, qty: int, unit_price_cents: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
    }


def _create_line(product_id: int, qty: int, unit_price_cents: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "dosing": _DEFAULT_DOSING,
    }


@contextmanager
def _seeded(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient, int, int, int]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        patient_id = _user_id(client, "Jane Doe")
        product_id = _product_id(client, provider_id, "MAG-GLY")
        yield application, client, provider_id, patient_id, product_id


def test_preview_rejects_qty_zero_one_thousand_one_and_huge(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, _patient_id, product_id):
        for qty in (0, 1_001, 10**17):
            response = client.post(
                "/orders/preview",
                headers=_headers(provider_id),
                json={"lines": [_line(product_id, qty, 2_400)]},
            )
            assert response.status_code == 422, qty
            assert response.json() == _VALIDATION_ERROR


def test_preview_rejects_price_above_one_million(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, _patient_id, product_id):
        response = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": [_line(product_id, 1, 1_000_001)]},
        )
        assert response.status_code == 422
        assert response.json() == _VALIDATION_ERROR


def test_create_rejects_qty_and_price_caps(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, patient_id, product_id):
        for qty, price in ((0, 2_400), (1_001, 2_400), (10**17, 2_400), (1, 1_000_001)):
            response = client.post(
                "/orders",
                headers=_headers(provider_id),
                json={
                    "patient_id": patient_id,
                    "lines": [_create_line(product_id, qty, price)],
                },
            )
            assert response.status_code == 422, (qty, price)
            assert response.json() == _VALIDATION_ERROR


def test_preview_and_create_reject_duplicate_product(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, patient_id, product_id):
        other_id = _product_id(client, provider_id, "D3-K2")
        preview_lines = [
            _line(product_id, 1, 2_400),
            _line(other_id, 1, 1_800),
            _line(product_id, 2, 2_400),
        ]
        preview = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": preview_lines},
        )
        assert preview.status_code == 422
        error = _require_dict(_require_dict(preview.json())["error"])
        assert error["code"] == "DUPLICATE_PRODUCT"
        assert _require_int(error["line_index"]) == 2

        create_lines = [
            _create_line(product_id, 1, 2_400),
            _create_line(other_id, 1, 1_800),
            _create_line(product_id, 2, 2_400),
        ]
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": patient_id, "lines": create_lines},
        )
        assert created.status_code == 422
        create_error = _require_dict(_require_dict(created.json())["error"])
        assert create_error["code"] == "DUPLICATE_PRODUCT"
        assert _require_int(create_error["line_index"]) == 2


def test_preview_includes_stock_available_and_allows_qty_above_stock(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, provider_id, patient_id, product_id):
        session: Session = application.state.session_factory()
        try:
            product = session.get(Product, product_id)
            assert product is not None
            stock = _require_int(product.stock_qty)
        finally:
            session.close()
        assert stock == 50
        qty = stock + 5

        preview = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": [_line(product_id, qty, 2_400)]},
        )
        assert preview.status_code == 200
        body = _require_dict(preview.json())
        lines = [_require_dict(line) for line in _require_list(body["lines"])]
        assert len(lines) == 1
        assert "stock_available" in lines[0]
        assert _require_int(lines[0]["stock_available"]) == stock
        assert _require_int(lines[0]["qty"]) == qty

        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": patient_id,
                "lines": [_create_line(product_id, qty, 2_400)],
            },
        )
        assert created.status_code == 200
        order_id = _require_int(_require_dict(created.json())["id"])

        patient_id_header = _user_id(client, "Jane Doe")
        pay = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(patient_id_header),
            json={"payment_method": "fake_card_ok"},
        )
        assert pay.status_code == 409
        assert _require_dict(_require_dict(pay.json())["error"])["code"] == "OUT_OF_STOCK"


def test_audit_includes_payment_ref_and_paid_at_for_paid_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, patient_id, product_id):
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": patient_id,
                "lines": [_create_line(product_id, 1, 2_400)],
            },
        )
        assert created.status_code == 200
        order = _require_dict(created.json())
        order_id = _require_int(order["id"])

        paid = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(patient_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200
        paid_body = _require_dict(paid.json())
        payment_ref = paid_body["payment_ref"]
        paid_at = paid_body["paid_at"]
        assert isinstance(payment_ref, str) and payment_ref
        assert isinstance(paid_at, str) and paid_at

        audit = client.get(f"/orders/{order_id}/audit", headers=_headers(provider_id))
        assert audit.status_code == 200
        body = _require_dict(audit.json())
        assert set(body) == _AUDIT_KEYS
        assert body["payment_ref"] == payment_ref
        assert body["paid_at"] == paid_at


def test_decline_message_mentions_try_a_different_card(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (_app, client, provider_id, patient_id, product_id):
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": patient_id,
                "lines": [_create_line(product_id, 1, 2_400)],
            },
        )
        assert created.status_code == 200
        order_id = _require_int(_require_dict(created.json())["id"])
        declined = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(patient_id),
            json={"payment_method": "fake_card_decline"},
        )
        assert declined.status_code == 402
        error = _require_dict(_require_dict(declined.json())["error"])
        assert error["code"] == "PAYMENT_DECLINED"
        assert error["message"] == "Payment was declined. Try a different card."

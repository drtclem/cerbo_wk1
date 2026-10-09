import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import LedgerEntry, Order, OrderLine, Product
from app.seams.payment_provider import FakePaymentProvider
from app.services.orders import OrderNotCancellable, cancel_order
from app.services.payments import OrderNotPayable, OutOfStock, PaymentDeclined, pay_order

_PRODUCTS: tuple[tuple[str, str, int, int, int, str], ...] = (
    ("MAG-GLY", "Magnesium Glycinate", 1_200, 2_400, 50, "Example: 1 capsule daily with a meal"),
    ("D3-K2", "Vitamin D3 + K2", 900, 1_800, 40, "Example: 1 capsule daily with a meal"),
    ("OMEGA3", "Omega-3 Fish Oil", 1_850, 3_600, 25, "Example: 1 capsule daily with a meal"),
    ("PROBIO50", "Probiotic 50B", 2_100, 4_200, 1, "Example: 1 capsule daily with a meal"),
)
_CATALOG_KEYS = {
    "id",
    "sku",
    "name",
    "unit_cogs_cents",
    "suggested_price_cents",
    "stock_qty",
    "default_dosing",
}
_SPLIT_FIELDS = (
    "subtotal_cents",
    "cogs_total_cents",
    "fee_bps",
    "platform_fee_cents",
    "donation_bps",
    "donation_cents",
    "provider_payout_cents",
)
_ORDER_KEYS = {
    "id",
    "provider_id",
    "patient_id",
    "status",
    "patient_link",
    "created_at",
    "paid_at",
    "cancelled_at",
    "payment_ref",
    "lines",
    "subtotal_cents",
    "cogs_total_cents",
    "fee_bps",
    "platform_fee_cents",
    "donation_bps",
    "donation_cents",
    "provider_payout_cents",
}
_LINE_KEYS = {
    "product_id",
    "product_name",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
    "dosing",
    "note",
    "donation_cents",
    "fund_id",
    "fund_name",
    "fund_url",
    "fund_description",
}
_STORED_LINE_KEYS = (
    "product_id",
    "product_name",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "dosing",
    "note",
    "donation_cents",
    "fund_id",
    "fund_name",
    "fund_url",
)
_LINE_MONEY = (
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
)
_SEED_USERS = (
    ("Dr. Maya Patel", "provider"),
    ("Jane Doe", "patient"),
    ("Sam Lee", "patient"),
    ("Cerbo Admin", "admin"),
)
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_UNKNOWN_ID = 999_999
_PAST_SQLITE_INT = 9_223_372_036_854_775_808
_JOIN_TIMEOUT_SECONDS = 15
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
_NOT_FOUND = {
    "error": {
        "code": "NOT_FOUND",
        "message": "Not found",
        "line_index": None,
    }
}
_VALIDATION_ERROR = {
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid request",
        "line_index": None,
    }
}
_PAYMENT_DECLINED = {
    "error": {
        "code": "PAYMENT_DECLINED",
        "message": "Payment was declined. Try a different card.",
        "line_index": None,
    }
}
_OUT_OF_STOCK = {
    "error": {
        "code": "OUT_OF_STOCK",
        "message": "Not enough stock.",
        "line_index": None,
    }
}
_NOT_PAYABLE = {
    "error": {
        "code": "ORDER_NOT_PAYABLE",
        "message": "Order cannot be paid.",
        "line_index": None,
    }
}


class _Call:
    def __init__(self) -> None:
        self.view: object | None = None
        self.error: BaseException | None = None


class _RaisingFulfillment:
    """Used only by the ship-failure test. Records the order id, then raises."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def ship(self, order: object) -> None:
        order_id = getattr(order, "id", None)
        assert isinstance(order_id, int) and not isinstance(order_id, bool)
        self.calls.append(order_id)
        raise RuntimeError("ship failed")


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
    return create_app(database_url=f"sqlite:///{tmp_path / 'pay.db'}")


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _users(client: TestClient) -> list[dict[str, object]]:
    response = client.get("/users")
    assert response.status_code == 200
    return [_require_dict(user) for user in _require_list(response.json())]


def _user_id(client: TestClient, name: str) -> int:
    matches = [user for user in _users(client) if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _assert_seed_users(client: TestClient) -> None:
    indexed: dict[str, dict[str, object]] = {}
    for user in _users(client):
        name = user["name"]
        assert isinstance(name, str)
        indexed[name] = user
    ids: list[int] = []
    for name, role in _SEED_USERS:
        assert indexed[name]["role"] == role
        ids.append(_require_int(indexed[name]["id"]))
    assert ids == sorted(set(ids))
    assert _UNKNOWN_ID not in ids


def _read_catalog(client: TestClient, user_id: int) -> list[dict[str, object]]:
    response = client.get("/products", headers=_headers(user_id))
    assert response.status_code == 200
    return [_require_dict(row) for row in _require_list(response.json())]


def _load_catalog(client: TestClient, user_id: int) -> list[dict[str, object]]:
    rows = _read_catalog(client, user_id)
    assert len(rows) == len(_PRODUCTS)
    ids: list[int] = []
    for row, expected in zip(rows, _PRODUCTS, strict=True):
        sku, name, cogs_cents, suggested_cents, stock_qty, _dosing = expected
        assert set(row) == _CATALOG_KEYS
        product_id = _require_int(row["id"])
        assert row["sku"] == sku
        assert row["name"] == name
        assert _require_int(row["unit_cogs_cents"]) == cogs_cents
        assert _require_int(row["suggested_price_cents"]) == suggested_cents
        assert _require_int(row["stock_qty"]) == stock_qty
        ids.append(product_id)
    assert [row["sku"] for row in rows] == [product[0] for product in _PRODUCTS]
    assert ids == sorted(set(ids))
    return rows


def _catalog_row(catalog: list[dict[str, object]], sku: str) -> dict[str, object]:
    matches = [row for row in catalog if row["sku"] == sku]
    assert len(matches) == 1
    return matches[0]


def _product_id(catalog: list[dict[str, object]], sku: str) -> int:
    return _require_int(_catalog_row(catalog, sku)["id"])


def _catalog_int(catalog: list[dict[str, object]], sku: str, field: str) -> int:
    return _require_int(_catalog_row(catalog, sku)[field])


def _request_line(product_id: int, qty: int, unit_price_cents: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "dosing": "Example: 1 capsule daily with a meal",
    }


def _charge_count(application: FastAPI) -> int:
    provider = application.state.payment_provider
    assert isinstance(provider, FakePaymentProvider)
    return _require_int(provider.charge_count)


def _ship_calls(application: FastAPI) -> list[int]:
    raw = application.state.fulfillment.calls
    assert isinstance(raw, list)
    calls: list[int] = []
    for item in raw:
        assert isinstance(item, int) and not isinstance(item, bool)
        calls.append(item)
    return calls


def _stocks_in(session: Session) -> dict[int, int]:
    rows = list(session.scalars(select(Product).order_by(Product.id)))
    return {_require_int(product.id): _require_int(product.stock_qty) for product in rows}


def _orders_in(session: Session) -> list[dict[str, object]]:
    rows = list(session.scalars(select(Order).order_by(Order.id)))
    loaded: list[dict[str, object]] = []
    for order in rows:
        line_rows = list(
            session.scalars(
                select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id)
            )
        )
        lines: list[dict[str, object]] = []
        for line in line_rows:
            lines.append(
                {
                    "product_id": _require_int(line.product_id),
                    "product_name": line.product_name,
                    "qty": _require_int(line.qty),
                    "unit_price_cents": _require_int(line.unit_price_cents),
                    "unit_cogs_cents": _require_int(line.unit_cogs_cents),
                    "dosing": line.dosing,
                    "note": line.note,
                    "donation_cents": _require_int(line.donation_cents),
                    "fund_id": line.fund_id,
                    "fund_name": line.fund_name,
                    "fund_url": line.fund_url,
                }
            )
        loaded.append(
            {
                "id": _require_int(order.id),
                "provider_id": _require_int(order.provider_id),
                "patient_id": _require_int(order.patient_id),
                "status": order.status,
                "fee_bps": _require_int(order.fee_bps),
                "donation_bps": _require_int(order.donation_bps),
                "subtotal_cents": _require_int(order.subtotal_cents),
                "cogs_total_cents": _require_int(order.cogs_total_cents),
                "platform_fee_cents": _require_int(order.platform_fee_cents),
                "donation_cents": _require_int(order.donation_cents),
                "provider_payout_cents": _require_int(order.provider_payout_cents),
                "payment_ref": order.payment_ref,
                "created_at": order.created_at,
                "paid_at": order.paid_at,
                "cancelled_at": order.cancelled_at,
                "lines": lines,
            }
        )
    return loaded


def _ledger_in(session: Session) -> list[dict[str, object]]:
    rows = list(session.scalars(select(LedgerEntry).order_by(LedgerEntry.id)))
    loaded: list[dict[str, object]] = []
    for row in rows:
        entry_type = row.entry_type
        assert isinstance(entry_type, str)
        created_at = row.created_at
        assert isinstance(created_at, str)
        loaded.append(
            {
                "id": _require_int(row.id),
                "order_id": _require_int(row.order_id),
                "entry_type": entry_type,
                "amount_cents": _require_int(row.amount_cents),
                "created_at": created_at,
                "fund_id": row.fund_id,
            }
        )
    return loaded


def _open_state(
    application: FastAPI,
) -> tuple[dict[int, int], list[dict[str, object]], list[dict[str, object]]]:
    session: Session = application.state.session_factory()
    try:
        return _stocks_in(session), _orders_in(session), _ledger_in(session)
    finally:
        session.close()


def _stocks(application: FastAPI) -> dict[int, int]:
    stocks, _orders, _ledger = _open_state(application)
    return stocks


def _load_order(application: FastAPI, order_id: int) -> dict[str, object]:
    _stocks, orders, _ledger = _open_state(application)
    matches = [order for order in orders if order["id"] == order_id]
    assert len(matches) == 1
    return matches[0]


def _ledger_rows(application: FastAPI) -> list[dict[str, object]]:
    _stocks, _orders, ledger = _open_state(application)
    return ledger


def _order_from(orders: list[dict[str, object]], order_id: int) -> dict[str, object]:
    matches = [order for order in orders if order["id"] == order_id]
    assert len(matches) == 1
    return matches[0]


def _assert_stored_lines(stored: dict[str, object], body: dict[str, object]) -> None:
    stored_lines = stored["lines"]
    body_lines = body["lines"]
    assert isinstance(stored_lines, list)
    assert isinstance(body_lines, list)
    assert len(stored_lines) == len(body_lines)
    for stored_value, body_value in zip(stored_lines, body_lines, strict=True):
        stored_line = _require_dict(stored_value)
        response_line = _require_dict(body_value)
        assert set(stored_line) == set(_STORED_LINE_KEYS)
        product_name = stored_line["product_name"]
        assert isinstance(product_name, str)
        assert product_name == response_line["product_name"]
        for field in ("product_id", "qty", "unit_price_cents", "unit_cogs_cents"):
            assert _require_int(stored_line[field]) == _require_int(response_line[field])


def _assert_money_unchanged(stored: dict[str, object], created: dict[str, object]) -> None:
    for field in _SPLIT_FIELDS:
        assert _require_int(stored[field]) == _require_int(created[field])
    _assert_stored_lines(stored, created)
    assert stored["created_at"] == created["created_at"]
    assert stored["provider_id"] == _require_int(created["provider_id"])
    assert stored["patient_id"] == _require_int(created["patient_id"])


def _create_order(
    client: TestClient,
    provider_id: int,
    patient_id: int,
    lines: list[dict[str, int]],
) -> dict[str, object]:
    response = client.post(
        "/orders",
        headers=_headers(provider_id),
        json={"patient_id": patient_id, "lines": lines},
    )
    assert response.status_code == 200
    body = _require_dict(response.json())
    assert set(body) == _ORDER_KEYS
    order_id = _require_int(body["id"])
    assert _require_int(body["provider_id"]) == provider_id
    assert _require_int(body["patient_id"]) == patient_id
    assert body["status"] == "pending_payment"
    assert body["patient_link"] == f"/orders/{order_id}"
    created_at = body["created_at"]
    assert isinstance(created_at, str)
    assert _TIMESTAMP.fullmatch(created_at)
    assert body["paid_at"] is None
    assert body["cancelled_at"] is None
    assert body["payment_ref"] is None
    for field in _SPLIT_FIELDS:
        _require_int(body[field])
    response_lines = [_require_dict(line) for line in _require_list(body["lines"])]
    assert len(response_lines) == len(lines)
    for response_line, requested in zip(response_lines, lines, strict=True):
        assert set(response_line) == _LINE_KEYS
        assert _require_int(response_line["product_id"]) == requested["product_id"]
        assert _require_int(response_line["qty"]) == requested["qty"]
        assert _require_int(response_line["unit_price_cents"]) == requested["unit_price_cents"]
        for field in _LINE_MONEY:
            _require_int(response_line[field])
        product_name = response_line["product_name"]
        assert isinstance(product_name, str)
        assert product_name != ""
    return body


def _pay(
    client: TestClient,
    order_id: int,
    user_id: int,
    payment_method: str = "fake_card_ok",
):
    return client.post(
        f"/orders/{order_id}/pay",
        headers=_headers(user_id),
        json={"payment_method": payment_method},
    )


def _assert_paid_response(body: dict[str, object], created: dict[str, object]) -> str:
    assert set(body) == _ORDER_KEYS
    order_id = _require_int(body["id"])
    assert order_id == _require_int(created["id"])
    assert _require_int(body["provider_id"]) == _require_int(created["provider_id"])
    assert _require_int(body["patient_id"]) == _require_int(created["patient_id"])
    assert body["status"] == "paid"
    assert body["patient_link"] == created["patient_link"]
    assert body["created_at"] == created["created_at"]
    paid_at = body["paid_at"]
    assert isinstance(paid_at, str)
    assert _TIMESTAMP.fullmatch(paid_at)
    assert body["payment_ref"] == f"fake_{order_id}"
    assert body["cancelled_at"] is None
    for field in _SPLIT_FIELDS:
        assert _require_int(body[field]) == _require_int(created[field])
    assert body["lines"] == created["lines"]
    for line_value in _require_list(body["lines"]):
        line = _require_dict(line_value)
        for field in _LINE_MONEY:
            _require_int(line[field])
    return paid_at


def _assert_paid_ledger(
    rows: list[dict[str, object]],
    order_id: int,
    paid_at: str,
    money: dict[str, object],
) -> None:
    assert len(rows) == 4
    amounts: dict[str, int] = {}
    for row in rows:
        assert row["order_id"] == order_id
        assert row["created_at"] == paid_at
        entry_type = row["entry_type"]
        assert isinstance(entry_type, str)
        assert entry_type not in amounts
        amounts[entry_type] = _require_int(row["amount_cents"])
    assert set(amounts) == {
        "patient_payment",
        "cerbo_cogs",
        "cerbo_fee",
        "provider_payable",
    }
    assert amounts["patient_payment"] == _require_int(money["subtotal_cents"])
    assert amounts["cerbo_cogs"] == _require_int(money["cogs_total_cents"])
    assert amounts["cerbo_fee"] == _require_int(money["platform_fee_cents"])
    assert amounts["provider_payable"] == _require_int(money["provider_payout_cents"])
    allocated = amounts["cerbo_cogs"] + amounts["cerbo_fee"] + amounts["provider_payable"]
    assert allocated == amounts["patient_payment"]


def _assert_pending_untouched(
    application: FastAPI,
    created: dict[str, object],
    stocks_before: dict[int, int],
    *,
    charge_count: int,
) -> None:
    order_id = _require_int(created["id"])
    stored = _load_order(application, order_id)
    assert stored["status"] == "pending_payment"
    assert stored["paid_at"] is None
    assert stored["payment_ref"] is None
    assert stored["cancelled_at"] is None
    _assert_money_unchanged(stored, created)
    assert _stocks(application) == stocks_before
    assert _ledger_rows(application) == []
    assert _charge_count(application) == charge_count
    assert _ship_calls(application) == []


def _assert_paid_view(view: object, order_id: int) -> tuple[str, str]:
    assert _require_int(getattr(view, "id")) == order_id
    assert getattr(view, "status") == "paid"
    paid_at = getattr(view, "paid_at")
    payment_ref = getattr(view, "payment_ref")
    assert isinstance(paid_at, str)
    assert _TIMESTAMP.fullmatch(paid_at)
    assert payment_ref == f"fake_{order_id}"
    assert getattr(view, "cancelled_at") is None
    for field in _SPLIT_FIELDS:
        _require_int(getattr(view, field))
    return paid_at, str(payment_ref)


def _assert_cancelled_view(view: object, order_id: int) -> str:
    assert _require_int(getattr(view, "id")) == order_id
    assert getattr(view, "status") == "cancelled"
    cancelled_at = getattr(view, "cancelled_at")
    assert isinstance(cancelled_at, str)
    assert _TIMESTAMP.fullmatch(cancelled_at)
    assert getattr(view, "paid_at") is None
    assert getattr(view, "payment_ref") is None
    for field in _SPLIT_FIELDS:
        _require_int(getattr(view, field))
    return cancelled_at


def _succeeded(call: _Call) -> object:
    if call.error is not None:
        raise call.error
    assert call.view is not None
    return call.view


def _expect_error(call: _Call, error_type: type[Exception]) -> Exception:
    assert call.view is None
    error = call.error
    assert isinstance(error, Exception)
    if isinstance(error, PaymentDeclined) and error_type is not PaymentDeclined:
        raise AssertionError("payment was declined") from error
    if not isinstance(error, error_type):
        raise error
    return error


def _start_pay(
    application: FastAPI,
    order_id: int,
    payment_provider: object,
    fulfillment: object,
    call: _Call,
) -> threading.Thread:
    # session.get takes BEGIN IMMEDIATE and holds it through the service call.
    # A barrier after both loads would deadlock: the second begin waits.
    def _target() -> None:
        session: Session = application.state.session_factory()
        try:
            loaded = session.get(Order, order_id)
            assert loaded is not None
            assert _require_int(loaded.id) == order_id
            call.view = pay_order(
                session,
                order_id,
                "fake_card_ok",
                payment_provider,
                fulfillment,
            )
        except Exception as exc:
            call.error = exc
        finally:
            session.close()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


def _start_cancel(application: FastAPI, order_id: int, call: _Call) -> threading.Thread:
    def _target() -> None:
        session: Session = application.state.session_factory()
        try:
            loaded = session.get(Order, order_id)
            assert loaded is not None
            assert _require_int(loaded.id) == order_id
            call.view = cancel_order(session, loaded)
        except Exception as exc:
            call.error = exc
        finally:
            session.close()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


def _finish(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(_JOIN_TIMEOUT_SECONDS)
    for thread in threads:
        assert not thread.is_alive()


@contextmanager
def _seeded(
    tmp_path: Path,
) -> Iterator[tuple[FastAPI, TestClient, list[dict[str, object]]]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        _assert_seed_users(client)
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        yield application, client, catalog


def test_jane_pays_a_two_line_order_decrements_stock_and_writes_four_ledger_rows(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        d3_id = _product_id(catalog, "D3-K2")
        magnesium_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        d3_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
        assert magnesium_price == 2_400
        assert d3_price == 1_800
        lines = [
            _request_line(magnesium_id, 2, magnesium_price),
            _request_line(d3_id, 1, d3_price),
        ]
        created = _create_order(client, provider_id, jane_id, lines)
        order_id = _require_int(created["id"])
        assert _require_int(created["patient_id"]) == jane_id
        before = _stocks(application)
        assert before[magnesium_id] == 50
        assert before[d3_id] == 40
        assert before[_product_id(catalog, "OMEGA3")] == 25
        assert before[_product_id(catalog, "PROBIO50")] == 1
        assert _charge_count(application) == 0
        assert _ship_calls(application) == []
        assert _ledger_rows(application) == []

        response = _pay(client, order_id, jane_id)
        assert response.status_code == 200
        body = _require_dict(response.json())
        paid_at = _assert_paid_response(body, created)
        stored = _load_order(application, order_id)
        assert stored["status"] == "paid"
        assert stored["paid_at"] == paid_at
        assert stored["payment_ref"] == f"fake_{order_id}"
        assert stored["cancelled_at"] is None
        _assert_money_unchanged(stored, created)
        _assert_paid_ledger(_ledger_rows(application), order_id, paid_at, body)

        expected = dict(before)
        expected[magnesium_id] = 48
        expected[d3_id] = 39
        assert _stocks(application) == expected
        assert _charge_count(application) == 1
        assert _ship_calls(application) == [order_id]

        follow = client.get(f"/orders/{order_id}", headers=_headers(jane_id))
        assert follow.status_code == 200
        assert follow.json() == body


def test_declined_card_is_rejected_and_a_later_approval_pays_the_same_order(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        assert before[magnesium_id] == 50

        declined = _pay(client, order_id, jane_id, "fake_card_decline")
        assert declined.status_code == 402
        assert declined.json() == _PAYMENT_DECLINED
        _assert_pending_untouched(application, created, before, charge_count=1)

        approved = _pay(client, order_id, jane_id, "fake_card_ok")
        assert approved.status_code == 200
        body = _require_dict(approved.json())
        paid_at = _assert_paid_response(body, created)
        expected = dict(before)
        expected[magnesium_id] = 49
        assert _stocks(application) == expected
        _assert_paid_ledger(_ledger_rows(application), order_id, paid_at, body)
        assert _charge_count(application) == 2
        assert _ship_calls(application) == [order_id]


def test_paying_two_probiotics_when_one_is_in_stock_charges_nothing(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        probiotic_id = _product_id(catalog, "PROBIO50")
        price = _catalog_int(catalog, "PROBIO50", "suggested_price_cents")
        assert _catalog_int(catalog, "PROBIO50", "stock_qty") == 1
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(probiotic_id, 2, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        assert before[probiotic_id] == 1

        response = _pay(client, order_id, jane_id)
        assert response.status_code == 409
        assert response.json() == _OUT_OF_STOCK
        _assert_pending_untouched(application, created, before, charge_count=0)


def test_an_order_with_one_in_stock_line_and_one_out_of_stock_line_charges_nothing(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        probiotic_id = _product_id(catalog, "PROBIO50")
        magnesium_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        probiotic_price = _catalog_int(catalog, "PROBIO50", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [
                _request_line(magnesium_id, 1, magnesium_price),
                _request_line(probiotic_id, 2, probiotic_price),
            ],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        assert before[magnesium_id] == 50
        assert before[probiotic_id] == 1

        response = _pay(client, order_id, jane_id)
        assert response.status_code == 409
        assert response.json() == _OUT_OF_STOCK
        stored = _load_order(application, order_id)
        assert stored["status"] == "pending_payment"
        assert stored["paid_at"] is None
        assert stored["payment_ref"] is None
        _assert_pending_untouched(application, created, before, charge_count=0)
        after = _stocks(application)
        assert after[magnesium_id] == before[magnesium_id]
        assert after[probiotic_id] == before[probiotic_id]


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"payment_method": None},
        {"payment_method": True},
        {"payment_method": 1},
        {"payment_method": 1.5},
        {"payment_method": "card"},
        {"payment_method": ""},
        {"payment_method": "fake_card_OK"},
        {"payment_method": ["fake_card_ok"]},
    ),
    ids=(
        "missing-field",
        "null",
        "bool",
        "integer",
        "float",
        "other-string",
        "empty-string",
        "wrong-case",
        "list",
    ),
)
def test_invalid_payment_method_is_rejected_and_writes_nothing(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before_stocks = _stocks(application)
        before_order = _load_order(application, order_id)

        response = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json=payload,
        )
        assert response.status_code == 422
        assert response.json() == _VALIDATION_ERROR
        assert _charge_count(application) == 0
        assert _ship_calls(application) == []
        assert _ledger_rows(application) == []
        assert _stocks(application) == before_stocks
        assert _load_order(application, order_id) == before_order


def test_paying_an_already_paid_order_returns_the_same_receipt(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 2, price)],
        )
        order_id = _require_int(created["id"])

        first = _pay(client, order_id, jane_id)
        assert first.status_code == 200
        first_body = _require_dict(first.json())
        paid_at = _assert_paid_response(first_body, created)
        ledger_after_first = _ledger_rows(application)
        _assert_paid_ledger(ledger_after_first, order_id, paid_at, first_body)
        stock_after_first = _stocks(application)
        assert stock_after_first[magnesium_id] == 48
        assert _charge_count(application) == 1
        assert _ship_calls(application) == [order_id]

        second = _pay(client, order_id, jane_id)
        assert second.status_code == 200
        second_body = _require_dict(second.json())
        assert second_body == first_body
        follow = client.get(f"/orders/{order_id}", headers=_headers(jane_id))
        assert follow.status_code == 200
        assert follow.json() == first_body
        assert _charge_count(application) == 1
        assert _ship_calls(application) == [order_id]
        assert len(_ship_calls(application)) == 1
        assert _ledger_rows(application) == ledger_after_first
        assert len(_ledger_rows(application)) == 4
        assert _stocks(application) == stock_after_first


def test_a_cancelled_order_cannot_be_paid(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)

        cancelled = client.post(f"/orders/{order_id}/cancel", headers=_headers(provider_id))
        assert cancelled.status_code == 200
        cancelled_body = _require_dict(cancelled.json())
        assert cancelled_body["status"] == "cancelled"
        stored = _load_order(application, order_id)
        assert stored["status"] == "cancelled"
        assert stored["paid_at"] is None
        assert stored["payment_ref"] is None

        response = _pay(client, order_id, jane_id)
        assert response.status_code == 409
        assert response.json() == _NOT_PAYABLE
        assert _load_order(application, order_id) == stored
        assert _load_order(application, order_id)["status"] == "cancelled"
        assert _charge_count(application) == 0
        assert _ledger_rows(application) == []
        assert _ship_calls(application) == []
        assert _stocks(application) == before


def test_another_patient_cannot_pay_janes_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        assert sam_id != jane_id
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        assert _require_int(created["patient_id"]) == jane_id
        before = _stocks(application)

        response = _pay(client, order_id, sam_id)
        assert response.status_code == 404
        assert response.json() == _NOT_FOUND
        _assert_pending_untouched(application, created, before, charge_count=0)


def test_the_owning_provider_and_admin_cannot_pay(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        admin_id = _user_id(client, "Cerbo Admin")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        assert _require_int(created["provider_id"]) == provider_id
        before = _stocks(application)
        before_order = _load_order(application, order_id)

        for user_id in (provider_id, admin_id):
            response = _pay(client, order_id, user_id)
            assert response.status_code == 403
            assert response.json() == _FORBIDDEN
            assert _load_order(application, order_id) == before_order
            assert _charge_count(application) == 0
            assert _ledger_rows(application) == []
            assert _ship_calls(application) == []
            assert _stocks(application) == before


@pytest.mark.parametrize(
    "headers",
    (None, {"X-User-Id": "999999"}),
    ids=("missing-user", "unknown-user"),
)
def test_missing_or_unknown_user_cannot_pay(
    tmp_path: Path,
    headers: dict[str, str] | None,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        before_order = _load_order(application, order_id)

        response = client.post(
            f"/orders/{order_id}/pay",
            headers=headers,
            json={"payment_method": "fake_card_ok"},
        )
        assert response.status_code == 401
        assert response.json() == _UNAUTHENTICATED
        assert _load_order(application, order_id) == before_order
        assert _charge_count(application) == 0
        assert _ledger_rows(application) == []
        assert _ship_calls(application) == []
        assert _stocks(application) == before


def test_unknown_or_invalid_order_ids_on_pay(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        before_order = _load_order(application, order_id)
        cases = (
            (f"/orders/{_UNKNOWN_ID}/pay", 404, _NOT_FOUND),
            ("/orders/abc/pay", 422, _VALIDATION_ERROR),
            (f"/orders/{_PAST_SQLITE_INT}/pay", 404, _NOT_FOUND),
        )

        for path, status, error in cases:
            response = client.post(
                path,
                headers=_headers(jane_id),
                json={"payment_method": "fake_card_ok"},
            )
            assert response.status_code != 500
            assert response.status_code == status
            assert response.json() == error
            assert _load_order(application, order_id) == before_order
            assert _charge_count(application) == 0
            assert _ledger_rows(application) == []
            assert _ship_calls(application) == []
            assert _stocks(application) == before


def test_fulfillment_failure_after_payment_still_returns_paid(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        assert before[magnesium_id] == 50
        assert _ship_calls(application) == []
        raising = _RaisingFulfillment()
        application.state.fulfillment = raising

        response = _pay(client, order_id, jane_id)
        assert response.status_code == 200
        body = _require_dict(response.json())
        paid_at = _assert_paid_response(body, created)
        stored = _load_order(application, order_id)
        assert stored["status"] == "paid"
        assert stored["paid_at"] == paid_at
        assert stored["payment_ref"] == f"fake_{order_id}"
        _assert_paid_ledger(_ledger_rows(application), order_id, paid_at, body)
        expected = dict(before)
        expected[magnesium_id] = 49
        assert _stocks(application) == expected
        assert raising.calls == [order_id]
        assert _charge_count(application) == 1


def test_concurrent_double_pay_charges_once_and_returns_the_same_receipt(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 2, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        assert before[magnesium_id] == 50
        assert _charge_count(application) == 0
        assert _ship_calls(application) == []
        assert _ledger_rows(application) == []
        payment_provider = application.state.payment_provider
        fulfillment = application.state.fulfillment
        first = _Call()
        second = _Call()

        _finish(
            [
                _start_pay(application, order_id, payment_provider, fulfillment, first),
                _start_pay(application, order_id, payment_provider, fulfillment, second),
            ]
        )

        first_view = _succeeded(first)
        second_view = _succeeded(second)
        first_paid_at, first_ref = _assert_paid_view(first_view, order_id)
        second_paid_at, second_ref = _assert_paid_view(second_view, order_id)
        assert first_paid_at == second_paid_at
        assert first_ref == second_ref
        for field in _SPLIT_FIELDS:
            assert _require_int(getattr(first_view, field)) == _require_int(
                getattr(second_view, field)
            )

        stocks, orders, ledger = _open_state(application)
        stored = _order_from(orders, order_id)
        assert stored["status"] == "paid"
        assert stored["paid_at"] == first_paid_at
        assert stored["payment_ref"] == first_ref
        _assert_money_unchanged(stored, created)
        _assert_paid_ledger(ledger, order_id, first_paid_at, stored)
        expected = dict(before)
        expected[magnesium_id] = 48
        assert stocks == expected
        assert _charge_count(application) == 1
        assert _ship_calls(application) == [order_id]


def test_concurrent_last_probiotic_lets_exactly_one_order_pay(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        probiotic_id = _product_id(catalog, "PROBIO50")
        price = _catalog_int(catalog, "PROBIO50", "suggested_price_cents")
        assert _catalog_int(catalog, "PROBIO50", "stock_qty") == 1
        jane_created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(probiotic_id, 1, price)],
        )
        sam_created = _create_order(
            client,
            provider_id,
            sam_id,
            [_request_line(probiotic_id, 1, price)],
        )
        jane_order_id = _require_int(jane_created["id"])
        sam_order_id = _require_int(sam_created["id"])
        assert jane_order_id != sam_order_id
        before = _stocks(application)
        assert before[probiotic_id] == 1
        assert _charge_count(application) == 0
        assert _ship_calls(application) == []
        payment_provider = application.state.payment_provider
        fulfillment = application.state.fulfillment
        jane_call = _Call()
        sam_call = _Call()

        _finish(
            [
                _start_pay(application, jane_order_id, payment_provider, fulfillment, jane_call),
                _start_pay(application, sam_order_id, payment_provider, fulfillment, sam_call),
            ]
        )

        if jane_call.view is not None and sam_call.view is not None:
            raise AssertionError("both pays succeeded")
        if jane_call.view is None and sam_call.view is None:
            assert jane_call.error is not None
            raise jane_call.error
        if jane_call.view is not None:
            winner_call = jane_call
            loser_call = sam_call
            winner_id = jane_order_id
            loser_id = sam_order_id
            winner_created = jane_created
        else:
            winner_call = sam_call
            loser_call = jane_call
            winner_id = sam_order_id
            loser_id = jane_order_id
            winner_created = sam_created
        view = _succeeded(winner_call)
        paid_at, payment_ref = _assert_paid_view(view, winner_id)
        _expect_error(loser_call, OutOfStock)
        for field in _SPLIT_FIELDS:
            _require_int(getattr(view, field))

        stocks, orders, ledger = _open_state(application)
        winner = _order_from(orders, winner_id)
        loser = _order_from(orders, loser_id)
        assert winner["status"] == "paid"
        assert winner["paid_at"] == paid_at
        assert winner["payment_ref"] == payment_ref
        _assert_money_unchanged(winner, winner_created)
        assert loser["status"] == "pending_payment"
        assert loser["payment_ref"] is None
        assert loser["paid_at"] is None
        assert all(row["order_id"] == winner_id for row in ledger)
        assert not any(row["order_id"] == loser_id for row in ledger)
        _assert_paid_ledger(ledger, winner_id, paid_at, winner)
        assert stocks[probiotic_id] == 0
        assert all(qty >= 0 for qty in stocks.values())
        for product_id, qty in before.items():
            if product_id == probiotic_id:
                continue
            assert stocks[product_id] == qty
        assert _charge_count(application) == 1
        assert _ship_calls(application) == [winner_id]


def test_concurrent_pay_and_cancel_lets_exactly_one_win(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        magnesium_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        assert _catalog_int(catalog, "MAG-GLY", "stock_qty") == 50
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(magnesium_id, 1, price)],
        )
        order_id = _require_int(created["id"])
        before = _stocks(application)
        assert before[magnesium_id] == 50
        assert _load_order(application, order_id)["status"] == "pending_payment"
        assert _charge_count(application) == 0
        assert _ship_calls(application) == []
        assert _ledger_rows(application) == []
        payment_provider = application.state.payment_provider
        fulfillment = application.state.fulfillment
        pay_call = _Call()
        cancel_call = _Call()

        _finish(
            [
                _start_pay(application, order_id, payment_provider, fulfillment, pay_call),
                _start_cancel(application, order_id, cancel_call),
            ]
        )

        pay_ok = pay_call.view is not None and pay_call.error is None
        cancel_ok = cancel_call.view is not None and cancel_call.error is None
        assert pay_ok != cancel_ok

        stocks, orders, ledger = _open_state(application)
        stored = _order_from(orders, order_id)
        _assert_money_unchanged(stored, created)
        if stored["status"] == "paid":
            view = _succeeded(pay_call)
            paid_at, payment_ref = _assert_paid_view(view, order_id)
            _expect_error(cancel_call, OrderNotCancellable)
            assert stored["paid_at"] == paid_at
            assert stored["payment_ref"] == payment_ref
            assert stored["cancelled_at"] is None
            _assert_paid_ledger(ledger, order_id, paid_at, stored)
            expected = dict(before)
            expected[magnesium_id] = 49
            assert stocks == expected
            assert _charge_count(application) == 1
            assert _ship_calls(application) == [order_id]
        elif stored["status"] == "cancelled":
            view = _succeeded(cancel_call)
            cancelled_at = _assert_cancelled_view(view, order_id)
            _expect_error(pay_call, OrderNotPayable)
            assert stored["cancelled_at"] == cancelled_at
            assert stored["paid_at"] is None
            assert stored["payment_ref"] is None
            assert ledger == []
            assert stocks == before
            assert _charge_count(application) == 0
            assert _ship_calls(application) == []
        else:
            raise AssertionError(stored["status"])

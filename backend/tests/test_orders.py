import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import LedgerEntry, Order, OrderLine, Product, ProviderProduct, User

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
    "provider_payout_cents",
)
_PREVIEW_LINE_FIELDS = (
    "product_id",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
    "stock_available",
)
_PRICED_LINE_FIELDS = (
    "product_id",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
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
}
_STORED_LINE_KEYS = {
    "product_id",
    "product_name",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "dosing",
    "note",
}
_COUNTED_MODELS = (
    ("users", User),
    ("products", Product),
    ("provider_products", ProviderProduct),
    ("orders", Order),
    ("order_lines", OrderLine),
    ("ledger_entries", LedgerEntry),
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
_PAID_AT = "2026-10-05T17:26:00Z"
_PAYMENT_REF = "pay_test"
_UPDATED_PRICE_CENTS = 2_500
_RAISED_COGS_CENTS = 5_000
_RENAMED_PRODUCT = "Renamed Magnesium Glycinate"
_UNAVAILABLE = "Product is not available for this provider."
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
_INVALID_PATIENT = {
    "error": {
        "code": "INVALID_PATIENT",
        "message": "Patient must be a patient user.",
        "line_index": None,
    }
}
_NOT_CANCELLABLE = {
    "error": {
        "code": "ORDER_NOT_CANCELLABLE",
        "message": "Order cannot be cancelled.",
        "line_index": None,
    }
}
_LINE_BELOW_COGS = {
    "error": {
        "code": "LINE_BELOW_COGS",
        "message": "Unit price must be at least the unit cost.",
        "line_index": 0,
    }
}


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def order_created(self, order: object, patient_link: str) -> None:
        order_id = getattr(order, "id", None)
        assert isinstance(order_id, int) and not isinstance(order_id, bool)
        assert isinstance(patient_link, str)
        self.calls.append((order_id, patient_link))


class _RaisingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.invoked = False

    def order_created(self, order: object, patient_link: str) -> None:
        self.invoked = True
        raise RuntimeError("notifier failed")


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
    return create_app(database_url=f"sqlite:///{tmp_path / 'orders.db'}")


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


def _names(catalog: list[dict[str, object]]) -> dict[int, str]:
    names: dict[int, str] = {}
    for row in catalog:
        name = row["name"]
        assert isinstance(name, str)
        names[_require_int(row["id"])] = name
    return names


def _request_line(product_id: int, qty: int, unit_price_cents: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "dosing": "Example: 1 capsule daily with a meal",
    }


def _raw_order(patient_id: str, product_id: int, qty: str, unit_price_cents: str) -> str:
    return (
        '{"patient_id":'
        + patient_id
        + ',"lines":[{"product_id":'
        + str(product_id)
        + ',"qty":'
        + qty
        + ',"unit_price_cents":'
        + unit_price_cents
        + "}]}"
    )


def _ensure_notifier(application: FastAPI) -> None:
    if getattr(application.state, "notifier", None) is None:
        application.state.notifier = _RecordingNotifier()


def _calls(application: FastAPI) -> list[tuple[int, str]]:
    _ensure_notifier(application)
    raw = getattr(application.state.notifier, "calls", None)
    assert isinstance(raw, list)
    parsed: list[tuple[int, str]] = []
    for item in raw:
        assert isinstance(item, tuple)
        assert len(item) == 2
        order_id, link = item
        assert isinstance(order_id, int) and not isinstance(order_id, bool)
        assert isinstance(link, str)
        parsed.append((order_id, link))
    return parsed


def _row_counts(application: FastAPI) -> dict[str, int]:
    session: Session = application.state.session_factory()
    try:
        counts: dict[str, int] = {}
        for name, model in _COUNTED_MODELS:
            counted = session.scalar(select(func.count()).select_from(model))
            counts[name] = _require_int(counted)
        return counts
    finally:
        session.close()


def _orders(application: FastAPI) -> list[dict[str, object]]:
    session: Session = application.state.session_factory()
    try:
        rows = list(session.scalars(select(Order).order_by(Order.id)))
        loaded: list[dict[str, object]] = []
        for order in rows:
            line_rows = list(
                session.scalars(
                    select(OrderLine)
                    .where(OrderLine.order_id == order.id)
                    .order_by(OrderLine.id)
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
                    }
                )
            loaded.append(
                {
                    "id": _require_int(order.id),
                    "provider_id": _require_int(order.provider_id),
                    "patient_id": _require_int(order.patient_id),
                    "status": order.status,
                    "fee_bps": _require_int(order.fee_bps),
                    "subtotal_cents": _require_int(order.subtotal_cents),
                    "cogs_total_cents": _require_int(order.cogs_total_cents),
                    "platform_fee_cents": _require_int(order.platform_fee_cents),
                    "provider_payout_cents": _require_int(order.provider_payout_cents),
                    "payment_ref": order.payment_ref,
                    "created_at": order.created_at,
                    "paid_at": order.paid_at,
                    "cancelled_at": order.cancelled_at,
                    "lines": lines,
                }
            )
        return loaded
    finally:
        session.close()


def _load_order(application: FastAPI, order_id: int) -> dict[str, object]:
    matches = [order for order in _orders(application) if order["id"] == order_id]
    assert len(matches) == 1
    return matches[0]


def _product_row(application: FastAPI, product_id: int) -> dict[str, object]:
    session: Session = application.state.session_factory()
    try:
        product = session.get(Product, product_id)
        assert product is not None
        return {
            "name": product.name,
            "unit_cogs_cents": _require_int(product.unit_cogs_cents),
            "stock_qty": _require_int(product.stock_qty),
        }
    finally:
        session.close()


def _default_price(application: FastAPI, provider_id: int, product_id: int) -> int:
    session: Session = application.state.session_factory()
    try:
        link = session.get(ProviderProduct, (provider_id, product_id))
        assert link is not None
        return _require_int(link.default_price_cents)
    finally:
        session.close()


def _set_name_and_cogs(
    application: FastAPI,
    product_id: int,
    name: str,
    unit_cogs_cents: int,
) -> None:
    session: Session = application.state.session_factory()
    try:
        product = session.get(Product, product_id)
        assert product is not None
        product.name = name
        product.unit_cogs_cents = unit_cogs_cents
        session.commit()
    finally:
        session.close()


def _mark_paid(application: FastAPI, order_id: int) -> None:
    # There is no pay endpoint in this task. The paid row is written here.
    assert _TIMESTAMP.fullmatch(_PAID_AT)
    session: Session = application.state.session_factory()
    try:
        order = session.get(Order, order_id)
        assert order is not None
        assert order.status == "pending_payment"
        order.status = "paid"
        order.paid_at = _PAID_AT
        order.payment_ref = _PAYMENT_REF
        session.commit()
    finally:
        session.close()


def _insert_user(application: FastAPI, name: str, role: str) -> None:
    session: Session = application.state.session_factory()
    try:
        session.add(User(name=name, role=role))
        session.commit()
    finally:
        session.close()


def _parse_preview(payload: object) -> dict[str, object]:
    body = _require_dict(payload)
    assert set(body) == {"lines", *_SPLIT_FIELDS}
    for field in _SPLIT_FIELDS:
        _require_int(body[field])
    lines: list[dict[str, object]] = []
    for line_value in _require_list(body["lines"]):
        line = _require_dict(line_value)
        assert set(line) == set(_PREVIEW_LINE_FIELDS)
        for field in _PREVIEW_LINE_FIELDS:
            _require_int(line[field])
        lines.append(line)
    body["lines"] = lines
    return body


def _preview_ok(
    application: FastAPI,
    client: TestClient,
    provider_id: int,
    lines: list[dict[str, int]],
) -> dict[str, object]:
    before = _row_counts(application)
    response = client.post(
        "/orders/preview",
        headers=_headers(provider_id),
        json={"lines": lines},
    )
    assert response.status_code == 200
    assert _row_counts(application) == before
    return _parse_preview(response.json())


def _assert_pending_order(
    payload: object,
    *,
    provider_id: int,
    patient_id: int,
    preview: dict[str, object],
    names: dict[int, str],
) -> dict[str, object]:
    body = _require_dict(payload)
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
        assert _require_int(body[field]) == _require_int(preview[field])
    preview_lines = [_require_dict(line) for line in _require_list(preview["lines"])]
    response_lines = [_require_dict(line) for line in _require_list(body["lines"])]
    assert len(response_lines) == len(preview_lines)
    for response_line, preview_line in zip(response_lines, preview_lines, strict=True):
        assert set(response_line) == _LINE_KEYS
        for field in _PRICED_LINE_FIELDS:
            assert _require_int(response_line[field]) == _require_int(preview_line[field])
        product_id = _require_int(response_line["product_id"])
        product_name = response_line["product_name"]
        assert isinstance(product_name, str)
        assert product_name == names[product_id]
        qty = _require_int(response_line["qty"])
        unit_price_cents = _require_int(response_line["unit_price_cents"])
        unit_cogs_cents = _require_int(response_line["unit_cogs_cents"])
        line_total_cents = _require_int(response_line["line_total_cents"])
        line_cogs_cents = _require_int(response_line["line_cogs_cents"])
        line_margin_cents = _require_int(response_line["line_margin_cents"])
        assert line_total_cents == unit_price_cents * qty
        assert line_cogs_cents == unit_cogs_cents * qty
        assert line_margin_cents == line_total_cents - line_cogs_cents
    return body


def _assert_stored_matches(
    stored: dict[str, object],
    body: dict[str, object],
    preview: dict[str, object],
    names: dict[int, str],
) -> None:
    assert stored["id"] == body["id"]
    assert stored["provider_id"] == body["provider_id"]
    assert stored["patient_id"] == body["patient_id"]
    assert stored["status"] == "pending_payment"
    assert stored["created_at"] == body["created_at"]
    created_at = stored["created_at"]
    assert isinstance(created_at, str)
    assert _TIMESTAMP.fullmatch(created_at)
    assert stored["paid_at"] is None
    assert stored["cancelled_at"] is None
    assert stored["payment_ref"] is None
    for field in _SPLIT_FIELDS:
        assert stored[field] == _require_int(preview[field])
        assert stored[field] == _require_int(body[field])
    preview_lines = [_require_dict(line) for line in _require_list(preview["lines"])]
    stored_lines = stored["lines"]
    assert isinstance(stored_lines, list)
    assert len(stored_lines) == len(preview_lines)
    for stored_value, preview_line in zip(stored_lines, preview_lines, strict=True):
        stored_line = _require_dict(stored_value)
        assert set(stored_line) == _STORED_LINE_KEYS
        product_id = _require_int(stored_line["product_id"])
        assert product_id == _require_int(preview_line["product_id"])
        product_name = stored_line["product_name"]
        assert isinstance(product_name, str)
        assert product_name == names[product_id]
        assert _require_int(stored_line["qty"]) == _require_int(preview_line["qty"])
        assert _require_int(stored_line["unit_price_cents"]) == _require_int(
            preview_line["unit_price_cents"]
        )
        assert _require_int(stored_line["unit_cogs_cents"]) == _require_int(
            preview_line["unit_cogs_cents"]
        )


def _create_order(
    application: FastAPI,
    client: TestClient,
    provider_id: int,
    patient_id: int,
    lines: list[dict[str, int]],
    names: dict[int, str],
    preview: dict[str, object],
) -> dict[str, object]:
    before_counts = _row_counts(application)
    before_calls = _calls(application)
    response = client.post(
        "/orders",
        headers=_headers(provider_id),
        json={"patient_id": patient_id, "lines": lines},
    )
    assert response.status_code == 200
    body = _assert_pending_order(
        response.json(),
        provider_id=provider_id,
        patient_id=patient_id,
        preview=preview,
        names=names,
    )
    _assert_stored_matches(
        _load_order(application, _require_int(body["id"])),
        body,
        preview,
        names,
    )
    after_counts = _row_counts(application)
    assert after_counts["orders"] == before_counts["orders"] + 1
    assert after_counts["order_lines"] == before_counts["order_lines"] + len(lines)
    assert after_counts["ledger_entries"] == before_counts["ledger_entries"]
    for table in ("users", "products", "provider_products"):
        assert after_counts[table] == before_counts[table]
    order_id = _require_int(body["id"])
    patient_link = body["patient_link"]
    assert isinstance(patient_link, str)
    assert patient_link == f"/orders/{order_id}"
    assert _calls(application) == [*before_calls, (order_id, patient_link)]
    return body


def _magnesium_line(catalog: list[dict[str, object]], qty: int, price: int) -> dict[str, int]:
    return _request_line(_product_id(catalog, "MAG-GLY"), qty, price)


@contextmanager
def _seeded(
    tmp_path: Path,
) -> Iterator[tuple[FastAPI, TestClient, list[dict[str, object]]]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        _ensure_notifier(application)
        _assert_seed_users(client)
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        yield application, client, catalog


def test_created_order_stores_the_preview_split_and_notifies_the_patient_link(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        assert jane_id != provider_id
        names = _names(catalog)
        magnesium_id = _product_id(catalog, "MAG-GLY")
        probiotic_id = _product_id(catalog, "PROBIO50")
        magnesium_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        probiotic_price = _catalog_int(catalog, "PROBIO50", "suggested_price_cents")
        probiotic_stock = _catalog_int(catalog, "PROBIO50", "stock_qty")
        assert magnesium_price == 2_400
        assert probiotic_price == 4_200
        assert probiotic_stock == 1
        assert names[magnesium_id] == "Magnesium Glycinate"
        assert names[probiotic_id] == "Probiotic 50B"
        qty_above_stock = 5
        assert qty_above_stock > probiotic_stock

        lines = [
            _request_line(magnesium_id, 2, magnesium_price),
            _request_line(probiotic_id, qty_above_stock, probiotic_price),
        ]
        assert all(set(line) == {"product_id", "qty", "unit_price_cents", "dosing"} for line in lines)
        preview_body = {"lines": lines}
        assert set(preview_body) == {"lines"}
        create_body = {"patient_id": jane_id, "lines": lines}
        assert set(create_body) == {"patient_id", "lines"}

        preview = _preview_ok(application, client, provider_id, lines)
        assert _calls(application) == []
        assert _row_counts(application)["ledger_entries"] == 0
        assert _product_row(application, probiotic_id)["stock_qty"] == probiotic_stock

        response = client.post("/orders", headers=_headers(provider_id), json=create_body)
        assert response.status_code == 200
        body = _assert_pending_order(
            response.json(),
            provider_id=provider_id,
            patient_id=jane_id,
            preview=preview,
            names=names,
        )
        order_id = _require_int(body["id"])
        patient_link = body["patient_link"]
        assert isinstance(patient_link, str)
        assert patient_link == f"/orders/{order_id}"
        stored = _load_order(application, order_id)
        _assert_stored_matches(stored, body, preview, names)
        assert _orders(application) == [stored]
        assert _calls(application) == [(order_id, patient_link)]
        assert _row_counts(application)["ledger_entries"] == 0
        assert _row_counts(application)["order_lines"] == 2
        assert _product_row(application, probiotic_id)["stock_qty"] == probiotic_stock
        reloaded = _load_catalog(client, provider_id)
        assert _catalog_int(reloaded, "PROBIO50", "stock_qty") == probiotic_stock


def test_later_cogs_default_price_and_name_changes_do_not_change_the_order(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        names = _names(catalog)
        product_id = _product_id(catalog, "MAG-GLY")
        original_name = names[product_id]
        original_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        original_cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        assert original_name == "Magnesium Glycinate"
        assert original_price == 2_400
        assert original_cogs == 1_200
        assert _UPDATED_PRICE_CENTS != original_price
        assert _RAISED_COGS_CENTS != original_cogs
        assert _RAISED_COGS_CENTS > original_price
        assert _RENAMED_PRODUCT != original_name

        lines = [_magnesium_line(catalog, 1, original_price)]
        preview = _preview_ok(application, client, provider_id, lines)
        created = _create_order(
            application,
            client,
            provider_id,
            jane_id,
            lines,
            names,
            preview,
        )
        order_id = _require_int(created["id"])

        updated = client.put(
            f"/provider/products/{product_id}",
            headers=_headers(provider_id),
            json={"enabled": True, "default_price_cents": _UPDATED_PRICE_CENTS},
        )
        assert updated.status_code == 200
        assert _require_int(_require_dict(updated.json())["default_price_cents"]) == (
            _UPDATED_PRICE_CENTS
        )
        assert _default_price(application, provider_id, product_id) == _UPDATED_PRICE_CENTS
        _set_name_and_cogs(application, product_id, _RENAMED_PRODUCT, _RAISED_COGS_CENTS)
        changed = _product_row(application, product_id)
        assert changed["name"] == _RENAMED_PRODUCT
        assert changed["unit_cogs_cents"] == _RAISED_COGS_CENTS

        catalog_after = _read_catalog(client, provider_id)
        assert _catalog_row(catalog_after, "MAG-GLY")["name"] == _RENAMED_PRODUCT
        assert _catalog_int(catalog_after, "MAG-GLY", "unit_cogs_cents") == _RAISED_COGS_CENTS
        repriced = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": lines},
        )
        assert repriced.status_code == 422
        assert repriced.json() == _LINE_BELOW_COGS
        assert repriced.json() != preview

        fetched = client.get(f"/orders/{order_id}", headers=_headers(provider_id))
        assert fetched.status_code == 200
        assert fetched.json() == created
        stored = _load_order(application, order_id)
        _assert_stored_matches(stored, created, preview, names)
        stored_lines = _require_list(stored["lines"])
        assert len(stored_lines) == 1
        stored_line = _require_dict(stored_lines[0])
        assert stored_line["product_name"] == original_name
        assert _require_int(stored_line["unit_cogs_cents"]) == original_cogs
        assert _require_int(stored_line["unit_price_cents"]) == original_price
        assert _default_price(application, provider_id, product_id) == _UPDATED_PRICE_CENTS


def test_notifier_error_does_not_roll_back_the_created_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        notifier = _RaisingNotifier()
        application.state.notifier = notifier

        response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines},
        )
        assert response.status_code == 200
        assert notifier.invoked is True
        body = _assert_pending_order(
            response.json(),
            provider_id=provider_id,
            patient_id=jane_id,
            preview=preview,
            names=names,
        )
        stored = _load_order(application, _require_int(body["id"]))
        _assert_stored_matches(stored, body, preview, names)
        assert _orders(application) == [stored]


@pytest.mark.parametrize(
    ("pricing", "code"),
    (
        ("below_cogs", "LINE_BELOW_COGS"),
        ("negative_payout", "NEGATIVE_PAYOUT"),
        ("empty", "EMPTY_ORDER"),
    ),
)
def test_pricing_failure_matches_preview_and_does_not_insert_or_notify(
    tmp_path: Path,
    pricing: str,
    code: str,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        product_id = _product_id(catalog, "MAG-GLY")
        cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        if pricing == "below_cogs":
            lines = [_request_line(product_id, 1, cogs - 1)]
        elif pricing == "negative_payout":
            lines = [_request_line(product_id, 1, cogs)]
        else:
            lines = []
        preview = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": lines},
        )
        assert preview.status_code == 422
        preview_body = preview.json()
        assert _require_dict(_require_dict(preview_body)["error"])["code"] == code
        before = _row_counts(application)
        response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines},
        )
        assert response.status_code == 422
        assert response.json() == preview_body
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []


@pytest.mark.parametrize("kind", ("disabled", "unknown"))
def test_unavailable_product_matches_preview_and_does_not_insert_or_notify(
    tmp_path: Path,
    kind: str,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        if kind == "disabled":
            product_id = _product_id(catalog, "MAG-GLY")
            price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
            disabled = client.put(
                f"/provider/products/{product_id}",
                headers=_headers(provider_id),
                json={"enabled": False, "default_price_cents": price},
            )
            assert disabled.status_code == 200
            assert _require_dict(disabled.json())["enabled"] is False
        else:
            product_id = _UNKNOWN_ID
            assert product_id not in {_require_int(row["id"]) for row in catalog}
            price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_request_line(product_id, 1, price)]
        preview = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": lines},
        )
        assert preview.status_code == 422
        assert preview.json() == {
            "error": {
                "code": "PRODUCT_UNAVAILABLE",
                "message": _UNAVAILABLE,
                "line_index": 0,
            }
        }
        before = _row_counts(application)
        response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines},
        )
        assert response.status_code == 422
        assert response.json() == preview.json()
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []


@pytest.mark.parametrize("patient_key", ("unknown", "provider", "admin", "past_sqlite_max"))
def test_patient_id_must_belong_to_a_patient_user(tmp_path: Path, patient_key: str) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        admin_id = _user_id(client, "Cerbo Admin")
        product_id = _product_id(catalog, "MAG-GLY")
        below_cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents") - 1
        lines = [_request_line(product_id, 1, below_cogs)]
        preview = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": lines},
        )
        assert preview.status_code == 422
        assert preview.json() == _LINE_BELOW_COGS
        if patient_key == "unknown":
            patient_id = _UNKNOWN_ID
            assert patient_id not in {_user_id(client, name) for name, _role in _SEED_USERS}
        elif patient_key == "provider":
            patient_id = provider_id
        elif patient_key == "admin":
            patient_id = admin_id
        else:
            patient_id = _PAST_SQLITE_INT
        assert patient_id != jane_id
        before = _row_counts(application)
        response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": patient_id, "lines": lines},
        )
        assert response.status_code != 500
        assert response.status_code == 422
        assert response.json() == _INVALID_PATIENT
        assert response.json() != preview.json()
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []


def test_owning_patient_and_provider_can_view_the_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        created = _create_order(
            application, client, provider_id, jane_id, lines, names, preview
        )
        order_id = _require_int(created["id"])

        for user_id in (jane_id, provider_id):
            fetched = client.get(f"/orders/{order_id}", headers=_headers(user_id))
            assert fetched.status_code == 200
            assert fetched.json() == created


def test_other_patient_provider_and_admin_cannot_view_the_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        admin_id = _user_id(client, "Cerbo Admin")
        assert sam_id != jane_id
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        created = _create_order(
            application, client, provider_id, jane_id, lines, names, preview
        )
        order_id = _require_int(created["id"])
        _insert_user(application, "Dr. Alex Kim", "provider")
        alex_id = _user_id(client, "Dr. Alex Kim")
        alex = [user for user in _users(client) if user["name"] == "Dr. Alex Kim"]
        assert len(alex) == 1
        assert alex[0]["role"] == "provider"
        assert alex_id not in (provider_id, jane_id)

        for user_id in (sam_id, alex_id):
            fetched = client.get(f"/orders/{order_id}", headers=_headers(user_id))
            assert fetched.status_code == 404
            assert fetched.json() == _NOT_FOUND
        admin = client.get(f"/orders/{order_id}", headers=_headers(admin_id))
        assert admin.status_code == 403
        assert admin.json() == _FORBIDDEN
        assert _load_order(application, order_id)["status"] == "pending_payment"


def test_patient_with_no_orders_gets_an_empty_list(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, _catalog):
        _insert_user(application, "Riley Chen", "patient")
        riley_id = _user_id(client, "Riley Chen")
        riley = [user for user in _users(client) if user["name"] == "Riley Chen"]
        assert len(riley) == 1
        assert riley[0]["role"] == "patient"
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        assert _orders(application) == []
        for user_id in (jane_id, sam_id, riley_id):
            response = client.get("/patient/orders", headers=_headers(user_id))
            assert response.status_code == 200
            assert response.json() == []


def test_patient_order_list_contains_only_that_patients_orders(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        assert jane_id != sam_id
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        jane_order = _create_order(
            application, client, provider_id, jane_id, lines, names, preview
        )
        jane_id_on_order = _require_int(jane_order["id"])

        jane_list = client.get("/patient/orders", headers=_headers(jane_id))
        assert jane_list.status_code == 200
        assert jane_list.json() == [jane_order]
        sam_list = client.get("/patient/orders", headers=_headers(sam_id))
        assert sam_list.status_code == 200
        assert sam_list.json() == []
        assert jane_id_on_order not in [
            _require_int(_require_dict(item)["id"]) for item in _require_list(sam_list.json())
        ]

        sam_order = _create_order(
            application, client, provider_id, sam_id, lines, names, preview
        )
        assert _require_int(sam_order["id"]) != jane_id_on_order
        assert _require_int(sam_order["patient_id"]) == sam_id
        jane_after = client.get("/patient/orders", headers=_headers(jane_id))
        sam_after = client.get("/patient/orders", headers=_headers(sam_id))
        assert jane_after.status_code == 200
        assert sam_after.status_code == 200
        assert jane_after.json() == [jane_order]
        assert sam_after.json() == [sam_order]


@pytest.mark.parametrize("name", ("Dr. Maya Patel", "Cerbo Admin"))
def test_provider_and_admin_cannot_list_patient_orders(tmp_path: Path, name: str) -> None:
    with _seeded(tmp_path) as (application, client, _catalog):
        user_id = _user_id(client, name)
        before = _row_counts(application)
        response = client.get("/patient/orders", headers=_headers(user_id))
        assert response.status_code == 403
        assert response.json() == _FORBIDDEN
        assert _row_counts(application) == before


def test_provider_can_cancel_a_pending_order_and_a_second_cancel_conflicts(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 2, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        created = _create_order(
            application, client, provider_id, jane_id, lines, names, preview
        )
        order_id = _require_int(created["id"])
        before = _load_order(application, order_id)
        calls_after_create = _calls(application)

        cancelled = client.post(f"/orders/{order_id}/cancel", headers=_headers(provider_id))
        assert cancelled.status_code == 200
        cancelled_body = _require_dict(cancelled.json())
        cancelled_at = cancelled_body["cancelled_at"]
        assert isinstance(cancelled_at, str)
        assert _TIMESTAMP.fullmatch(cancelled_at)
        expected = dict(created)
        expected["status"] = "cancelled"
        expected["cancelled_at"] = cancelled_at
        assert cancelled_body == expected
        assert cancelled_body["created_at"] == created["created_at"]
        assert cancelled_body["paid_at"] is None
        assert cancelled_body["payment_ref"] is None
        assert cancelled_body["lines"] == created["lines"]
        for field in _SPLIT_FIELDS:
            assert cancelled_body[field] == created[field]

        stored = _load_order(application, order_id)
        assert stored["status"] == "cancelled"
        assert stored["cancelled_at"] == cancelled_at
        assert stored["paid_at"] is None
        assert stored["payment_ref"] is None
        assert stored["created_at"] == before["created_at"]
        assert stored["lines"] == before["lines"]
        for field in _SPLIT_FIELDS:
            assert stored[field] == before[field]
        assert _calls(application) == calls_after_create

        again = client.post(f"/orders/{order_id}/cancel", headers=_headers(provider_id))
        assert again.status_code == 409
        assert again.json() == _NOT_CANCELLABLE
        after_second = _load_order(application, order_id)
        assert after_second == stored
        assert after_second["cancelled_at"] == cancelled_at


def test_cancelling_a_paid_order_conflicts_and_leaves_the_row_unchanged(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        created = _create_order(
            application, client, provider_id, jane_id, lines, names, preview
        )
        order_id = _require_int(created["id"])
        _mark_paid(application, order_id)
        paid = _load_order(application, order_id)
        assert paid["status"] == "paid"
        assert paid["paid_at"] == _PAID_AT
        assert paid["payment_ref"] == _PAYMENT_REF
        assert paid["cancelled_at"] is None
        calls_before = _calls(application)

        response = client.post(f"/orders/{order_id}/cancel", headers=_headers(provider_id))
        assert response.status_code == 409
        assert response.json() == _NOT_CANCELLABLE
        assert _load_order(application, order_id) == paid
        assert _calls(application) == calls_before


def test_patient_cannot_cancel_and_other_provider_gets_not_found(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        names = _names(catalog)
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        preview = _preview_ok(application, client, provider_id, lines)
        created = _create_order(
            application, client, provider_id, jane_id, lines, names, preview
        )
        order_id = _require_int(created["id"])
        before = _load_order(application, order_id)
        _insert_user(application, "Dr. Alex Kim", "provider")
        alex_id = _user_id(client, "Dr. Alex Kim")
        assert [user for user in _users(client) if user["name"] == "Dr. Alex Kim"][0]["role"] == (
            "provider"
        )

        jane = client.post(f"/orders/{order_id}/cancel", headers=_headers(jane_id))
        assert jane.status_code == 403
        assert jane.json() == _FORBIDDEN
        assert _load_order(application, order_id) == before

        alex = client.post(f"/orders/{order_id}/cancel", headers=_headers(alex_id))
        assert alex.status_code == 404
        assert alex.status_code != 403
        assert alex.json() == _NOT_FOUND
        assert _load_order(application, order_id) == before


@pytest.mark.parametrize(
    ("method", "path", "status", "error"),
    (
        ("GET", f"/orders/{_UNKNOWN_ID}", 404, _NOT_FOUND),
        ("POST", f"/orders/{_UNKNOWN_ID}/cancel", 404, _NOT_FOUND),
        ("GET", "/orders/abc", 422, _VALIDATION_ERROR),
        ("POST", "/orders/abc/cancel", 422, _VALIDATION_ERROR),
        ("GET", f"/orders/{_PAST_SQLITE_INT}", 404, _NOT_FOUND),
        ("POST", f"/orders/{_PAST_SQLITE_INT}/cancel", 404, _NOT_FOUND),
    ),
    ids=(
        "get-unknown",
        "cancel-unknown",
        "get-abc",
        "cancel-abc",
        "get-past-sqlite-max",
        "cancel-past-sqlite-max",
    ),
)
def test_unknown_or_invalid_order_ids(
    tmp_path: Path,
    method: str,
    path: str,
    status: int,
    error: dict[str, object],
) -> None:
    with _seeded(tmp_path) as (application, client, _catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        before = _row_counts(application)
        response = client.request(method, path, headers=_headers(provider_id))
        assert response.status_code != 500
        assert response.status_code == status
        assert response.json() == error
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []


@pytest.mark.parametrize(
    ("bad_field", "bad_token"),
    (
        ("patient_id", "float"),
        ("patient_id", "bool"),
        ("patient_id", "string"),
        ("qty", "float"),
        ("qty", "bool"),
        ("qty", "string"),
        ("unit_price_cents", "float"),
        ("unit_price_cents", "bool"),
        ("unit_price_cents", "string"),
    ),
    ids=(
        "patient-float",
        "patient-bool",
        "patient-numeric-string",
        "qty-float",
        "qty-bool",
        "qty-numeric-string",
        "price-float",
        "price-bool",
        "price-numeric-string",
    ),
)
def test_non_integer_patient_qty_or_price_is_rejected_and_inserts_nothing(
    tmp_path: Path,
    bad_field: str,
    bad_token: str,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        product_id = _product_id(catalog, "MAG-GLY")
        patient = str(jane_id)
        qty = "1"
        price = "2400"
        if bad_field == "patient_id":
            patient = {
                "float": f"{jane_id}.0",
                "bool": "true",
                "string": f'"{jane_id}"',
            }[bad_token]
        elif bad_field == "qty":
            qty = {"float": "1.0", "bool": "true", "string": '"1"'}[bad_token]
        else:
            price = {"float": "2500.0", "bool": "true", "string": '"2500"'}[bad_token]
        raw = _raw_order(patient, product_id, qty, price)
        if bad_token == "float":
            assert ".0" in raw
        before = _row_counts(application)
        response = client.post(
            "/orders",
            headers={**_headers(provider_id), "Content-Type": "application/json"},
            content=raw,
        )
        assert response.status_code == 422
        assert response.json() == _VALIDATION_ERROR
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []


@pytest.mark.parametrize("route", ("create", "detail", "list", "cancel"))
@pytest.mark.parametrize(
    "headers",
    (None, {"X-User-Id": "999999"}),
    ids=("missing-user", "unknown-user"),
)
def test_missing_or_unknown_user_is_unauthenticated(
    tmp_path: Path,
    route: str,
    headers: dict[str, str] | None,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        jane_id = _user_id(client, "Jane Doe")
        product_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        before = _row_counts(application)
        if route == "create":
            response = client.post(
                "/orders",
                headers=headers,
                json={
                    "patient_id": jane_id,
                    "lines": [_request_line(product_id, 1, price)],
                },
            )
        elif route == "detail":
            response = client.get(f"/orders/{_UNKNOWN_ID}", headers=headers)
        elif route == "list":
            response = client.get("/patient/orders", headers=headers)
        else:
            response = client.post(f"/orders/{_UNKNOWN_ID}/cancel", headers=headers)
        assert response.status_code == 401
        assert response.json() == _UNAUTHENTICATED
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []


@pytest.mark.parametrize("name", ("Jane Doe", "Sam Lee", "Cerbo Admin"))
def test_patient_and_admin_cannot_create_an_order(tmp_path: Path, name: str) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        caller_id = _user_id(client, name)
        jane_id = _user_id(client, "Jane Doe")
        assert caller_id != provider_id
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        lines = [_magnesium_line(catalog, 1, price)]
        before = _row_counts(application)
        response = client.post(
            "/orders",
            headers=_headers(caller_id),
            json={"patient_id": jane_id, "lines": lines},
        )
        assert response.status_code == 403
        assert response.json() == _FORBIDDEN
        assert _row_counts(application) == before
        assert _orders(application) == []
        assert _calls(application) == []

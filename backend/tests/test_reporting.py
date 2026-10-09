import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.money import LineInput, compute_fee, compute_split
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
    "donation_bps",
    "donation_cents",
    "provider_payout_cents",
)
_DASHBOARD_KEYS = {
    "gmv_cents",
    "platform_fee_cents",
    "donation_cents",
    "earnings_cents",
    "paid_orders",
    "units_sold",
    "pending_orders",
}
_PAID_ORDER_KEYS = {
    "id",
    "paid_at",
    "patient_id",
    "patient_name",
    "subtotal_cents",
    "platform_fee_cents",
    "donation_cents",
    "provider_payout_cents",
    "audit_link",
}
_UNIT_KEYS = {"product_id", "product_name", "qty"}
_PENDING_KEYS = {"id", "created_at", "patient_id", "patient_name"}
_AUDIT_KEYS = {
    "id",
    "status",
    "payment_ref",
    "paid_at",
    "lines",
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
_LINE_KEYS = {
    "product_id",
    "product_name",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
    "donation_cents",
    "fund_id",
    "fund_name",
    "fund_url",
}
_LEDGER_KEYS = {"entry_type", "amount_cents", "created_at", "fund_id"}
_LEDGER_TYPES = (
    "patient_payment",
    "cerbo_cogs",
    "cerbo_fee",
    "provider_payable",
)
_HEADLINE_TYPES = (
    "patient_payment",
    "cerbo_fee",
    "provider_payable",
    "research_donation",
)
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
_RENAMED_PATIENT = "Jane Q. Doe"
_RENAMED_PRODUCT = "Renamed Magnesium Glycinate"
_RAISED_COGS_CENTS = 5_000
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


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _require_str(value: object) -> str:
    assert isinstance(value, str)
    return value


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'reporting.db'}")


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


def _names_by_id(client: TestClient) -> dict[int, str]:
    names: dict[int, str] = {}
    for user in _users(client):
        names[_require_int(user["id"])] = _require_str(user["name"])
    return names


def _assert_seed_users(client: TestClient) -> None:
    indexed: dict[str, dict[str, object]] = {}
    for user in _users(client):
        indexed[_require_str(user["name"])] = user
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
                    "created_at": order.created_at,
                    "paid_at": order.paid_at,
                    "cancelled_at": order.cancelled_at,
                    "payment_ref": order.payment_ref,
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


def _orders_for(
    application: FastAPI, provider_id: int, status: str
) -> list[dict[str, object]]:
    matched = [
        order
        for order in _orders(application)
        if order["provider_id"] == provider_id and order["status"] == status
    ]
    matched.sort(key=lambda order: _require_int(order["id"]))
    return matched


def _ledger(application: FastAPI) -> list[dict[str, object]]:
    session: Session = application.state.session_factory()
    try:
        rows = list(session.scalars(select(LedgerEntry).order_by(LedgerEntry.id)))
        loaded: list[dict[str, object]] = []
        for row in rows:
            loaded.append(
                {
                    "id": _require_int(row.id),
                    "order_id": _require_int(row.order_id),
                    "entry_type": _require_str(row.entry_type),
                    "amount_cents": _require_int(row.amount_cents),
                    "created_at": _require_str(row.created_at),
                    "fund_id": row.fund_id,
                }
            )
        return loaded
    finally:
        session.close()


def _ledger_for_order(
    ledger: list[dict[str, object]], order_id: int
) -> list[dict[str, object]]:
    rows = [entry for entry in ledger if entry["order_id"] == order_id]
    rows.sort(key=lambda entry: _require_int(entry["id"]))
    ids = [_require_int(entry["id"]) for entry in rows]
    assert ids == sorted(set(ids))
    return rows


def _amounts_by_type(rows: list[dict[str, object]]) -> dict[str, int]:
    amounts: dict[str, int] = {}
    for row in rows:
        entry_type = _require_str(row["entry_type"])
        assert entry_type not in amounts
        amounts[entry_type] = _require_int(row["amount_cents"])
    return amounts


def _paid_order_ids(application: FastAPI, provider_id: int) -> set[int]:
    return {
        _require_int(order["id"])
        for order in _orders_for(application, provider_id, "paid")
    }


def _paid_ledger_sums(application: FastAPI, provider_id: int) -> dict[str, int]:
    """Sums for paid orders only. cerbo_cogs is read and then left out of the headlines."""
    paid_ids = _paid_order_ids(application, provider_id)
    sums = {entry_type: 0 for entry_type in _HEADLINE_TYPES}
    cogs_cents = 0
    for entry in _ledger(application):
        if entry["order_id"] not in paid_ids:
            continue
        entry_type = _require_str(entry["entry_type"])
        amount_cents = _require_int(entry["amount_cents"])
        if entry_type == "cerbo_cogs":
            cogs_cents += amount_cents
            continue
        assert entry_type in sums
        sums[entry_type] += amount_cents
    sums["cerbo_cogs"] = cogs_cents
    return sums


def _stored_lines(order: dict[str, object]) -> list[dict[str, object]]:
    return [_require_dict(line) for line in _require_list(order["lines"])]


def _index_lines(lines: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    indexed: dict[int, dict[str, object]] = {}
    for line in lines:
        product_id = _require_int(line["product_id"])
        assert product_id not in indexed
        indexed[product_id] = line
    return indexed


def _expected_units(
    paid_orders: list[dict[str, object]],
) -> list[tuple[int, str, int]]:
    qty_by_product: dict[int, int] = {}
    name_by_product: dict[int, str] = {}
    for order in paid_orders:
        for line in _stored_lines(order):
            product_id = _require_int(line["product_id"])
            product_name = _require_str(line["product_name"])
            qty = _require_int(line["qty"])
            if product_id in name_by_product:
                assert name_by_product[product_id] == product_name
            else:
                name_by_product[product_id] = product_name
            qty_by_product[product_id] = qty_by_product.get(product_id, 0) + qty
    units: list[tuple[int, str, int]] = []
    for product_id in sorted(qty_by_product):
        units.append((product_id, name_by_product[product_id], qty_by_product[product_id]))
    return units


def _product_name(application: FastAPI, product_id: int) -> str:
    session: Session = application.state.session_factory()
    try:
        product = session.get(Product, product_id)
        assert product is not None
        return _require_str(product.name)
    finally:
        session.close()


def _product_cogs(application: FastAPI, product_id: int) -> int:
    session: Session = application.state.session_factory()
    try:
        product = session.get(Product, product_id)
        assert product is not None
        return _require_int(product.unit_cogs_cents)
    finally:
        session.close()


def _insert_user(application: FastAPI, name: str, role: str) -> None:
    session: Session = application.state.session_factory()
    try:
        session.add(User(name=name, role=role))
        session.commit()
    finally:
        session.close()


def _rename_user(application: FastAPI, user_id: int, name: str) -> None:
    session: Session = application.state.session_factory()
    try:
        user = session.get(User, user_id)
        assert user is not None
        user.name = name
        session.commit()
    finally:
        session.close()


def _set_product_name_and_cogs(
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


def _shift_stored_fee(application: FastAPI, order_id: int) -> tuple[int, int]:
    # fee + 1 and payout - 1 keeps subtotal = cogs + fee + donation + payout.
    session: Session = application.state.session_factory()
    try:
        order = session.get(Order, order_id)
        assert order is not None
        fee = _require_int(order.platform_fee_cents)
        payout = _require_int(order.provider_payout_cents)
        assert payout >= 1
        order.platform_fee_cents = fee + 1
        order.provider_payout_cents = payout - 1
        session.commit()
        assert _require_int(order.subtotal_cents) == (
            _require_int(order.cogs_total_cents)
            + _require_int(order.platform_fee_cents)
            + _require_int(order.donation_cents)
            + _require_int(order.provider_payout_cents)
        )
        return fee, payout
    finally:
        session.close()


def _preview(client: TestClient, provider_id: int, lines: list[dict[str, int]]) -> None:
    response = client.post(
        "/orders/preview",
        headers=_headers(provider_id),
        json={"lines": lines},
    )
    assert response.status_code == 200


def _create_order(
    client: TestClient,
    provider_id: int,
    patient_id: int,
    lines: list[dict[str, int]],
) -> dict[str, object]:
    _preview(client, provider_id, lines)
    response = client.post(
        "/orders",
        headers=_headers(provider_id),
        json={"patient_id": patient_id, "lines": lines},
    )
    assert response.status_code == 200
    body = _require_dict(response.json())
    assert _require_int(body["provider_id"]) == provider_id
    assert _require_int(body["patient_id"]) == patient_id
    assert body["status"] == "pending_payment"
    assert body["paid_at"] is None
    assert body["cancelled_at"] is None
    for field in _SPLIT_FIELDS:
        _require_int(body[field])
    return body


def _pay_order(
    client: TestClient,
    order_id: int,
    patient_id: int,
    created: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        f"/orders/{order_id}/pay",
        headers=_headers(patient_id),
        json={"payment_method": "fake_card_ok"},
    )
    assert response.status_code == 200
    body = _require_dict(response.json())
    assert _require_int(body["id"]) == order_id
    assert body["status"] == "paid"
    paid_at = body["paid_at"]
    assert isinstance(paid_at, str)
    assert _TIMESTAMP.fullmatch(paid_at)
    for field in _SPLIT_FIELDS:
        assert _require_int(body[field]) == _require_int(created[field])
    return body


def _cancel_order(
    client: TestClient,
    order_id: int,
    provider_id: int,
    created: dict[str, object],
) -> dict[str, object]:
    response = client.post(f"/orders/{order_id}/cancel", headers=_headers(provider_id))
    assert response.status_code == 200
    body = _require_dict(response.json())
    assert _require_int(body["id"]) == order_id
    assert body["status"] == "cancelled"
    assert isinstance(body["cancelled_at"], str)
    assert body["paid_at"] is None
    for field in _SPLIT_FIELDS:
        assert _require_int(body[field]) == _require_int(created[field])
    return body


def _enable_product(
    client: TestClient, provider_id: int, product_id: int, price_cents: int
) -> None:
    response = client.put(
        f"/provider/products/{product_id}",
        headers=_headers(provider_id),
        json={"enabled": True, "default_price_cents": price_cents},
    )
    assert response.status_code == 200


def _get_dashboard(
    application: FastAPI,
    client: TestClient,
    headers: dict[str, str] | None,
):
    before = _row_counts(application)
    response = client.get("/provider/dashboard", headers=headers)
    assert _row_counts(application) == before
    return response


def _get_audit(
    application: FastAPI,
    client: TestClient,
    order_id: object,
    headers: dict[str, str] | None,
):
    before = _row_counts(application)
    response = client.get(f"/orders/{order_id}/audit", headers=headers)
    assert _row_counts(application) == before
    return response


def _assert_paid_order_item(
    item: dict[str, object],
    stored: dict[str, object],
    names: dict[int, str],
    ledger: list[dict[str, object]],
    *,
    columns_match_ledger: bool,
) -> None:
    assert set(item) == _PAID_ORDER_KEYS
    order_id = _require_int(stored["id"])
    assert _require_int(item["id"]) == order_id
    paid_at = stored["paid_at"]
    assert isinstance(paid_at, str)
    assert item["paid_at"] == paid_at
    assert _TIMESTAMP.fullmatch(paid_at)
    patient_id = _require_int(stored["patient_id"])
    assert _require_int(item["patient_id"]) == patient_id
    assert item["patient_name"] == names[patient_id]
    subtotal_cents = _require_int(item["subtotal_cents"])
    platform_fee_cents = _require_int(item["platform_fee_cents"])
    donation_cents = _require_int(item["donation_cents"])
    provider_payout_cents = _require_int(item["provider_payout_cents"])
    assert subtotal_cents == _require_int(stored["subtotal_cents"])
    assert platform_fee_cents == _require_int(stored["platform_fee_cents"])
    assert donation_cents == _require_int(stored["donation_cents"])
    assert provider_payout_cents == _require_int(stored["provider_payout_cents"])
    assert item["audit_link"] == f"/orders/{order_id}/audit"
    amounts = _amounts_by_type(_ledger_for_order(ledger, order_id))
    assert set(amounts) == set(_LEDGER_TYPES)
    assert subtotal_cents == amounts["patient_payment"]
    if columns_match_ledger:
        assert platform_fee_cents == amounts["cerbo_fee"]
        assert provider_payout_cents == amounts["provider_payable"]
    else:
        assert platform_fee_cents != amounts["cerbo_fee"]
        assert provider_payout_cents != amounts["provider_payable"]


def _assert_pending_item(
    item: dict[str, object],
    stored: dict[str, object],
    names: dict[int, str],
) -> None:
    assert set(item) == _PENDING_KEYS
    assert _require_int(item["id"]) == _require_int(stored["id"])
    created_at = stored["created_at"]
    assert isinstance(created_at, str)
    assert item["created_at"] == created_at
    assert _TIMESTAMP.fullmatch(created_at)
    patient_id = _require_int(stored["patient_id"])
    assert _require_int(item["patient_id"]) == patient_id
    assert item["patient_name"] == names[patient_id]


def _assert_dashboard(
    body: dict[str, object],
    application: FastAPI,
    provider_id: int,
    names: dict[int, str],
    *,
    columns_match_ledger: bool = True,
) -> None:
    assert set(body) == _DASHBOARD_KEYS
    gmv_cents = _require_int(body["gmv_cents"])
    platform_fee_cents = _require_int(body["platform_fee_cents"])
    donation_cents = _require_int(body["donation_cents"])
    earnings_cents = _require_int(body["earnings_cents"])
    sums = _paid_ledger_sums(application, provider_id)
    assert gmv_cents == sums["patient_payment"]
    assert platform_fee_cents == sums["cerbo_fee"]
    assert donation_cents == sums["research_donation"]
    assert earnings_cents == sums["provider_payable"]

    paid_stored = _orders_for(application, provider_id, "paid")
    pending_stored = _orders_for(application, provider_id, "pending_payment")
    cancelled_stored = _orders_for(application, provider_id, "cancelled")
    paid = [_require_dict(item) for item in _require_list(body["paid_orders"])]
    units = [_require_dict(item) for item in _require_list(body["units_sold"])]
    pending = [_require_dict(item) for item in _require_list(body["pending_orders"])]
    assert [_require_int(item["id"]) for item in paid] == [
        _require_int(order["id"]) for order in paid_stored
    ]
    assert [_require_int(item["id"]) for item in pending] == [
        _require_int(order["id"]) for order in pending_stored
    ]
    visible_ids = {_require_int(item["id"]) for item in paid + pending}
    cancelled_ids = {_require_int(order["id"]) for order in cancelled_stored}
    assert cancelled_ids.isdisjoint(visible_ids)

    if paid_stored:
        paid_subtotal = sum(_require_int(order["subtotal_cents"]) for order in paid_stored)
        unpaid_subtotal = sum(
            _require_int(order["subtotal_cents"])
            for order in pending_stored + cancelled_stored
        )
        all_entry_amounts = sums["patient_payment"] + sums["cerbo_cogs"]
        all_entry_amounts += sums["cerbo_fee"] + sums["provider_payable"]
        assert gmv_cents == paid_subtotal
        assert gmv_cents != all_entry_amounts
        if unpaid_subtotal:
            assert gmv_cents != paid_subtotal + unpaid_subtotal

    ledger = _ledger(application)
    for item, stored in zip(paid, paid_stored, strict=True):
        _assert_paid_order_item(
            item,
            stored,
            names,
            ledger,
            columns_match_ledger=columns_match_ledger,
        )

    expected_units = _expected_units(paid_stored)
    assert [_require_int(item["product_id"]) for item in units] == [
        product_id for product_id, _name, _qty in expected_units
    ]
    for item, (product_id, product_name, qty) in zip(units, expected_units, strict=True):
        assert set(item) == _UNIT_KEYS
        assert _require_int(item["product_id"]) == product_id
        assert item["product_name"] == product_name
        assert _require_int(item["qty"]) == qty
        assert qty >= 1

    for item, stored in zip(pending, pending_stored, strict=True):
        _assert_pending_item(item, stored, names)


def _assert_audit(
    body: dict[str, object],
    stored: dict[str, object],
    ledger: list[dict[str, object]],
    *,
    columns_match_ledger: bool = True,
) -> None:
    assert set(body) == _AUDIT_KEYS
    order_id = _require_int(stored["id"])
    assert _require_int(body["id"]) == order_id
    assert body["status"] == stored["status"]
    assert body["payment_ref"] == stored["payment_ref"]
    assert body["paid_at"] == stored["paid_at"]
    for field in _SPLIT_FIELDS:
        assert _require_int(body[field]) == _require_int(stored[field])
    subtotal_cents = _require_int(stored["subtotal_cents"])
    fee_bps = _require_int(stored["fee_bps"])
    stored_fee = _require_int(stored["platform_fee_cents"])
    matches = stored_fee == compute_fee(subtotal_cents, fee_bps)
    assert isinstance(body["recomputed_fee_matches"], bool)
    assert body["recomputed_fee_matches"] is matches
    cogs_total_cents = _require_int(stored["cogs_total_cents"])
    donation_cents = _require_int(stored["donation_cents"])
    payout_cents = _require_int(stored["provider_payout_cents"])
    split_adds_up = (
        subtotal_cents == cogs_total_cents + stored_fee + donation_cents + payout_cents
    )
    assert isinstance(body["split_adds_up"], bool)
    assert body["split_adds_up"] is split_adds_up
    assert isinstance(body["donation_matches_rate"], bool)
    assert body["donation_matches_rate"] is True

    response_lines = [_require_dict(line) for line in _require_list(body["lines"])]
    stored_by_product = _index_lines(_stored_lines(stored))
    response_by_product = _index_lines(response_lines)
    assert set(response_by_product) == set(stored_by_product)
    for product_id, stored_line in stored_by_product.items():
        line = response_by_product[product_id]
        assert set(line) == _LINE_KEYS
        qty = _require_int(line["qty"])
        unit_price_cents = _require_int(line["unit_price_cents"])
        unit_cogs_cents = _require_int(line["unit_cogs_cents"])
        assert qty == _require_int(stored_line["qty"])
        assert unit_price_cents == _require_int(stored_line["unit_price_cents"])
        assert unit_cogs_cents == _require_int(stored_line["unit_cogs_cents"])
        assert line["product_name"] == stored_line["product_name"]
        assert _require_int(line["line_total_cents"]) == unit_price_cents * qty
        assert _require_int(line["line_cogs_cents"]) == unit_cogs_cents * qty
        margin = unit_price_cents * qty - unit_cogs_cents * qty
        assert _require_int(line["line_margin_cents"]) == margin
        assert _require_int(line["donation_cents"]) == _require_int(
            stored_line["donation_cents"]
        )
        assert line["fund_id"] == stored_line["fund_id"]
        assert line["fund_name"] == stored_line["fund_name"]
        assert line["fund_url"] == stored_line["fund_url"]

    stored_ledger = _ledger_for_order(ledger, order_id)
    response_ledger = [_require_dict(entry) for entry in _require_list(body["ledger"])]
    assert len(response_ledger) == len(stored_ledger)
    for response_entry, stored_entry in zip(response_ledger, stored_ledger, strict=True):
        assert set(response_entry) == _LEDGER_KEYS
        assert response_entry["entry_type"] == stored_entry["entry_type"]
        assert _require_int(response_entry["amount_cents"]) == _require_int(
            stored_entry["amount_cents"]
        )
        assert response_entry["created_at"] == stored_entry["created_at"]
        assert response_entry["fund_id"] == stored_entry["fund_id"]

    if stored["status"] == "paid":
        paid_at = stored["paid_at"]
        assert isinstance(paid_at, str)
        amounts = _amounts_by_type(response_ledger)
        assert set(amounts) == set(_LEDGER_TYPES)
        for entry in response_ledger:
            assert entry["created_at"] == paid_at
        assert amounts["patient_payment"] == subtotal_cents
        assert amounts["cerbo_cogs"] == cogs_total_cents
        if columns_match_ledger:
            assert amounts["cerbo_fee"] == stored_fee
            assert amounts["provider_payable"] == payout_cents
        else:
            assert amounts["cerbo_fee"] != stored_fee
            assert amounts["provider_payable"] != payout_cents
        ledger_matches = (
            set(amounts) == set(_LEDGER_TYPES)
            and amounts["patient_payment"] == subtotal_cents
            and amounts["cerbo_cogs"] == cogs_total_cents
            and amounts["cerbo_fee"] == stored_fee
            and amounts["provider_payable"] == payout_cents
        )
        assert isinstance(body["ledger_matches_split"], bool)
        assert body["ledger_matches_split"] is ledger_matches
        return

    assert stored["status"] in ("pending_payment", "cancelled")
    assert response_ledger == []
    assert stored_ledger == []
    assert matches is True
    assert body["recomputed_fee_matches"] is True
    assert split_adds_up is True
    assert body["split_adds_up"] is True
    assert isinstance(body["ledger_matches_split"], bool)
    assert body["ledger_matches_split"] is True


def _assert_split_ignores_live_cogs(
    application: FastAPI,
    body: dict[str, object],
    stored: dict[str, object],
) -> None:
    inputs: list[LineInput] = []
    for line in _stored_lines(stored):
        product_id = _require_int(line["product_id"])
        inputs.append(
            LineInput(
                product_id=product_id,
                qty=_require_int(line["qty"]),
                unit_price_cents=_require_int(line["unit_price_cents"]),
                unit_cogs_cents=_product_cogs(application, product_id),
            )
        )
    live = compute_split(inputs, _require_int(stored["fee_bps"]))
    assert _require_int(body["cogs_total_cents"]) == _require_int(stored["cogs_total_cents"])
    assert _require_int(body["provider_payout_cents"]) == _require_int(
        stored["provider_payout_cents"]
    )
    assert _require_int(body["cogs_total_cents"]) != live.cogs_total_cents
    assert _require_int(body["provider_payout_cents"]) != live.provider_payout_cents
    assert _require_int(body["platform_fee_cents"]) == live.platform_fee_cents


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


def test_a_provider_with_no_orders_gets_an_empty_dashboard(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, _catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        empty = _get_dashboard(application, client, _headers(provider_id))
        assert empty.status_code == 200
        _assert_dashboard(
            _require_dict(empty.json()),
            application,
            provider_id,
            _names_by_id(client),
        )

        _insert_user(application, "Dr. Alex Kim", "provider")
        alex_id = _user_id(client, "Dr. Alex Kim")
        assert [user for user in _users(client) if user["name"] == "Dr. Alex Kim"][0]["role"] == (
            "provider"
        )
        alex = _get_dashboard(application, client, _headers(alex_id))
        assert alex.status_code == 200
        _assert_dashboard(
            _require_dict(alex.json()),
            application,
            alex_id,
            _names_by_id(client),
        )
        patel_again = _get_dashboard(application, client, _headers(provider_id))
        assert patel_again.status_code == 200
        assert patel_again.json() == empty.json()


def test_dashboard_and_audit_count_only_this_providers_paid_orders(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        mag_id = _product_id(catalog, "MAG-GLY")
        d3_id = _product_id(catalog, "D3-K2")
        omega_id = _product_id(catalog, "OMEGA3")
        probio_id = _product_id(catalog, "PROBIO50")
        mag_name = _require_str(_catalog_row(catalog, "MAG-GLY")["name"])
        mag_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        d3_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
        omega_price = _catalog_int(catalog, "OMEGA3", "suggested_price_cents")
        probio_price = _catalog_int(catalog, "PROBIO50", "suggested_price_cents")

        jane_created = _create_order(
            client,
            provider_id,
            jane_id,
            [
                _request_line(mag_id, 2, mag_price),
                _request_line(d3_id, 1, d3_price),
            ],
        )
        jane_paid = _pay_order(client, _require_int(jane_created["id"]), jane_id, jane_created)
        sam_created = _create_order(
            client,
            provider_id,
            sam_id,
            [
                _request_line(mag_id, 1, mag_price),
                _request_line(omega_id, 1, omega_price),
            ],
        )
        sam_paid = _pay_order(client, _require_int(sam_created["id"]), sam_id, sam_created)
        pending_created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(probio_id, 1, probio_price)],
        )
        cancelled_created = _create_order(
            client,
            provider_id,
            sam_id,
            [_request_line(d3_id, 1, d3_price)],
        )
        cancelled = _cancel_order(
            client,
            _require_int(cancelled_created["id"]),
            provider_id,
            cancelled_created,
        )
        jane_order_id = _require_int(jane_paid["id"])
        sam_order_id = _require_int(sam_paid["id"])
        pending_order_id = _require_int(pending_created["id"])
        cancelled_order_id = _require_int(cancelled["id"])

        _rename_user(application, jane_id, _RENAMED_PATIENT)
        _set_product_name_and_cogs(application, mag_id, _RENAMED_PRODUCT, _RAISED_COGS_CENTS)
        assert _names_by_id(client)[jane_id] == _RENAMED_PATIENT
        assert _product_name(application, mag_id) == _RENAMED_PRODUCT
        assert _product_cogs(application, mag_id) == _RAISED_COGS_CENTS
        assert mag_name != _RENAMED_PRODUCT

        dashboard = _get_dashboard(application, client, _headers(provider_id))
        assert dashboard.status_code == 200
        body = _require_dict(dashboard.json())
        names = _names_by_id(client)
        _assert_dashboard(body, application, provider_id, names)

        paid = [_require_dict(item) for item in _require_list(body["paid_orders"])]
        units = [_require_dict(item) for item in _require_list(body["units_sold"])]
        pending = [_require_dict(item) for item in _require_list(body["pending_orders"])]
        assert [_require_int(item["id"]) for item in paid] == [jane_order_id, sam_order_id]
        assert [_require_int(item["id"]) for item in pending] == [pending_order_id]
        assert cancelled_order_id not in {_require_int(item["id"]) for item in paid + pending}
        paid_by_id = {_require_int(item["id"]): item for item in paid}
        assert paid_by_id[jane_order_id]["patient_name"] == _RENAMED_PATIENT
        assert paid_by_id[jane_order_id]["patient_name"] == names[jane_id]
        assert paid_by_id[sam_order_id]["patient_name"] == "Sam Lee"
        assert _require_dict(pending[0])["patient_name"] == _RENAMED_PATIENT
        assert _require_dict(pending[0])["created_at"] == pending_created["created_at"]

        units_by_product = {_require_int(item["product_id"]): item for item in units}
        assert list(units_by_product) == [mag_id, d3_id, omega_id]
        assert probio_id not in units_by_product
        assert _require_int(units_by_product[mag_id]["qty"]) == 3
        assert _require_int(units_by_product[d3_id]["qty"]) == 1
        assert _require_int(units_by_product[omega_id]["qty"]) == 1
        assert units_by_product[mag_id]["product_name"] == mag_name
        assert units_by_product[mag_id]["product_name"] != _product_name(application, mag_id)

        gmv_cents = _require_int(body["gmv_cents"])
        platform_fee_cents = _require_int(body["platform_fee_cents"])
        earnings_cents = _require_int(body["earnings_cents"])
        paid_subtotal = _require_int(jane_paid["subtotal_cents"]) + _require_int(
            sam_paid["subtotal_cents"]
        )
        paid_fee = _require_int(jane_paid["platform_fee_cents"]) + _require_int(
            sam_paid["platform_fee_cents"]
        )
        paid_payout = _require_int(jane_paid["provider_payout_cents"]) + _require_int(
            sam_paid["provider_payout_cents"]
        )
        unpaid_subtotal = _require_int(pending_created["subtotal_cents"]) + _require_int(
            cancelled["subtotal_cents"]
        )
        assert unpaid_subtotal > 0
        assert gmv_cents == paid_subtotal
        assert gmv_cents != paid_subtotal + unpaid_subtotal
        assert platform_fee_cents == paid_fee
        assert earnings_cents == paid_payout
        assert platform_fee_cents != paid_fee + _require_int(pending_created["platform_fee_cents"])
        assert earnings_cents != paid_payout + _require_int(
            cancelled["provider_payout_cents"]
        )

        ledger = _ledger(application)
        for paid_body, stored_status in (
            (jane_paid, "paid"),
            (sam_paid, "paid"),
            (pending_created, "pending_payment"),
            (cancelled, "cancelled"),
        ):
            order_id = _require_int(paid_body["id"])
            stored = _load_order(application, order_id)
            assert stored["status"] == stored_status
            audit = _get_audit(application, client, order_id, _headers(provider_id))
            assert audit.status_code == 200
            audit_body = _require_dict(audit.json())
            _assert_audit(audit_body, stored, ledger)
            if order_id == jane_order_id:
                _assert_split_ignores_live_cogs(application, audit_body, stored)
                mag_line = _index_lines(
                    [_require_dict(line) for line in _require_list(audit_body["lines"])]
                )[mag_id]
                assert _require_int(mag_line["unit_cogs_cents"]) != _product_cogs(
                    application, mag_id
                )
                assert mag_line["product_name"] == mag_name

        reread = _get_dashboard(application, client, _headers(provider_id))
        assert reread.status_code == 200
        assert reread.json() == body

        _insert_user(application, "Dr. Alex Kim", "provider")
        alex_id = _user_id(client, "Dr. Alex Kim")
        assert [user for user in _users(client) if user["name"] == "Dr. Alex Kim"][0]["role"] == (
            "provider"
        )
        _enable_product(client, alex_id, d3_id, d3_price)
        alex_created = _create_order(
            client,
            alex_id,
            sam_id,
            [_request_line(d3_id, 2, d3_price)],
        )
        alex_paid = _pay_order(client, _require_int(alex_created["id"]), sam_id, alex_created)
        alex_order_id = _require_int(alex_paid["id"])

        patel_after = _get_dashboard(application, client, _headers(provider_id))
        assert patel_after.status_code == 200
        assert patel_after.json() == body
        alex_dashboard = _get_dashboard(application, client, _headers(alex_id))
        assert alex_dashboard.status_code == 200
        alex_body = _require_dict(alex_dashboard.json())
        _assert_dashboard(alex_body, application, alex_id, _names_by_id(client))
        alex_paid_rows = [
            _require_dict(item) for item in _require_list(alex_body["paid_orders"])
        ]
        alex_units = [_require_dict(item) for item in _require_list(alex_body["units_sold"])]
        assert [_require_int(item["id"]) for item in alex_paid_rows] == [alex_order_id]
        assert alex_order_id not in {_require_int(item["id"]) for item in paid}
        assert [_require_int(item["id"]) for item in paid] == [jane_order_id, sam_order_id]
        assert alex_body["pending_orders"] == []
        assert len(alex_units) == 1
        assert _require_int(alex_units[0]["product_id"]) == d3_id
        assert _require_int(alex_units[0]["qty"]) == 2
        assert _require_int(alex_body["gmv_cents"]) == _require_int(alex_paid["subtotal_cents"])
        assert _require_int(alex_body["gmv_cents"]) != gmv_cents

        hidden_from_patel = _get_audit(
            application, client, alex_order_id, _headers(provider_id)
        )
        assert hidden_from_patel.status_code == 404
        assert hidden_from_patel.json() == _NOT_FOUND
        hidden_from_alex = _get_audit(application, client, jane_order_id, _headers(alex_id))
        assert hidden_from_alex.status_code == 404
        assert hidden_from_alex.json() == _NOT_FOUND


def test_audit_flags_are_true_for_a_paid_order_and_an_unpaid_order(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        mag_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(mag_id, 1, price)],
        )
        unpaid = _get_audit(
            application, client, _require_int(created["id"]), _headers(provider_id)
        )
        assert unpaid.status_code == 200
        unpaid_body = _require_dict(unpaid.json())
        assert unpaid_body["status"] == "pending_payment"
        assert unpaid_body["ledger"] == []
        assert unpaid_body["recomputed_fee_matches"] is True
        assert unpaid_body["donation_matches_rate"] is True
        assert unpaid_body["split_adds_up"] is True
        assert unpaid_body["ledger_matches_split"] is True
        subtotal_cents = _require_int(unpaid_body["subtotal_cents"])
        assert subtotal_cents == (
            _require_int(unpaid_body["cogs_total_cents"])
            + _require_int(unpaid_body["platform_fee_cents"])
            + _require_int(unpaid_body["donation_cents"])
            + _require_int(unpaid_body["provider_payout_cents"])
        )

        paid = _pay_order(client, _require_int(created["id"]), jane_id, created)
        audit = _get_audit(
            application, client, _require_int(paid["id"]), _headers(provider_id)
        )
        assert audit.status_code == 200
        body = _require_dict(audit.json())
        assert body["status"] == "paid"
        assert body["recomputed_fee_matches"] is True
        assert body["donation_matches_rate"] is True
        assert body["split_adds_up"] is True
        assert body["ledger_matches_split"] is True
        amounts = _amounts_by_type(
            [_require_dict(entry) for entry in _require_list(body["ledger"])]
        )
        assert set(amounts) == set(_LEDGER_TYPES)
        assert amounts["patient_payment"] == _require_int(body["subtotal_cents"])
        assert amounts["cerbo_cogs"] == _require_int(body["cogs_total_cents"])
        assert amounts["cerbo_fee"] == _require_int(body["platform_fee_cents"])
        assert amounts["provider_payable"] == _require_int(body["provider_payout_cents"])


def test_recomputed_fee_matches_is_false_when_the_stored_fee_changes(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        mag_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(mag_id, 1, price)],
        )
        paid = _pay_order(client, _require_int(created["id"]), jane_id, created)
        order_id = _require_int(paid["id"])
        before_ledger = _ledger(application)
        before_counts = _row_counts(application)
        original_fee, original_payout = _shift_stored_fee(application, order_id)
        after_update = _row_counts(application)
        assert after_update == before_counts
        assert _ledger(application) == before_ledger

        audit = _get_audit(application, client, order_id, _headers(provider_id))
        assert _row_counts(application) == after_update
        assert audit.status_code == 200
        stored = _load_order(application, order_id)
        assert _require_int(stored["platform_fee_cents"]) == original_fee + 1
        assert _require_int(stored["provider_payout_cents"]) == original_payout - 1
        body = _require_dict(audit.json())
        ledger = _ledger(application)
        assert ledger == before_ledger
        _assert_audit(body, stored, ledger, columns_match_ledger=False)
        assert body["recomputed_fee_matches"] is False
        subtotal_cents = _require_int(body["subtotal_cents"])
        fee_bps = _require_int(body["fee_bps"])
        assert compute_fee(subtotal_cents, fee_bps) == original_fee
        assert _require_int(body["platform_fee_cents"]) == original_fee + 1
        assert _require_int(body["provider_payout_cents"]) == original_payout - 1
        assert _require_int(body["subtotal_cents"]) == _require_int(paid["subtotal_cents"])
        assert _require_int(body["cogs_total_cents"]) == _require_int(paid["cogs_total_cents"])
        assert fee_bps == _require_int(paid["fee_bps"])
        amounts = _amounts_by_type(_ledger_for_order(ledger, order_id))
        assert amounts["cerbo_fee"] == original_fee
        assert amounts["provider_payable"] == original_payout
        assert amounts["patient_payment"] == subtotal_cents

        dashboard = _get_dashboard(application, client, _headers(provider_id))
        assert _row_counts(application) == after_update
        assert dashboard.status_code == 200
        dash_body = _require_dict(dashboard.json())
        _assert_dashboard(
            dash_body,
            application,
            provider_id,
            _names_by_id(client),
            columns_match_ledger=False,
        )
        assert _require_int(dash_body["platform_fee_cents"]) == original_fee
        assert _require_int(dash_body["earnings_cents"]) == original_payout
        assert _require_int(dash_body["gmv_cents"]) == subtotal_cents
        dash_row = _require_dict(_require_list(dash_body["paid_orders"])[0])
        assert _require_int(dash_row["platform_fee_cents"]) == original_fee + 1
        assert _require_int(dash_row["provider_payout_cents"]) == original_payout - 1
        assert _require_int(dash_body["platform_fee_cents"]) != _require_int(
            dash_row["platform_fee_cents"]
        )
        assert _require_int(dash_body["earnings_cents"]) != _require_int(
            dash_row["provider_payout_cents"]
        )
        assert _ledger(application) == before_ledger


@pytest.mark.parametrize("name", ("Jane Doe", "Cerbo Admin"))
def test_patient_and_admin_cannot_read_the_dashboard_or_an_order_audit(
    tmp_path: Path,
    name: str,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        mag_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(mag_id, 1, price)],
        )
        paid = _pay_order(client, _require_int(created["id"]), jane_id, created)
        order_id = _require_int(paid["id"])
        assert _require_int(paid["patient_id"]) == jane_id
        caller_id = _user_id(client, name)
        if name == "Jane Doe":
            assert caller_id == jane_id

        dashboard = _get_dashboard(application, client, _headers(caller_id))
        assert dashboard.status_code == 403
        assert dashboard.status_code != 404
        assert dashboard.json() == _FORBIDDEN
        audit = _get_audit(application, client, order_id, _headers(caller_id))
        assert audit.status_code == 403
        assert audit.status_code != 404
        assert audit.json() == _FORBIDDEN


@pytest.mark.parametrize(
    "headers",
    (None, {"X-User-Id": "999999"}),
    ids=("missing-user", "unknown-user"),
)
def test_missing_or_unknown_user_cannot_read_the_dashboard_or_an_audit(
    tmp_path: Path,
    headers: dict[str, str] | None,
) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        mag_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(mag_id, 1, price)],
        )
        paid = _pay_order(client, _require_int(created["id"]), jane_id, created)
        order_id = _require_int(paid["id"])

        dashboard = _get_dashboard(application, client, headers)
        assert dashboard.status_code == 401
        assert dashboard.json() == _UNAUTHENTICATED
        audit = _get_audit(application, client, order_id, headers)
        assert audit.status_code == 401
        assert audit.json() == _UNAUTHENTICATED


def test_unknown_or_invalid_order_ids_on_audit(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        mag_id = _product_id(catalog, "MAG-GLY")
        d3_id = _product_id(catalog, "D3-K2")
        mag_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        d3_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
        created = _create_order(
            client,
            provider_id,
            jane_id,
            [_request_line(mag_id, 1, mag_price)],
        )
        paid = _pay_order(client, _require_int(created["id"]), jane_id, created)
        to_cancel = _create_order(
            client,
            provider_id,
            sam_id,
            [_request_line(d3_id, 1, d3_price)],
        )
        _cancel_order(client, _require_int(to_cancel["id"]), provider_id, to_cancel)
        assert paid["status"] == "paid"
        cases = (
            (_UNKNOWN_ID, 404, _NOT_FOUND),
            ("abc", 422, _VALIDATION_ERROR),
            (_PAST_SQLITE_INT, 404, _NOT_FOUND),
        )

        for order_id, status, error in cases:
            response = _get_audit(application, client, order_id, _headers(provider_id))
            assert response.status_code != 500
            assert response.status_code == status
            assert response.json() == error

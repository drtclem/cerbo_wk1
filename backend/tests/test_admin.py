import json
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
_PRODUCT_KEYS = {
    "id",
    "sku",
    "name",
    "unit_cogs_cents",
    "suggested_price_cents",
    "stock_qty",
    "default_dosing",
}
_PROVIDER_PRODUCT_KEYS = {
    "product_id",
    "sku",
    "name",
    "enabled",
    "default_price_cents",
    "unit_cogs_cents",
    "stock_qty",
    "default_dosing",
}
_MUTABLE_FIELDS = {"stock_qty", "unit_cogs_cents"}
_ORDER_MONEY = (
    "subtotal_cents",
    "cogs_total_cents",
    "platform_fee_cents",
    "donation_cents",
    "provider_payout_cents",
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
_SEED_COUNTS = {
    "users": 4,
    "products": 4,
    "provider_products": 4,
    "orders": 0,
    "order_lines": 0,
    "ledger_entries": 0,
}
_UNKNOWN_ID = 999_999
_PAST_SQLITE_INT = 9_223_372_036_854_775_808
_RAISED_COGS_CENTS = 2_500
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
_LINE_BELOW_COGS = {
    "error": {
        "code": "LINE_BELOW_COGS",
        "message": "Unit price must be at least the unit cost.",
        "line_index": 0,
    }
}
_INVALID_BODIES: tuple[tuple[str, dict[str, object]], ...] = (
    ("stock-negative", {"stock_qty": -1}),
    ("cogs-zero", {"unit_cogs_cents": 0}),
    ("cogs-negative", {"unit_cogs_cents": -1}),
    ("empty-object", {}),
    ("stock-float", {"stock_qty": 1.0}),
    ("stock-bool", {"stock_qty": True}),
    ("stock-string", {"stock_qty": "50"}),
    ("cogs-float", {"unit_cogs_cents": 1.0}),
    ("cogs-bool", {"unit_cogs_cents": True}),
    ("cogs-string", {"unit_cogs_cents": "50"}),
    ("stock-above-sqlite-max", {"stock_qty": _PAST_SQLITE_INT}),
    ("cogs-above-sqlite-max", {"unit_cogs_cents": _PAST_SQLITE_INT}),
    ("negative-stock-with-cogs", {"stock_qty": -1, "unit_cogs_cents": 1_500}),
    ("stock-with-zero-cogs", {"stock_qty": 10, "unit_cogs_cents": 0}),
)


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
    return create_app(database_url=f"sqlite:///{tmp_path / 'admin.db'}")


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _users(client: TestClient) -> list[dict[str, object]]:
    response = client.get("/users")
    assert response.status_code == 200, response.text
    return [_require_dict(user) for user in _require_list(response.json())]


def _user_id(client: TestClient, name: str) -> int:
    matches = [user for user in _users(client) if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _role(client: TestClient, name: str) -> str:
    matches = [user for user in _users(client) if user["name"] == name]
    assert len(matches) == 1
    role = matches[0]["role"]
    assert isinstance(role, str)
    return role


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


def _product_rows(application: FastAPI) -> list[dict[str, object]]:
    session: Session = application.state.session_factory()
    try:
        products = list(session.scalars(select(Product).order_by(Product.id)))
        rows: list[dict[str, object]] = []
        for product in products:
            sku = product.sku
            name = product.name
            assert isinstance(sku, str)
            assert isinstance(name, str)
            dosing = product.default_dosing
            assert isinstance(dosing, str)
            rows.append(
                {
                    "id": _require_int(product.id),
                    "sku": sku,
                    "name": name,
                    "unit_cogs_cents": _require_int(product.unit_cogs_cents),
                    "suggested_price_cents": _require_int(product.suggested_price_cents),
                    "stock_qty": _require_int(product.stock_qty),
                    "default_dosing": dosing,
                }
            )
        ids = [_require_int(row["id"]) for row in rows]
        assert ids == sorted(set(ids))
        return rows
    finally:
        session.close()


def _provider_links(application: FastAPI) -> list[dict[str, object]]:
    session: Session = application.state.session_factory()
    try:
        links = list(
            session.scalars(
                select(ProviderProduct).order_by(
                    ProviderProduct.provider_id,
                    ProviderProduct.product_id,
                )
            )
        )
        return [
            {
                "provider_id": _require_int(link.provider_id),
                "product_id": _require_int(link.product_id),
                "enabled": _require_int(link.enabled),
                "default_price_cents": _require_int(link.default_price_cents),
            }
            for link in links
        ]
    finally:
        session.close()


def _sku_id(application: FastAPI, sku: str) -> int:
    matches = [row for row in _product_rows(application) if row["sku"] == sku]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _product(application: FastAPI, product_id: int) -> dict[str, object]:
    matches = [row for row in _product_rows(application) if row["id"] == product_id]
    assert len(matches) == 1
    return matches[0]


def _default_price(application: FastAPI, provider_id: int, product_id: int) -> int:
    matches = [
        link
        for link in _provider_links(application)
        if link["provider_id"] == provider_id and link["product_id"] == product_id
    ]
    assert len(matches) == 1
    return _require_int(matches[0]["default_price_cents"])


def _parse_product(value: object) -> dict[str, object]:
    row = _require_dict(value)
    assert set(row) == _PRODUCT_KEYS
    sku = row["sku"]
    name = row["name"]
    assert isinstance(sku, str)
    assert isinstance(name, str)
    dosing = row["default_dosing"]
    assert isinstance(dosing, str)
    return {
        "id": _require_int(row["id"]),
        "sku": sku,
        "name": name,
        "unit_cogs_cents": _require_int(row["unit_cogs_cents"]),
        "suggested_price_cents": _require_int(row["suggested_price_cents"]),
        "stock_qty": _require_int(row["stock_qty"]),
        "default_dosing": dosing,
    }


def _parse_products(payload: object) -> list[dict[str, object]]:
    rows = [_parse_product(row) for row in _require_list(payload)]
    ids = [_require_int(row["id"]) for row in rows]
    assert ids == sorted(set(ids))
    return rows


def _assert_seed_products(rows: list[dict[str, object]]) -> None:
    assert len(rows) == len(_PRODUCTS)
    for row, expected in zip(rows, _PRODUCTS, strict=True):
        sku, name, cogs_cents, suggested_cents, stock_qty, dosing = expected
        assert row["sku"] == sku
        assert row["name"] == name
        assert _require_int(row["unit_cogs_cents"]) == cogs_cents
        assert _require_int(row["suggested_price_cents"]) == suggested_cents
        assert _require_int(row["stock_qty"]) == stock_qty
        assert row["default_dosing"] == dosing


def _assert_provider_api(
    client: TestClient,
    provider_id: int,
    products: list[dict[str, object]],
) -> None:
    response = client.get("/provider/products", headers=_headers(provider_id))
    assert response.status_code == 200, response.text
    rows = [_require_dict(row) for row in _require_list(response.json())]
    assert len(rows) == len(products)
    for row, product in zip(rows, products, strict=True):
        assert set(row) == _PROVIDER_PRODUCT_KEYS
        assert _require_int(row["product_id"]) == _require_int(product["id"])
        assert row["sku"] == product["sku"]
        assert row["name"] == product["name"]
        assert isinstance(row["enabled"], bool)
        assert row["enabled"] is True
        assert _require_int(row["default_price_cents"]) == _require_int(
            product["suggested_price_cents"]
        )
        assert _require_int(row["unit_cogs_cents"]) == _require_int(product["unit_cogs_cents"])
        assert _require_int(row["stock_qty"]) == _require_int(product["stock_qty"])
        assert row["default_dosing"] == product["default_dosing"]


def _assert_seed_state(application: FastAPI, client: TestClient) -> None:
    assert _row_counts(application) == _SEED_COUNTS
    products = _product_rows(application)
    _assert_seed_products(products)
    provider_id = _user_id(client, "Dr. Maya Patel")
    links = _provider_links(application)
    assert len(links) == len(products)
    for link, product in zip(links, products, strict=True):
        assert link["provider_id"] == provider_id
        assert link["product_id"] == product["id"]
        assert link["enabled"] == 1
        assert link["default_price_cents"] == product["suggested_price_cents"]
    _assert_provider_api(client, provider_id, products)


def _assert_no_write(
    application: FastAPI,
    products: list[dict[str, object]],
    links: list[dict[str, object]],
    counts: dict[str, int],
) -> None:
    assert _product_rows(application) == products
    assert _provider_links(application) == links
    assert _row_counts(application) == counts


def _replace_product(
    products: list[dict[str, object]],
    product_id: int,
    changes: dict[str, int],
) -> list[dict[str, object]]:
    assert changes
    assert set(changes) <= _MUTABLE_FIELDS
    updated: list[dict[str, object]] = []
    found = False
    for product in products:
        row = dict(product)
        if _require_int(row["id"]) == product_id:
            found = True
            for key, value in changes.items():
                assert isinstance(value, int) and not isinstance(value, bool)
                row[key] = value
        updated.append(row)
    assert found
    return updated


def _admin_list(client: TestClient, admin_id: int) -> list[dict[str, object]]:
    response = client.get("/admin/products", headers=_headers(admin_id))
    assert response.status_code == 200, response.text
    return _parse_products(response.json())


def _put_product(
    application: FastAPI,
    client: TestClient,
    admin_id: int,
    provider_id: int,
    product_id: int,
    payload: dict[str, int],
) -> dict[str, object]:
    assert payload
    assert set(payload) <= _MUTABLE_FIELDS
    for value in payload.values():
        assert isinstance(value, int) and not isinstance(value, bool)
    before_products = _product_rows(application)
    before_links = _provider_links(application)
    before_counts = _row_counts(application)
    response = client.put(
        f"/admin/products/{product_id}",
        headers=_headers(admin_id),
        json=payload,
    )
    assert response.status_code == 200, response.text
    expected = _replace_product(before_products, product_id, payload)
    body = _parse_product(response.json())
    assert body == next(row for row in expected if row["id"] == product_id)
    assert _product_rows(application) == expected
    assert _provider_links(application) == before_links
    counts = _row_counts(application)
    assert counts == before_counts
    assert counts["orders"] == before_counts["orders"]
    assert counts["order_lines"] == before_counts["order_lines"]
    assert counts["ledger_entries"] == before_counts["ledger_entries"]
    assert _admin_list(client, admin_id) == expected
    _assert_provider_api(client, provider_id, expected)
    assert _default_price(application, provider_id, product_id) == _require_int(
        body["suggested_price_cents"]
    )
    return body


def _order_money(payload: object) -> dict[str, int]:
    body = _require_dict(payload)
    return {field: _require_int(body[field]) for field in _ORDER_MONEY}


def _order_line(payload: object) -> dict[str, object]:
    lines = _require_list(_require_dict(payload)["lines"])
    assert len(lines) == 1
    return _require_dict(lines[0])


def _stored_order(application: FastAPI, order_id: int) -> dict[str, object]:
    session: Session = application.state.session_factory()
    try:
        order = session.get(Order, order_id)
        assert order is not None
        line_rows = list(
            session.scalars(
                select(OrderLine).where(OrderLine.order_id == order_id).order_by(OrderLine.id)
            )
        )
        lines: list[dict[str, object]] = []
        for line in line_rows:
            lines.append(
                {
                    "product_id": _require_int(line.product_id),
                    "qty": _require_int(line.qty),
                    "unit_price_cents": _require_int(line.unit_price_cents),
                    "unit_cogs_cents": _require_int(line.unit_cogs_cents),
                }
            )
        return {
            "subtotal_cents": _require_int(order.subtotal_cents),
            "cogs_total_cents": _require_int(order.cogs_total_cents),
            "platform_fee_cents": _require_int(order.platform_fee_cents),
            "donation_cents": _require_int(order.donation_cents),
            "provider_payout_cents": _require_int(order.provider_payout_cents),
            "lines": lines,
        }
    finally:
        session.close()


def _assert_line_index(payload: object) -> None:
    error = _require_dict(_require_dict(payload)["error"])
    line_index = error["line_index"]
    if line_index is not None:
        _require_int(line_index)


@contextmanager
def _open(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        _assert_seed_users(client)
        _assert_seed_state(application, client)
        yield application, client


def test_admin_lists_seeded_products_in_id_order_without_writing(tmp_path: Path) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        assert _role(client, "Cerbo Admin") == "admin"
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        assert before_counts == _SEED_COUNTS
        assert before_counts["orders"] == 0
        assert before_counts["order_lines"] == 0
        assert before_counts["ledger_entries"] == 0

        listed = _admin_list(client, admin_id)
        ids = [_require_int(row["id"]) for row in listed]
        assert ids == sorted(ids)
        assert [row["sku"] for row in listed] == [product[0] for product in _PRODUCTS]
        _assert_seed_products(listed)
        assert listed == before_products
        catalog = client.get("/products", headers=_headers(admin_id))
        assert catalog.status_code == 200, catalog.text
        assert _parse_products(catalog.json()) == listed
        _assert_no_write(application, before_products, before_links, before_counts)


@pytest.mark.parametrize("name", ("Dr. Maya Patel", "Jane Doe", "Sam Lee"))
def test_provider_and_patient_cannot_list_admin_products(tmp_path: Path, name: str) -> None:
    with _open(tmp_path) as (application, client):
        assert _role(client, name) in {"provider", "patient"}
        user_id = _user_id(client, name)
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.get("/admin/products", headers=_headers(user_id))
        assert (response.status_code, response.json()) == (403, _FORBIDDEN)
        _assert_no_write(application, before_products, before_links, before_counts)


@pytest.mark.parametrize(
    "headers",
    (None, {"X-User-Id": "999999"}),
    ids=("missing-user", "unknown-user"),
)
def test_missing_or_unknown_user_cannot_list_admin_products(
    tmp_path: Path,
    headers: dict[str, str] | None,
) -> None:
    with _open(tmp_path) as (application, client):
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.get("/admin/products", headers=headers)
        assert (response.status_code, response.json()) == (401, _UNAUTHENTICATED)
        _assert_no_write(application, before_products, before_links, before_counts)


def test_admin_can_set_stock_and_cogs_together(tmp_path: Path) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        provider_id = _user_id(client, "Dr. Maya Patel")
        product_id = _sku_id(application, "MAG-GLY")
        payload = {"stock_qty": 17, "unit_cogs_cents": 1_501}
        assert set(payload) == {"stock_qty", "unit_cogs_cents"}
        body = _put_product(
            application,
            client,
            admin_id,
            provider_id,
            product_id,
            payload,
        )
        assert body["sku"] == "MAG-GLY"
        assert body["name"] == "Magnesium Glycinate"
        assert _require_int(body["stock_qty"]) == 17
        assert _require_int(body["unit_cogs_cents"]) == 1_501
        assert _require_int(body["suggested_price_cents"]) == 2_400
        assert _default_price(application, provider_id, product_id) == 2_400


def test_admin_can_set_stock_to_zero_without_changing_unit_cogs(tmp_path: Path) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        provider_id = _user_id(client, "Dr. Maya Patel")
        product_id = _sku_id(application, "MAG-GLY")
        payload = {"stock_qty": 0}
        assert set(payload) == {"stock_qty"}
        assert isinstance(payload["stock_qty"], int) and not isinstance(payload["stock_qty"], bool)
        body = _put_product(
            application,
            client,
            admin_id,
            provider_id,
            product_id,
            payload,
        )
        assert body["sku"] == "MAG-GLY"
        assert body["name"] == "Magnesium Glycinate"
        assert _require_int(body["stock_qty"]) == 0
        assert _require_int(body["unit_cogs_cents"]) == 1_200
        assert _require_int(body["suggested_price_cents"]) == 2_400
        assert _default_price(application, provider_id, product_id) == 2_400


def test_admin_can_set_unit_cogs_without_changing_stock(tmp_path: Path) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        provider_id = _user_id(client, "Dr. Maya Patel")
        product_id = _sku_id(application, "MAG-GLY")
        payload = {"unit_cogs_cents": 1}
        assert set(payload) == {"unit_cogs_cents"}
        body = _put_product(
            application,
            client,
            admin_id,
            provider_id,
            product_id,
            payload,
        )
        assert body["sku"] == "MAG-GLY"
        assert body["name"] == "Magnesium Glycinate"
        assert _require_int(body["unit_cogs_cents"]) == 1
        assert _require_int(body["stock_qty"]) == 50
        assert _require_int(body["suggested_price_cents"]) == 2_400
        assert _default_price(application, provider_id, product_id) == 2_400


@pytest.mark.parametrize("name", ("Dr. Maya Patel", "Jane Doe", "Sam Lee"))
@pytest.mark.parametrize(
    "product_ref",
    ("known", "missing"),
    ids=("known-id", "missing-id"),
)
def test_provider_and_patient_cannot_update_products_even_when_the_id_is_missing(
    tmp_path: Path,
    name: str,
    product_ref: str,
) -> None:
    with _open(tmp_path) as (application, client):
        assert _role(client, name) in {"provider", "patient"}
        user_id = _user_id(client, name)
        product_id = (
            _sku_id(application, "MAG-GLY") if product_ref == "known" else _UNKNOWN_ID
        )
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.put(
            f"/admin/products/{product_id}",
            headers=_headers(user_id),
            json={"stock_qty": 4},
        )
        assert (response.status_code, response.json()) == (403, _FORBIDDEN)
        _assert_no_write(application, before_products, before_links, before_counts)


@pytest.mark.parametrize(
    "headers",
    (None, {"X-User-Id": "999999"}),
    ids=("missing-user", "unknown-user"),
)
@pytest.mark.parametrize(
    "product_ref",
    ("known", "missing"),
    ids=("known-id", "missing-id"),
)
def test_missing_or_unknown_user_cannot_update_a_product(
    tmp_path: Path,
    headers: dict[str, str] | None,
    product_ref: str,
) -> None:
    with _open(tmp_path) as (application, client):
        product_id = (
            _sku_id(application, "MAG-GLY") if product_ref == "known" else _UNKNOWN_ID
        )
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.put(
            f"/admin/products/{product_id}",
            headers=headers,
            json={"unit_cogs_cents": 1_300},
        )
        assert (response.status_code, response.json()) == (401, _UNAUTHENTICATED)
        _assert_no_write(application, before_products, before_links, before_counts)


@pytest.mark.parametrize(
    "payload",
    tuple(body for _name, body in _INVALID_BODIES),
    ids=tuple(name for name, _body in _INVALID_BODIES),
)
def test_invalid_stock_or_cogs_is_rejected_and_leaves_the_product_unchanged(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        product_id = _sku_id(application, "MAG-GLY")
        content = json.dumps(payload)
        if any(isinstance(value, float) for value in payload.values()):
            assert ".0" in content
        if any(value is True for value in payload.values()):
            assert "true" in content
        if any(isinstance(value, str) for value in payload.values()):
            assert '"50"' in content
        if any(value == _PAST_SQLITE_INT for value in payload.values()):
            assert str(_PAST_SQLITE_INT) in content
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.put(
            f"/admin/products/{product_id}",
            headers={**_headers(admin_id), "Content-Type": "application/json"},
            content=content,
        )
        assert response.status_code != 500, response.text
        assert (response.status_code, response.json()) == (422, _VALIDATION_ERROR)
        _assert_line_index(response.json())
        _assert_no_write(application, before_products, before_links, before_counts)
        assert _product(application, product_id)["unit_cogs_cents"] == 1_200
        assert _product(application, product_id)["stock_qty"] == 50


@pytest.mark.parametrize(
    "product_id",
    (_UNKNOWN_ID, _PAST_SQLITE_INT),
    ids=("unknown", "past-sqlite-max"),
)
def test_unknown_product_id_returns_not_found_without_writing(
    tmp_path: Path,
    product_id: int,
) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.put(
            f"/admin/products/{product_id}",
            headers=_headers(admin_id),
            json={"stock_qty": 9, "unit_cogs_cents": 1_300},
        )
        assert response.status_code != 500, response.text
        assert (response.status_code, response.json()) == (404, _NOT_FOUND)
        _assert_no_write(application, before_products, before_links, before_counts)


def test_non_integer_product_id_returns_validation_error(tmp_path: Path) -> None:
    with _open(tmp_path) as (application, client):
        admin_id = _user_id(client, "Cerbo Admin")
        before_products = _product_rows(application)
        before_links = _provider_links(application)
        before_counts = _row_counts(application)
        response = client.put(
            "/admin/products/abc",
            headers=_headers(admin_id),
            json={"stock_qty": 0},
        )
        assert response.status_code != 500, response.text
        assert (response.status_code, response.json()) == (422, _VALIDATION_ERROR)
        _assert_no_write(application, before_products, before_links, before_counts)


def test_raising_catalog_cogs_leaves_the_existing_order_unchanged(tmp_path: Path) -> None:
    with _open(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        admin_id = _user_id(client, "Cerbo Admin")
        assert jane_id != provider_id
        product_id = _sku_id(application, "MAG-GLY")
        original = _product(application, product_id)
        assert original["sku"] == "MAG-GLY"
        assert original["name"] == "Magnesium Glycinate"
        assert _require_int(original["unit_cogs_cents"]) == 1_200
        assert _require_int(original["suggested_price_cents"]) == 2_400
        assert _require_int(original["stock_qty"]) == 50
        assert _default_price(application, provider_id, product_id) == 2_400
        line = {
            "product_id": product_id,
            "qty": 1,
            "unit_price_cents": 2_400,
            "dosing": "Example: 1 capsule daily with a meal",
        }
        assert set(line) == {"product_id", "qty", "unit_price_cents", "dosing"}

        created_response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": [line]},
        )
        assert created_response.status_code == 200, created_response.text
        created = created_response.json()
        created_body = _require_dict(created)
        order_id = _require_int(created_body["id"])
        assert _require_int(created_body["provider_id"]) == provider_id
        assert _require_int(created_body["patient_id"]) == jane_id
        created_line = _order_line(created)
        assert _require_int(created_line["product_id"]) == product_id
        assert _require_int(created_line["qty"]) == 1
        assert _require_int(created_line["unit_price_cents"]) == 2_400
        assert _require_int(created_line["unit_cogs_cents"]) == 1_200
        money = _order_money(created)
        assert money["subtotal_cents"] == 2_400
        assert money["cogs_total_cents"] == 1_200
        stored = _stored_order(application, order_id)
        assert stored["lines"] == [
            {
                "product_id": product_id,
                "qty": 1,
                "unit_price_cents": 2_400,
                "unit_cogs_cents": 1_200,
            }
        ]
        assert stored["subtotal_cents"] == money["subtotal_cents"]
        assert stored["cogs_total_cents"] == money["cogs_total_cents"]
        assert stored["platform_fee_cents"] == money["platform_fee_cents"]
        assert stored["provider_payout_cents"] == money["provider_payout_cents"]
        before_counts = _row_counts(application)
        assert before_counts["orders"] == 1
        assert before_counts["order_lines"] == 1
        assert _require_int(before_counts["ledger_entries"]) == 0
        before_links = _provider_links(application)

        payload = {"unit_cogs_cents": _RAISED_COGS_CENTS}
        assert set(payload) == {"unit_cogs_cents"}
        assert _RAISED_COGS_CENTS > 2_400
        body = _put_product(
            application,
            client,
            admin_id,
            provider_id,
            product_id,
            payload,
        )
        assert body["sku"] == "MAG-GLY"
        assert body["name"] == "Magnesium Glycinate"
        assert _require_int(body["unit_cogs_cents"]) == _RAISED_COGS_CENTS
        assert _require_int(body["stock_qty"]) == 50
        assert _require_int(body["suggested_price_cents"]) == 2_400
        assert _default_price(application, provider_id, product_id) == 2_400
        assert _provider_links(application) == before_links

        fetched = client.get(f"/orders/{order_id}", headers=_headers(provider_id))
        assert fetched.status_code == 200, fetched.text
        assert fetched.json() == created
        fetched_line = _order_line(fetched.json())
        assert _require_int(fetched_line["unit_cogs_cents"]) == 1_200
        assert _order_money(fetched.json()) == money
        assert _stored_order(application, order_id) == stored

        preview = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": [line]},
        )
        assert preview.status_code != 500, preview.text
        assert (preview.status_code, preview.json()) == (422, _LINE_BELOW_COGS)
        _assert_line_index(preview.json())
        created_again = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": [line]},
        )
        assert created_again.status_code != 500, created_again.text
        assert (created_again.status_code, created_again.json()) == (422, _LINE_BELOW_COGS)
        _assert_line_index(created_again.json())

        assert _row_counts(application) == before_counts
        assert _stored_order(application, order_id) == stored
        reread = client.get(f"/orders/{order_id}", headers=_headers(provider_id))
        assert reread.status_code == 200, reread.text
        assert reread.json() == created
        live = _product(application, product_id)
        assert _require_int(live["unit_cogs_cents"]) == _RAISED_COGS_CENTS
        assert _require_int(live["stock_qty"]) == 50
        assert _require_int(live["suggested_price_cents"]) == 2_400
        assert _default_price(application, provider_id, product_id) == 2_400

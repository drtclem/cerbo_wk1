from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.money import (
    FEE_BPS_DEFAULT,
    LineInput,
    PricingError,
    compute_split,
    validate_order,
)
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
_LINE_FIELDS = (
    "product_id",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
    "stock_available",
    "donation_cents",
    "fund_id",
    "fund_name",
    "fund_url",
    "fund_description",
)
_COUNTED_MODELS = (
    ("users", User),
    ("products", Product),
    ("provider_products", ProviderProduct),
    ("orders", Order),
    ("order_lines", OrderLine),
    ("ledger_entries", LedgerEntry),
)
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


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'orders_preview.db'}")


def _user_id(client: TestClient, name: str) -> int:
    response = client.get("/users")
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    matches = [user for user in users if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _load_catalog(client: TestClient, user_id: int) -> list[dict[str, object]]:
    response = client.get("/products", headers=_headers(user_id))
    assert response.status_code == 200
    rows = [_require_dict(row) for row in _require_list(response.json())]
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


def _request_line(product_id: int, qty: int, unit_price_cents: int) -> dict[str, int]:
    return {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
    }


def _order_body(lines: list[dict[str, int]]) -> dict[str, object]:
    return {"lines": lines}


def _raw_preview(product_id: int, qty: str, unit_price_cents: str) -> str:
    return (
        '{"lines":[{"product_id":'
        + str(product_id)
        + ',"qty":'
        + qty
        + ',"unit_price_cents":'
        + unit_price_cents
        + "}]}"
    )


def _preview(
    application: FastAPI,
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    content: str | None = None,
):
    before = _row_counts(application)
    request_headers = {} if headers is None else dict(headers)
    if content is not None:
        request_headers["Content-Type"] = "application/json"
        response = client.post(
            "/orders/preview",
            headers=request_headers,
            content=content,
        )
    else:
        response = client.post("/orders/preview", headers=request_headers, json=body)
    assert _row_counts(application) == before
    return response


def _error(code: str, message: str, line_index: int | None) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "line_index": line_index,
        }
    }


def _money_error(lines: Sequence[LineInput]) -> dict[str, object]:
    with pytest.raises(PricingError) as raised:
        validate_order(lines, FEE_BPS_DEFAULT)
    error = raised.value
    return _error(error.code, error.detail, error.line_index)


def _assert_error(body: object, code: str, message: str, line_index: int | None) -> None:
    assert body == _error(code, message, line_index)
    error = _require_dict(_require_dict(body)["error"])
    if line_index is None:
        assert error["line_index"] is None
    else:
        assert _require_int(error["line_index"]) == line_index


def _assert_pricing_response(
    body: object,
    lines: Sequence[LineInput],
    code: str,
    message: str,
    line_index: int | None,
) -> None:
    assert _money_error(lines) == _error(code, message, line_index)
    _assert_error(body, code, message, line_index)


def _assert_exact_split(body: object, expected: dict[str, object]) -> None:
    parsed = _require_dict(body)
    assert isinstance(parsed["lines"], list)
    assert set(parsed) == {"lines", *_SPLIT_FIELDS}
    assert parsed == expected
    for field in _SPLIT_FIELDS:
        _require_int(parsed[field])
    for line_value in _require_list(parsed["lines"]):
        line = _require_dict(line_value)
        assert set(line) == set(_LINE_FIELDS)
        for field in _LINE_FIELDS:
            _require_int(line[field])


def _disable_product(
    client: TestClient,
    provider_id: int,
    product_id: int,
    default_price_cents: int,
) -> None:
    response = client.put(
        f"/provider/products/{product_id}",
        headers=_headers(provider_id),
        json={"enabled": False, "default_price_cents": default_price_cents},
    )
    assert response.status_code == 200
    body = _require_dict(response.json())
    assert _require_int(body["product_id"]) == product_id
    assert body["enabled"] is False


def _unknown_product_id(catalog: list[dict[str, object]]) -> int:
    missing_id = 999_999
    assert missing_id not in {_require_int(row["id"]) for row in catalog}
    return missing_id


@contextmanager
def _seeded_provider(
    tmp_path: Path,
) -> Iterator[tuple[FastAPI, TestClient, int, list[dict[str, object]]]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        yield application, client, provider_id, catalog


def test_preview_matches_compute_split_for_a_multi_line_order_and_allows_qty_above_stock(
    tmp_path: Path,
) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        listed = client.get("/provider/products", headers=_headers(provider_id))
        assert listed.status_code == 200
        enabled_by_sku: dict[str, object] = {}
        for row_value in _require_list(listed.json()):
            row = _require_dict(row_value)
            sku = row["sku"]
            assert isinstance(sku, str)
            enabled_by_sku[sku] = row["enabled"]
        assert enabled_by_sku["MAG-GLY"] is True
        assert enabled_by_sku["PROBIO50"] is True

        magnesium_id = _product_id(catalog, "MAG-GLY")
        probiotic_id = _product_id(catalog, "PROBIO50")
        magnesium_cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        probiotic_cogs = _catalog_int(catalog, "PROBIO50", "unit_cogs_cents")
        magnesium_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        probiotic_price = _catalog_int(catalog, "PROBIO50", "suggested_price_cents")
        probiotic_stock = _catalog_int(catalog, "PROBIO50", "stock_qty")
        assert magnesium_cogs == 1_200
        assert magnesium_price == 2_400
        assert probiotic_cogs == 2_100
        assert probiotic_price == 4_200
        assert probiotic_stock == 1
        assert 5 > probiotic_stock

        priced = (
            LineInput(
                product_id=magnesium_id,
                qty=2,
                unit_price_cents=magnesium_price,
                unit_cogs_cents=magnesium_cogs,
            ),
            LineInput(
                product_id=probiotic_id,
                qty=5,
                unit_price_cents=probiotic_price,
                unit_cogs_cents=probiotic_cogs,
            ),
        )
        assert FEE_BPS_DEFAULT == 75
        split = compute_split(priced, FEE_BPS_DEFAULT)
        magnesium_stock = _catalog_int(catalog, "MAG-GLY", "stock_qty")

        request_lines = [
            _request_line(magnesium_id, 2, magnesium_price),
            _request_line(probiotic_id, 5, probiotic_price),
        ]
        assert all(set(line) == {"product_id", "qty", "unit_price_cents"} for line in request_lines)
        body = _order_body(request_lines)
        assert set(body) == {"lines"}

        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=body,
        )
        assert response.status_code == 200
        parsed = _require_dict(response.json())
        assert set(parsed) == {"lines", *_SPLIT_FIELDS}
        for field in _SPLIT_FIELDS:
            assert _require_int(parsed[field]) == getattr(split, field)
        response_lines = [_require_dict(line) for line in _require_list(parsed["lines"])]
        assert len(response_lines) == 2
        for response_line, priced_line, stock in zip(
            response_lines,
            split.lines,
            (magnesium_stock, probiotic_stock),
            strict=True,
        ):
            assert set(response_line) == set(_LINE_FIELDS)
            assert _require_int(response_line["product_id"]) == priced_line.product_id
            assert _require_int(response_line["qty"]) == priced_line.qty
            assert _require_int(response_line["unit_price_cents"]) == (
                priced_line.unit_price_cents
            )
            assert _require_int(response_line["unit_cogs_cents"]) == (
                priced_line.unit_cogs_cents
            )
            assert _require_int(response_line["line_total_cents"]) == (
                priced_line.line_total_cents
            )
            assert _require_int(response_line["line_cogs_cents"]) == priced_line.line_cogs_cents
            assert _require_int(response_line["line_margin_cents"]) == (
                priced_line.line_margin_cents
            )
            assert _require_int(response_line["stock_available"]) == stock
            assert _require_int(response_line["donation_cents"]) == priced_line.donation_cents
            assert response_line["fund_id"] is not None
            assert isinstance(response_line["fund_name"], str)
            assert isinstance(response_line["fund_url"], str)
            assert isinstance(response_line["fund_description"], str)
        assert (
            _catalog_int(_load_catalog(client, provider_id), "PROBIO50", "stock_qty")
            == probiotic_stock
        )


def test_empty_lines_return_empty_order(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, _catalog):
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body={"lines": []},
        )
        assert response.status_code == 422
        _assert_pricing_response(
            response.json(),
            (),
            "EMPTY_ORDER",
            "Order must contain at least one line.",
            None,
        )


def test_zero_quantity_returns_validation_error(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        product_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body([_request_line(product_id, 0, price)]),
        )
        assert response.status_code == 422
        assert response.json() == _VALIDATION_ERROR


def test_price_equal_to_cogs_returns_negative_payout(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        product_id = _product_id(catalog, "MAG-GLY")
        cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        assert cogs == 1_200
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body([_request_line(product_id, 1, cogs)]),
        )
        assert response.status_code == 422
        _assert_pricing_response(
            response.json(),
            (
                LineInput(
                    product_id=product_id,
                    qty=1,
                    unit_price_cents=cogs,
                    unit_cogs_cents=cogs,
                ),
            ),
            "NEGATIVE_PAYOUT",
            "Price too low to cover the platform fee.",
            None,
        )


def test_price_below_cogs_returns_line_below_cogs_for_that_line(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        product_id = _product_id(catalog, "MAG-GLY")
        cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        price = cogs - 1
        assert price == 1_199
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body([_request_line(product_id, 1, price)]),
        )
        assert response.status_code == 422
        _assert_pricing_response(
            response.json(),
            (
                LineInput(
                    product_id=product_id,
                    qty=1,
                    unit_price_cents=price,
                    unit_cogs_cents=cogs,
                ),
            ),
            "LINE_BELOW_COGS",
            "Unit price must be at least the unit cost.",
            0,
        )


def test_disabled_product_returns_product_unavailable(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        product_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        _disable_product(client, provider_id, product_id, price)
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body([_request_line(product_id, 1, price)]),
        )
        assert response.status_code == 422
        _assert_error(response.json(), "PRODUCT_UNAVAILABLE", _UNAVAILABLE, 0)


def test_unknown_product_returns_product_unavailable(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        missing_id = _unknown_product_id(catalog)
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body([_request_line(missing_id, 1, 2_400)]),
        )
        assert response.status_code == 422
        _assert_error(response.json(), "PRODUCT_UNAVAILABLE", _UNAVAILABLE, 0)


def test_provider_with_no_product_row_returns_product_unavailable(tmp_path: Path) -> None:
    with _seeded_provider(tmp_path) as (application, client, _provider_id, catalog):
        session: Session = application.state.session_factory()
        try:
            session.add(User(name="Dr. Alex Kim", role="provider"))
            session.commit()
        finally:
            session.close()
        alex_id = _user_id(client, "Dr. Alex Kim")
        listed = client.get("/provider/products", headers=_headers(alex_id))
        assert listed.status_code == 200
        assert listed.json() == []

        product_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        response = _preview(
            application,
            client,
            headers=_headers(alex_id),
            body=_order_body([_request_line(product_id, 1, price)]),
        )
        assert response.status_code == 422
        _assert_error(response.json(), "PRODUCT_UNAVAILABLE", _UNAVAILABLE, 0)


@pytest.mark.parametrize("unavailable", ("disabled", "unknown"))
def test_product_unavailable_reports_the_request_line_index(
    tmp_path: Path,
    unavailable: str,
) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        magnesium_id = _product_id(catalog, "MAG-GLY")
        magnesium_price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        magnesium_cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        valid = validate_order(
            (
                LineInput(
                    product_id=magnesium_id,
                    qty=1,
                    unit_price_cents=magnesium_price,
                    unit_cogs_cents=magnesium_cogs,
                ),
            ),
            FEE_BPS_DEFAULT,
        )
        assert valid.fee_bps == 75
        if unavailable == "disabled":
            second_id = _product_id(catalog, "D3-K2")
            second_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
            _disable_product(client, provider_id, second_id, second_price)
        else:
            second_id = _unknown_product_id(catalog)
            second_price = 1_800
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body(
                [
                    _request_line(magnesium_id, 1, magnesium_price),
                    _request_line(second_id, 1, second_price),
                ]
            ),
        )
        assert response.status_code == 422
        _assert_error(response.json(), "PRODUCT_UNAVAILABLE", _UNAVAILABLE, 1)


@pytest.mark.parametrize("later", ("disabled", "unknown"))
def test_price_below_cogs_on_line_zero_precedes_a_later_unavailable_product(
    tmp_path: Path,
    later: str,
) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        magnesium_id = _product_id(catalog, "MAG-GLY")
        magnesium_cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        below_cogs = magnesium_cogs - 1
        assert below_cogs == 1_199
        if later == "disabled":
            second_id = _product_id(catalog, "D3-K2")
            second_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
            _disable_product(client, provider_id, second_id, second_price)
        else:
            second_id = _unknown_product_id(catalog)
            second_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body(
                [
                    _request_line(magnesium_id, 1, below_cogs),
                    _request_line(second_id, 1, second_price),
                ]
            ),
        )
        assert response.status_code == 422
        _assert_pricing_response(
            response.json(),
            (
                LineInput(
                    product_id=magnesium_id,
                    qty=1,
                    unit_price_cents=below_cogs,
                    unit_cogs_cents=magnesium_cogs,
                ),
            ),
            "LINE_BELOW_COGS",
            "Unit price must be at least the unit cost.",
            0,
        )


@pytest.mark.parametrize("earlier", ("disabled", "unknown"))
def test_unavailable_line_zero_precedes_a_later_price_below_cogs(
    tmp_path: Path,
    earlier: str,
) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        magnesium_id = _product_id(catalog, "MAG-GLY")
        magnesium_cogs = _catalog_int(catalog, "MAG-GLY", "unit_cogs_cents")
        below_cogs = magnesium_cogs - 1
        assert below_cogs == 1_199
        assert _money_error(
            (
                LineInput(
                    product_id=magnesium_id,
                    qty=1,
                    unit_price_cents=below_cogs,
                    unit_cogs_cents=magnesium_cogs,
                ),
            )
        ) == _error(
            "LINE_BELOW_COGS",
            "Unit price must be at least the unit cost.",
            0,
        )
        if earlier == "disabled":
            first_id = _product_id(catalog, "D3-K2")
            first_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
            _disable_product(client, provider_id, first_id, first_price)
        else:
            first_id = _unknown_product_id(catalog)
            first_price = _catalog_int(catalog, "D3-K2", "suggested_price_cents")
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            body=_order_body(
                [
                    _request_line(first_id, 1, first_price),
                    _request_line(magnesium_id, 1, below_cogs),
                ]
            ),
        )
        assert response.status_code == 422
        _assert_error(response.json(), "PRODUCT_UNAVAILABLE", _UNAVAILABLE, 0)


@pytest.mark.parametrize(
    ("qty", "unit_price_cents"),
    (
        ("2.0", "2400"),
        ("true", "2400"),
        ('"2"', "2400"),
        ("2", "2500.0"),
        ("2", "true"),
        ("2", '"2500"'),
    ),
    ids=(
        "qty-float",
        "qty-bool",
        "qty-numeric-string",
        "price-float",
        "price-bool",
        "price-numeric-string",
    ),
)
def test_non_integer_qty_or_unit_price_returns_validation_error(
    tmp_path: Path,
    qty: str,
    unit_price_cents: str,
) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        product_id = _product_id(catalog, "MAG-GLY")
        response = _preview(
            application,
            client,
            headers=_headers(provider_id),
            content=_raw_preview(product_id, qty, unit_price_cents),
        )
        assert response.status_code == 422
        assert response.json() == _VALIDATION_ERROR


@pytest.mark.parametrize("name", ("Jane Doe", "Sam Lee", "Cerbo Admin"))
def test_patient_and_admin_preview_are_forbidden(tmp_path: Path, name: str) -> None:
    with _seeded_provider(tmp_path) as (application, client, provider_id, catalog):
        caller_id = _user_id(client, name)
        assert caller_id != provider_id
        product_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        response = _preview(
            application,
            client,
            headers=_headers(caller_id),
            body=_order_body([_request_line(product_id, 1, price)]),
        )
        assert response.status_code == 403
        assert response.json() == _FORBIDDEN


@pytest.mark.parametrize(
    "headers",
    (None, {"X-User-Id": "999999"}),
    ids=("missing-user", "unknown-user"),
)
def test_missing_or_unknown_user_preview_is_unauthenticated(
    tmp_path: Path,
    headers: dict[str, str] | None,
) -> None:
    with _seeded_provider(tmp_path) as (application, client, _provider_id, catalog):
        product_id = _product_id(catalog, "MAG-GLY")
        price = _catalog_int(catalog, "MAG-GLY", "suggested_price_cents")
        response = _preview(
            application,
            client,
            headers=headers,
            body=_order_body([_request_line(product_id, 1, price)]),
        )
        assert response.status_code == 401
        assert response.json() == _UNAUTHENTICATED

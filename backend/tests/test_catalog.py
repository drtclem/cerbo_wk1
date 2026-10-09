from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import User

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
_NEGATIVE_PAYOUT = {
    "error": {
        "code": "NEGATIVE_PAYOUT",
        "message": "Price too low to cover the platform fee.",
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
_VALIDATION_ERROR = {
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid request",
        "line_index": None,
    }
}
_NON_INTEGER_PRICE = '{"enabled": true, "default_price_cents": 24.5}'


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
    return create_app(database_url=f"sqlite:///{tmp_path / 'catalog.db'}")


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


def _assert_catalog(body: object) -> list[dict[str, object]]:
    rows = _require_list(body)
    assert len(rows) == len(_PRODUCTS)
    parsed: list[dict[str, object]] = []
    ids: list[int] = []
    for row_value, expected in zip(rows, _PRODUCTS, strict=True):
        row = _require_dict(row_value)
        sku, name, cogs_cents, suggested_cents, stock_qty, _dosing = expected
        assert set(row) == _CATALOG_KEYS
        product_id = _require_int(row["id"])
        assert row["sku"] == sku
        assert row["name"] == name
        assert _require_int(row["unit_cogs_cents"]) == cogs_cents
        assert _require_int(row["suggested_price_cents"]) == suggested_cents
        assert _require_int(row["stock_qty"]) == stock_qty
        ids.append(product_id)
        parsed.append(row)
    assert [row["sku"] for row in parsed] == [product[0] for product in _PRODUCTS]
    assert ids == sorted(set(ids))
    return parsed


def _load_catalog(client: TestClient, user_id: int) -> list[dict[str, object]]:
    response = client.get("/products", headers=_headers(user_id))
    assert response.status_code == 200
    return _assert_catalog(response.json())


def _product_id(catalog: list[dict[str, object]], sku: str) -> int:
    matches = [row for row in catalog if row["sku"] == sku]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _assert_provider_product(
    row_value: object,
    *,
    product_id: int,
    sku: str,
    name: str,
    enabled: bool,
    default_price_cents: int,
    unit_cogs_cents: int,
    stock_qty: int,
) -> None:
    row = _require_dict(row_value)
    assert set(row) == _PROVIDER_PRODUCT_KEYS
    assert _require_int(row["product_id"]) == product_id
    assert row["sku"] == sku
    assert row["name"] == name
    assert isinstance(row["enabled"], bool)
    assert row["enabled"] is enabled
    assert _require_int(row["default_price_cents"]) == default_price_cents
    assert _require_int(row["unit_cogs_cents"]) == unit_cogs_cents
    assert _require_int(row["stock_qty"]) == stock_qty


def _assert_provider_rows(
    body: object,
    catalog: list[dict[str, object]],
    enabled_and_price: tuple[tuple[bool, int], ...],
) -> None:
    rows = _require_list(body)
    assert len(rows) == len(catalog) == len(enabled_and_price)
    product_ids: list[int] = []
    for row_value, catalog_row, (enabled, price_cents) in zip(
        rows,
        catalog,
        enabled_and_price,
        strict=True,
    ):
        product_id = _require_int(catalog_row["id"])
        _assert_provider_product(
            row_value,
            product_id=product_id,
            sku=str(catalog_row["sku"]),
            name=str(catalog_row["name"]),
            enabled=enabled,
            default_price_cents=price_cents,
            unit_cogs_cents=_require_int(catalog_row["unit_cogs_cents"]),
            stock_qty=_require_int(catalog_row["stock_qty"]),
        )
        product_ids.append(product_id)
    assert product_ids == sorted(set(product_ids))


def _seeded_provider_state(
    catalog: list[dict[str, object]],
) -> tuple[tuple[bool, int], ...]:
    return tuple((True, _require_int(row["suggested_price_cents"])) for row in catalog)


def _assert_seeded_provider_products(
    body: object,
    catalog: list[dict[str, object]],
) -> None:
    _assert_provider_rows(body, catalog, _seeded_provider_state(catalog))


def _load_provider_products(client: TestClient, user_id: int) -> object:
    response = client.get("/provider/products", headers=_headers(user_id))
    assert response.status_code == 200
    return response.json()


def test_provider_sees_four_seeded_products_with_stock_and_suggested_prices(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        listed = _load_provider_products(client, provider_id)

    _assert_seeded_provider_products(listed, catalog)
    assert [row["sku"] for row in _require_list(listed)] == [
        "MAG-GLY",
        "D3-K2",
        "OMEGA3",
        "PROBIO50",
    ]


def test_patient_cannot_read_or_update_provider_products_and_missing_user_is_unauthenticated(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        patient_id = _user_id(client, "Jane Doe")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        patient_headers = _headers(patient_id)
        body = {"enabled": True, "default_price_cents": 2_500}

        patient_get = client.get("/provider/products", headers=patient_headers)
        patient_put = client.put(
            f"/provider/products/{product_id}",
            headers=patient_headers,
            json=body,
        )
        missing_get = client.get("/provider/products")
        missing_put = client.put(
            f"/provider/products/{product_id}",
            json=body,
        )
        unknown_get = client.get("/provider/products", headers={"X-User-Id": "999999"})
        unknown_put = client.put(
            f"/provider/products/{product_id}",
            headers={"X-User-Id": "999999"},
            json=body,
        )
        stored = _load_provider_products(client, provider_id)

    assert patient_get.status_code == 403
    assert patient_get.json() == _FORBIDDEN
    assert patient_put.status_code == 403
    assert patient_put.json() == _FORBIDDEN
    assert missing_get.status_code == 401
    assert missing_get.json() == _UNAUTHENTICATED
    assert missing_put.status_code == 401
    assert missing_put.json() == _UNAUTHENTICATED
    assert unknown_get.status_code == 401
    assert unknown_get.json() == _UNAUTHENTICATED
    assert unknown_put.status_code == 401
    assert unknown_put.json() == _UNAUTHENTICATED
    _assert_seeded_provider_products(stored, catalog)


def test_provider_and_admin_see_the_catalog_and_a_patient_or_admin_list_is_forbidden(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        patient_id = _user_id(client, "Jane Doe")
        admin_id = _user_id(client, "Cerbo Admin")

        patient_catalog = client.get("/products", headers=_headers(patient_id))
        missing_catalog = client.get("/products")
        unknown_catalog = client.get("/products", headers={"X-User-Id": "999999"})
        provider_catalog = _load_catalog(client, provider_id)
        admin_catalog = _load_catalog(client, admin_id)
        admin_list = client.get("/provider/products", headers=_headers(admin_id))

    assert patient_catalog.status_code == 403
    assert patient_catalog.json() == _FORBIDDEN
    assert missing_catalog.status_code == 401
    assert missing_catalog.json() == _UNAUTHENTICATED
    assert unknown_catalog.status_code == 401
    assert unknown_catalog.json() == _UNAUTHENTICATED
    assert admin_catalog == provider_catalog
    assert [row["sku"] for row in provider_catalog] == [
        "MAG-GLY",
        "D3-K2",
        "OMEGA3",
        "PROBIO50",
    ]
    assert admin_list.status_code == 403
    assert admin_list.json() == _FORBIDDEN


def test_price_equal_to_cogs_returns_negative_payout_and_does_not_save(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        response = client.put(
            f"/provider/products/{product_id}",
            headers=_headers(provider_id),
            json={"enabled": True, "default_price_cents": 1_200},
        )
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 422
    assert response.json() == _NEGATIVE_PAYOUT
    _assert_seeded_provider_products(stored, catalog)


def test_price_below_cogs_returns_line_below_cogs_and_does_not_save(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        response = client.put(
            f"/provider/products/{product_id}",
            headers=_headers(provider_id),
            json={"enabled": True, "default_price_cents": 1_199},
        )
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 422
    assert response.json() == _LINE_BELOW_COGS
    _assert_seeded_provider_products(stored, catalog)


def test_valid_price_and_disabled_flag_save_only_that_provider_product(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        response = client.put(
            f"/provider/products/{product_id}",
            headers=_headers(provider_id),
            json={"enabled": False, "default_price_cents": 2_500},
        )
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 200
    _assert_provider_product(
        response.json(),
        product_id=product_id,
        sku="MAG-GLY",
        name="Magnesium Glycinate",
        enabled=False,
        default_price_cents=2_500,
        unit_cogs_cents=1_200,
        stock_qty=50,
    )
    _assert_provider_rows(
        stored,
        catalog,
        (
            (False, 2_500),
            (True, 1_800),
            (True, 3_600),
            (True, 4_200),
        ),
    )


def test_unknown_product_returns_not_found_and_catalog_stays_four_products(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        response = client.put(
            "/provider/products/999999",
            headers=_headers(provider_id),
            json={"enabled": True, "default_price_cents": 2_500},
        )
        catalog = _load_catalog(client, provider_id)
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 404
    assert response.json() == _NOT_FOUND
    assert len(catalog) == 4
    _assert_seeded_provider_products(stored, catalog)


def test_non_integer_price_returns_validation_error_and_does_not_save(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        response = client.put(
            f"/provider/products/{product_id}",
            headers={**_headers(provider_id), "Content-Type": "application/json"},
            content=_NON_INTEGER_PRICE,
        )
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 422
    assert response.json() == _VALIDATION_ERROR
    _assert_seeded_provider_products(stored, catalog)


@pytest.mark.parametrize(
    "payload",
    (
        {"enabled": True},
        {"default_price_cents": 2_500},
        {},
    ),
    ids=("missing-price", "missing-enabled", "missing-both"),
)
def test_missing_field_returns_validation_error_and_does_not_save(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        response = client.put(
            f"/provider/products/{product_id}",
            headers=_headers(provider_id),
            json=payload,
        )
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 422
    assert response.json() == _VALIDATION_ERROR
    _assert_seeded_provider_products(stored, catalog)


@pytest.mark.parametrize(
    "content",
    (
        '{"enabled": true, "default_price_cents": 2500.0}',
        '{"enabled": true, "default_price_cents": true}',
        '{"enabled": true, "default_price_cents": "2500"}',
        '{"enabled": 1, "default_price_cents": 2500}',
    ),
    ids=("integer-valued-float", "boolean-price", "numeric-string", "enabled-as-integer"),
)
def test_coerced_money_or_enabled_values_are_rejected(tmp_path: Path, content: str) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")
        response = client.put(
            f"/provider/products/{product_id}",
            headers={**_headers(provider_id), "Content-Type": "application/json"},
            content=content,
        )
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 422
    assert response.json() == _VALIDATION_ERROR
    _assert_seeded_provider_products(stored, catalog)


def test_non_integer_product_id_returns_validation_error(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        response = client.put(
            "/provider/products/abc",
            headers=_headers(provider_id),
            json={"enabled": True, "default_price_cents": 2_500},
        )
        catalog = _load_catalog(client, provider_id)
        stored = _load_provider_products(client, provider_id)

    assert response.status_code == 422
    assert response.json() == _VALIDATION_ERROR
    assert len(catalog) == 4
    _assert_seeded_provider_products(stored, catalog)


def test_a_provider_cannot_change_another_providers_list(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        session: Session = application.state.session_factory()
        try:
            session.add(User(name="Dr. Alex Kim", role="provider"))
            session.commit()
        finally:
            session.close()
        alex_id = _user_id(client, "Dr. Alex Kim")
        catalog = _load_catalog(client, provider_id)
        product_id = _product_id(catalog, "MAG-GLY")

        response = client.put(
            f"/provider/products/{product_id}",
            headers=_headers(alex_id),
            json={"enabled": True, "default_price_cents": 3_000},
        )
        alex_list = _load_provider_products(client, alex_id)
        patel_list = _load_provider_products(client, provider_id)
        catalog_after = _load_catalog(client, provider_id)

    assert response.status_code == 200
    _assert_provider_product(
        response.json(),
        product_id=product_id,
        sku="MAG-GLY",
        name="Magnesium Glycinate",
        enabled=True,
        default_price_cents=3_000,
        unit_cogs_cents=1_200,
        stock_qty=50,
    )
    alex_rows = _require_list(alex_list)
    assert len(alex_rows) == 1
    _assert_provider_product(
        alex_rows[0],
        product_id=product_id,
        sku="MAG-GLY",
        name="Magnesium Glycinate",
        enabled=True,
        default_price_cents=3_000,
        unit_cogs_cents=1_200,
        stock_qty=50,
    )
    _assert_seeded_provider_products(patel_list, catalog)
    assert catalog_after == catalog

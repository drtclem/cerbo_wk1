from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.money import FEE_BPS_DEFAULT, LineInput, OrderSplit, compute_fee, compute_split
from app.main import create_app

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
_LINE_MONEY = (
    "product_id",
    "qty",
    "unit_price_cents",
    "unit_cogs_cents",
    "line_total_cents",
    "line_cogs_cents",
    "line_margin_cents",
)
_DASHBOARD_KEYS = {
    "gmv_cents",
    "platform_fee_cents",
    "earnings_cents",
    "paid_orders",
    "units_sold",
    "pending_orders",
}
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
    "provider_payout_cents",
    "ledger",
    "recomputed_fee_matches",
    "split_adds_up",
    "ledger_matches_split",
}
_LEDGER_TYPES = (
    "patient_payment",
    "cerbo_cogs",
    "cerbo_fee",
    "provider_payable",
)
_SEED_USERS = (
    ("Dr. Maya Patel", "provider"),
    ("Jane Doe", "patient"),
    ("Sam Lee", "patient"),
    ("Cerbo Admin", "admin"),
)
_ORDER_LINES = (
    ("MAG-GLY", 2),
    ("D3-K2", 1),
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_README_HEADINGS = ("What's stubbed", "Known limitations")
_README_LINKS = (
    "docs/prd.md",
    "docs/architecture.md",
    "docs/tasks.md",
    "docs/decisions.md",
    "docs/ai-log.md",
    "docs/diagrams/",
)
_DIAGRAMS = (
    "docs/diagrams/overview.md",
    "docs/diagrams/data-model.md",
    "docs/diagrams/flows/pay.md",
)


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _require_str(value: object) -> str:
    assert isinstance(value, str)
    return value


def _require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'e2e.db'}")


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
        indexed[_require_str(user["name"])] = user
    ids: list[int] = []
    for name, role in _SEED_USERS:
        assert indexed[name]["role"] == role
        ids.append(_require_int(indexed[name]["id"]))
    assert ids == sorted(set(ids))


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


def _assert_enabled_at_suggested_price(
    client: TestClient,
    provider_id: int,
    catalog: list[dict[str, object]],
    sku: str,
) -> None:
    response = client.get("/provider/products", headers=_headers(provider_id))
    assert response.status_code == 200
    matches = [
        _require_dict(row)
        for row in _require_list(response.json())
        if _require_dict(row)["sku"] == sku
    ]
    assert len(matches) == 1
    row = matches[0]
    assert row["enabled"] is True
    assert _require_int(row["default_price_cents"]) == _catalog_int(
        catalog, sku, "suggested_price_cents"
    )
    assert _require_int(row["product_id"]) == _product_id(catalog, sku)


def _request_line(product_id: int, qty: int, unit_price_cents: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "dosing": "Example: 1 capsule daily with a meal",
    }


def _expected_split(catalog: list[dict[str, object]]) -> OrderSplit:
    assert FEE_BPS_DEFAULT == 75
    inputs: list[LineInput] = []
    for sku, qty in _ORDER_LINES:
        price_cents = _catalog_int(catalog, sku, "suggested_price_cents")
        cogs_cents = _catalog_int(catalog, sku, "unit_cogs_cents")
        inputs.append(
            LineInput(
                product_id=_product_id(catalog, sku),
                qty=qty,
                unit_price_cents=price_cents,
                unit_cogs_cents=cogs_cents,
            )
        )
    split = compute_split(inputs, FEE_BPS_DEFAULT)
    assert split.fee_bps == FEE_BPS_DEFAULT
    assert split.platform_fee_cents == compute_fee(split.subtotal_cents, FEE_BPS_DEFAULT)
    assert split.subtotal_cents == 2 * 2_400 + 1_800
    assert split.cogs_total_cents == 2 * 1_200 + 900
    assert split.provider_payout_cents == (
        split.subtotal_cents - split.cogs_total_cents - split.platform_fee_cents
    )
    return split


def _money_tuple(body: dict[str, object]) -> tuple[int, ...]:
    return tuple(_require_int(body[field]) for field in _SPLIT_FIELDS)


def _line_money(body: dict[str, object]) -> tuple[tuple[int, ...], ...]:
    lines: list[tuple[int, ...]] = []
    for line_value in _require_list(body["lines"]):
        line = _require_dict(line_value)
        lines.append(tuple(_require_int(line[field]) for field in _LINE_MONEY))
    return tuple(lines)


def _assert_matches_split(body: dict[str, object], expected: OrderSplit) -> None:
    assert _money_tuple(body) == (
        expected.subtotal_cents,
        expected.cogs_total_cents,
        expected.fee_bps,
        expected.platform_fee_cents,
        expected.provider_payout_cents,
    )
    assert _line_money(body) == tuple(
        (
            line.product_id,
            line.qty,
            line.unit_price_cents,
            line.unit_cogs_cents,
            line.line_total_cents,
            line.line_cogs_cents,
            line.line_margin_cents,
        )
        for line in expected.lines
    )


def _get_order(client: TestClient, order_id: int, user_id: int) -> dict[str, object]:
    response = client.get(f"/orders/{order_id}", headers=_headers(user_id))
    assert response.status_code == 200
    return _require_dict(response.json())


def _dashboard(client: TestClient, provider_id: int) -> dict[str, object]:
    response = client.get("/provider/dashboard", headers=_headers(provider_id))
    assert response.status_code == 200
    body = _require_dict(response.json())
    assert set(body) == _DASHBOARD_KEYS
    return body


def _ids(body: dict[str, object], key: str) -> list[int]:
    return [
        _require_int(_require_dict(item)["id"]) for item in _require_list(body[key])
    ]


def _assert_unpaid_dashboard(body: dict[str, object], pending_ids: list[int]) -> None:
    assert _require_int(body["gmv_cents"]) == 0
    assert _require_int(body["platform_fee_cents"]) == 0
    assert _require_int(body["earnings_cents"]) == 0
    assert _ids(body, "paid_orders") == []
    assert body["units_sold"] == []
    assert _ids(body, "pending_orders") == pending_ids


def _amounts_by_type(entries: list[dict[str, object]]) -> dict[str, int]:
    amounts: dict[str, int] = {}
    for entry in entries:
        entry_type = _require_str(entry["entry_type"])
        assert entry_type not in amounts
        amounts[entry_type] = _require_int(entry["amount_cents"])
    return amounts


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


def test_order_decline_then_pay_dashboard_and_audit_match_to_the_cent(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (_application, client, catalog):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        assert provider_id != jane_id
        for sku, _qty in _ORDER_LINES:
            _assert_enabled_at_suggested_price(client, provider_id, catalog, sku)
        expected = _expected_split(catalog)
        lines = [
            _request_line(
                _product_id(catalog, sku),
                qty,
                _catalog_int(catalog, sku, "suggested_price_cents"),
            )
            for sku, qty in _ORDER_LINES
        ]

        empty = _dashboard(client, provider_id)
        _assert_unpaid_dashboard(empty, [])

        created_response = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines},
        )
        assert created_response.status_code == 200
        created = _require_dict(created_response.json())
        order_id = _require_int(created["id"])
        assert _require_int(created["patient_id"]) == jane_id
        assert _require_int(created["provider_id"]) == provider_id
        assert created["status"] == "pending_payment"
        _assert_matches_split(created, expected)
        before_decline = _get_order(client, order_id, jane_id)
        assert before_decline["status"] == "pending_payment"
        _assert_matches_split(before_decline, expected)

        declined = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_decline"},
        )
        assert declined.status_code == 402
        assert _require_dict(_require_dict(declined.json())["error"])["code"] == (
            "PAYMENT_DECLINED"
        )
        after_decline = _get_order(client, order_id, jane_id)
        assert after_decline["status"] == "pending_payment"
        _assert_matches_split(after_decline, expected)
        assert _money_tuple(after_decline) == _money_tuple(before_decline)
        assert _line_money(after_decline) == _line_money(before_decline)
        declined_dashboard = _dashboard(client, provider_id)
        _assert_unpaid_dashboard(declined_dashboard, [order_id])

        paid_response = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid_response.status_code == 200
        paid = _require_dict(paid_response.json())
        assert _require_int(paid["id"]) == order_id
        assert paid["status"] == "paid"
        _assert_matches_split(paid, expected)
        after_pay = _get_order(client, order_id, jane_id)
        assert after_pay["status"] == "paid"
        _assert_matches_split(after_pay, expected)
        assert _money_tuple(before_decline) == _money_tuple(after_decline) == _money_tuple(
            after_pay
        )
        assert _line_money(before_decline) == _line_money(after_decline) == _line_money(after_pay)

        dashboard = _dashboard(client, provider_id)
        assert _require_int(dashboard["gmv_cents"]) == expected.subtotal_cents
        assert _require_int(dashboard["platform_fee_cents"]) == expected.platform_fee_cents
        assert _require_int(dashboard["earnings_cents"]) == expected.provider_payout_cents
        assert _ids(dashboard, "pending_orders") == []
        paid_orders = [
            _require_dict(item) for item in _require_list(dashboard["paid_orders"])
        ]
        assert [_require_int(item["id"]) for item in paid_orders] == [order_id]
        paid_order = paid_orders[0]
        assert _require_int(paid_order["patient_id"]) == jane_id
        assert paid_order["patient_name"] == "Jane Doe"
        assert _require_int(paid_order["subtotal_cents"]) == expected.subtotal_cents
        assert _require_int(paid_order["platform_fee_cents"]) == expected.platform_fee_cents
        assert _require_int(paid_order["provider_payout_cents"]) == (
            expected.provider_payout_cents
        )
        units = {
            _require_int(_require_dict(item)["product_id"]): _require_dict(item)
            for item in _require_list(dashboard["units_sold"])
        }
        assert set(units) == {
            _product_id(catalog, sku) for sku, _qty in _ORDER_LINES
        }
        for sku, qty in _ORDER_LINES:
            unit = units[_product_id(catalog, sku)]
            assert unit["product_name"] == _catalog_row(catalog, sku)["name"]
            assert _require_int(unit["qty"]) == qty

        audit_response = client.get(
            f"/orders/{order_id}/audit",
            headers=_headers(provider_id),
        )
        assert audit_response.status_code == 200
        audit = _require_dict(audit_response.json())
        assert set(audit) == _AUDIT_KEYS
        assert _require_int(audit["id"]) == order_id
        assert audit["status"] == "paid"
        _assert_matches_split(audit, expected)
        assert _money_tuple(audit) == _money_tuple(after_pay)
        assert _line_money(audit) == _line_money(after_pay)
        ledger = [_require_dict(entry) for entry in _require_list(audit["ledger"])]
        assert len(ledger) == len(_LEDGER_TYPES)
        amounts = _amounts_by_type(ledger)
        assert set(amounts) == set(_LEDGER_TYPES)
        assert amounts["patient_payment"] == expected.subtotal_cents
        assert amounts["cerbo_cogs"] == expected.cogs_total_cents
        assert amounts["cerbo_fee"] == expected.platform_fee_cents
        assert amounts["provider_payable"] == expected.provider_payout_cents
        assert amounts["patient_payment"] == _require_int(audit["subtotal_cents"])
        allocated = (
            amounts["cerbo_cogs"] + amounts["cerbo_fee"] + amounts["provider_payable"]
        )
        assert allocated == amounts["patient_payment"]
        assert audit["recomputed_fee_matches"] is True
        assert audit["split_adds_up"] is True
        assert audit["ledger_matches_split"] is True


def test_readme_names_the_walkthrough_users_and_diagrams_exist() -> None:
    for relative in _DIAGRAMS:
        assert (_REPO_ROOT / relative).is_file()
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for heading in _README_HEADINGS:
        assert heading in readme
    for name in ("Dr. Maya Patel", "Jane Doe"):
        assert name in readme
    for link in _README_LINKS:
        assert link in readme

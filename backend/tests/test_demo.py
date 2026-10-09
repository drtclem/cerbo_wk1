"""T20: DEMO_MODE reset endpoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app

_PRODUCTS = (
    ("MAG-GLY", "Magnesium Glycinate", 1_200, 2_400, 50),
    ("D3-K2", "Vitamin D3 + K2", 900, 1_800, 40),
    ("OMEGA3", "Omega-3 Fish Oil", 1_850, 3_600, 25),
    ("PROBIO50", "Probiotic 50B", 2_100, 4_200, 1),
)


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _user_id(client: TestClient, name: str) -> int:
    users = [_require_dict(u) for u in _require_list(client.get("/users").json())]
    matches = [u for u in users if u["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _application(tmp_path: Path, *, demo_mode: bool) -> FastAPI:
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        demo_mode=demo_mode,
    )


def test_demo_reset_clears_orders_and_restores_seed_stock_and_cogs(tmp_path: Path) -> None:
    application = _application(tmp_path, demo_mode=True)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        catalog = [
            _require_dict(row)
            for row in _require_list(
                client.get("/products", headers=_headers(provider_id)).json()
            )
        ]
        mag = next(row for row in catalog if row["sku"] == "MAG-GLY")
        mag_id = _require_int(mag["id"])
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": jane_id,
                "lines": [
                    {
                        "product_id": mag_id,
                        "qty": 2,
                        "unit_price_cents": 2_400,
                    }
                ],
            },
        )
        assert created.status_code == 200
        paid = client.post(
            f"/orders/{_require_int(_require_dict(created.json())['id'])}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200

        after_pay_catalog = [
            _require_dict(row)
            for row in _require_list(
                client.get("/products", headers=_headers(provider_id)).json()
            )
        ]
        mag_after = next(row for row in after_pay_catalog if row["sku"] == "MAG-GLY")
        assert _require_int(mag_after["stock_qty"]) == 48

        admin_id = _user_id(client, "Cerbo Admin")
        bumped = client.put(
            f"/admin/products/{mag_id}",
            headers=_headers(admin_id),
            json={"unit_cogs_cents": 1_500},
        )
        assert bumped.status_code == 200

        reset = client.post("/demo/reset")
        assert reset.status_code == 204
        assert reset.content in (b"", b"null")

        patients = client.get("/patient/orders", headers=_headers(jane_id))
        assert patients.status_code == 200
        assert patients.json() == []

        restored = [
            _require_dict(row)
            for row in _require_list(
                client.get("/products", headers=_headers(provider_id)).json()
            )
        ]
        assert len(restored) == len(_PRODUCTS)
        for row, expected in zip(restored, _PRODUCTS, strict=True):
            sku, _name, cogs_cents, _suggested, stock_qty = expected
            assert row["sku"] == sku
            assert _require_int(row["unit_cogs_cents"]) == cogs_cents
            assert _require_int(row["stock_qty"]) == stock_qty

        users = [_require_dict(u) for u in _require_list(client.get("/users").json())]
        assert {u["name"] for u in users} == {
            "Dr. Maya Patel",
            "Jane Doe",
            "Sam Lee",
            "Cerbo Admin",
        }


def test_demo_reset_route_is_absent_when_demo_mode_is_off(tmp_path: Path) -> None:
    application = _application(tmp_path, demo_mode=False)
    with TestClient(application) as client:
        response = client.post("/demo/reset")
        assert response.status_code == 404

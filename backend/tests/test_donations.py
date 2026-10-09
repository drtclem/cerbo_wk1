"""T23 / D12: research donations through preview, create, pay, audit, and DB."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import LedgerEntry, Order, OrderLine, ResearchFund
from app.seed import seed

_CREATED_AT = "2026-10-09T12:00:00Z"


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'donations.db'}")


def _user_id(client: TestClient, name: str) -> int:
    users = client.get("/users").json()
    assert isinstance(users, list)
    matches = [user for user in users if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _product_id(client: TestClient, provider_id: int, sku: str) -> int:
    response = client.get("/products", headers=_headers(provider_id))
    assert response.status_code == 200
    for row_value in _require_list(response.json()):
        row = _require_dict(row_value)
        if row["sku"] == sku:
            return _require_int(row["id"])
    raise AssertionError(sku)


def _readme_lines(client: TestClient, provider_id: int) -> list[dict[str, object]]:
    mag = _product_id(client, provider_id, "MAG-GLY")
    d3 = _product_id(client, provider_id, "D3-K2")
    return [
        {
            "product_id": mag,
            "qty": 2,
            "unit_price_cents": 2_400,
            "dosing": "Example: 1 capsule daily with a meal",
            "note": None,
        },
        {
            "product_id": d3,
            "qty": 1,
            "unit_price_cents": 1_800,
            "dosing": "Example: 1 capsule daily with a meal",
            "note": None,
        },
    ]


def test_seed_creates_four_research_funds_and_product_links(db_session: Session) -> None:
    seed(db_session)
    db_session.commit()
    funds = list(db_session.scalars(select(ResearchFund).order_by(ResearchFund.id)))
    assert len(funds) == 4
    names = {fund.name for fund in funds}
    assert "American Migraine Foundation" in names
    assert "ASBMR Fund for Research and Education" in names


def test_db_rejects_order_split_that_does_not_add_up_with_donation(
    db_session: Session,
) -> None:
    seed(db_session)
    db_session.commit()
    from app.models import User

    provider_id = db_session.scalars(select(User).where(User.name == "Dr. Maya Patel")).one().id
    patient_id = db_session.scalars(select(User).where(User.name == "Jane Doe")).one().id
    # donation 165 claimed but payout left at the no-donation figure → does not add up.
    db_session.add(
        Order(
            provider_id=provider_id,
            patient_id=patient_id,
            status="pending_payment",
            fee_bps=75,
            donation_bps=500,
            subtotal_cents=6_600,
            cogs_total_cents=3_300,
            platform_fee_cents=50,
            donation_cents=165,
            provider_payout_cents=3_250,
            created_at=_CREATED_AT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_ledger_allows_one_research_donation_per_fund_and_rejects_duplicate(
    db_session: Session,
) -> None:
    seed(db_session)
    db_session.commit()
    from app.models import User

    provider_id = db_session.scalars(select(User).where(User.name == "Dr. Maya Patel")).one().id
    patient_id = db_session.scalars(select(User).where(User.name == "Jane Doe")).one().id
    fund_ids = list(db_session.scalars(select(ResearchFund.id).order_by(ResearchFund.id)))
    assert len(fund_ids) >= 2
    order = Order(
        provider_id=provider_id,
        patient_id=patient_id,
        status="paid",
        fee_bps=75,
        donation_bps=500,
        subtotal_cents=6_600,
        cogs_total_cents=3_300,
        platform_fee_cents=50,
        donation_cents=165,
        provider_payout_cents=3_085,
        created_at=_CREATED_AT,
        paid_at=_CREATED_AT,
        payment_ref="pay_x",
    )
    db_session.add(order)
    db_session.flush()
    for entry_type, amount, fund_id in (
        ("patient_payment", 6_600, None),
        ("cerbo_cogs", 3_300, None),
        ("cerbo_fee", 50, None),
        ("provider_payable", 3_085, None),
        ("research_donation", 120, fund_ids[0]),
        ("research_donation", 45, fund_ids[1]),
    ):
        db_session.add(
            LedgerEntry(
                order_id=order.id,
                entry_type=entry_type,
                amount_cents=amount,
                created_at=_CREATED_AT,
                fund_id=fund_id,
            )
        )
    db_session.commit()

    db_session.add(
        LedgerEntry(
            order_id=order.id,
            entry_type="research_donation",
            amount_cents=1,
            created_at=_CREATED_AT,
            fund_id=fund_ids[0],
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_readme_order_donate_off_keeps_today_payout_and_on_matches_worked_example(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        lines = _readme_lines(client, provider_id)
        preview_lines = [
            {
                "product_id": line["product_id"],
                "qty": line["qty"],
                "unit_price_cents": line["unit_price_cents"],
            }
            for line in lines
        ]

        off = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": preview_lines, "donate": False},
        )
        assert off.status_code == 200
        off_body = _require_dict(off.json())
        assert _require_int(off_body["subtotal_cents"]) == 6_600
        assert _require_int(off_body["cogs_total_cents"]) == 3_300
        assert _require_int(off_body["platform_fee_cents"]) == 50
        assert _require_int(off_body["donation_cents"]) == 0
        assert _require_int(off_body["donation_bps"]) == 0
        assert _require_int(off_body["provider_payout_cents"]) == 3_250

        on = client.post(
            "/orders/preview",
            headers=_headers(provider_id),
            json={"lines": preview_lines, "donate": True},
        )
        assert on.status_code == 200
        on_body = _require_dict(on.json())
        assert _require_int(on_body["subtotal_cents"]) == 6_600
        assert _require_int(on_body["cogs_total_cents"]) == 3_300
        assert _require_int(on_body["platform_fee_cents"]) == 50
        assert _require_int(on_body["donation_bps"]) == 500
        assert _require_int(on_body["donation_cents"]) == 165
        assert _require_int(on_body["provider_payout_cents"]) == 3_085
        on_lines = [_require_dict(line) for line in _require_list(on_body["lines"])]
        assert [_require_int(line["donation_cents"]) for line in on_lines] == [120, 45]
        assert on_lines[0]["fund_name"] == "American Migraine Foundation"
        assert on_lines[1]["fund_name"] == "ASBMR Fund for Research and Education"

        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines, "donate": True},
        )
        assert created.status_code == 200
        order = _require_dict(created.json())
        order_id = _require_int(order["id"])
        assert _require_int(order["donation_cents"]) == 165
        assert _require_int(order["provider_payout_cents"]) == 3_085

        paid = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200

        audit = client.get(f"/orders/{order_id}/audit", headers=_headers(provider_id))
        assert audit.status_code == 200
        body = _require_dict(audit.json())
        assert body["recomputed_fee_matches"] is True
        assert body["donation_matches_rate"] is True
        assert body["split_adds_up"] is True
        assert body["ledger_matches_split"] is True
        assert _require_int(body["donation_cents"]) == 165
        assert _require_int(body["provider_payout_cents"]) == 3_085

        ledger = [_require_dict(entry) for entry in _require_list(body["ledger"])]
        by_type: dict[str, list[dict[str, object]]] = {}
        for entry in ledger:
            entry_type = entry["entry_type"]
            assert isinstance(entry_type, str)
            by_type.setdefault(entry_type, []).append(entry)
        assert _require_int(by_type["patient_payment"][0]["amount_cents"]) == 6_600
        assert _require_int(by_type["cerbo_cogs"][0]["amount_cents"]) == 3_300
        assert _require_int(by_type["cerbo_fee"][0]["amount_cents"]) == 50
        assert _require_int(by_type["provider_payable"][0]["amount_cents"]) == 3_085
        donations = by_type["research_donation"]
        assert len(donations) == 2
        amounts = sorted(_require_int(entry["amount_cents"]) for entry in donations)
        assert amounts == [45, 120]

        dashboard = client.get("/provider/dashboard", headers=_headers(provider_id))
        assert dashboard.status_code == 200
        dash = _require_dict(dashboard.json())
        assert _require_int(dash["donation_cents"]) == 165
        assert _require_int(dash["earnings_cents"]) == 3_085


def test_tampered_line_donation_flips_donation_and_ledger_checks(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        lines = _readme_lines(client, provider_id)
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines, "donate": True},
        )
        order_id = _require_int(_require_dict(created.json())["id"])
        paid = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200

        session: Session = application.state.session_factory()
        try:
            order = session.get(Order, order_id)
            assert order is not None
            line = session.scalars(
                select(OrderLine).where(OrderLine.order_id == order_id).order_by(OrderLine.id)
            ).first()
            assert line is not None
            # Move 1¢ from donation into payout so the four-way still adds up,
            # but the per-line rate and ledger no longer match.
            assert line.donation_cents >= 1
            line.donation_cents -= 1
            order.donation_cents -= 1
            order.provider_payout_cents += 1
            session.commit()
        finally:
            session.close()

        audit = client.get(f"/orders/{order_id}/audit", headers=_headers(provider_id))
        assert audit.status_code == 200
        body = _require_dict(audit.json())
        assert body["split_adds_up"] is True
        assert body["donation_matches_rate"] is False
        assert body["ledger_matches_split"] is False


def test_patient_order_response_includes_funds_but_amounts_are_for_provider_ui(
    tmp_path: Path,
) -> None:
    """API may carry donation_cents; patient UI must not display them (frontend test)."""
    application = _application(tmp_path)
    with TestClient(application) as client:
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        lines = _readme_lines(client, provider_id)
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={"patient_id": jane_id, "lines": lines, "donate": True},
        )
        order = _require_dict(created.json())
        order_id = _require_int(order["id"])
        response = client.get(f"/orders/{order_id}", headers=_headers(jane_id))
        assert response.status_code == 200
        body = _require_dict(response.json())
        assert _require_int(body["donation_bps"]) == 500
        fund_names = {
            _require_dict(line)["fund_name"] for line in _require_list(body["lines"])
        }
        assert "American Migraine Foundation" in fund_names
        assert "ASBMR Fund for Research and Education" in fund_names

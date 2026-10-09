"""T24 / D13: patient removes order lines before paying."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.money import LineInput, compute_split
from app.main import create_app
from app.models import LedgerEntry, Order, OrderLine, Product
from app.seams.payment_provider import FakePaymentProvider
from app.services.payments import pay_order

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_JOIN_TIMEOUT_SECONDS = 15
_UNKNOWN_ID = 999_999
_NOT_FOUND = {
    "error": {
        "code": "NOT_FOUND",
        "message": "Not found",
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
_LAST_LINE = {
    "error": {
        "code": "LAST_LINE",
        "message": "At least one item must remain. Ask your provider to cancel the order.",
        "line_index": None,
    }
}
_NOT_REMOVABLE = {
    "error": {
        "code": "ORDER_NOT_REMOVABLE",
        "message": "Order cannot be changed.",
        "line_index": None,
    }
}


class _Call:
    def __init__(self) -> None:
        self.view: object | None = None
        self.error: BaseException | None = None


def _require_int(value: object) -> int:
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _require_str(value: object) -> str:
    assert isinstance(value, str)
    return value


def _application(tmp_path: Path) -> FastAPI:
    return create_app(database_url=f"sqlite:///{tmp_path / 'remove_line.db'}")


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _user_id(client: TestClient, name: str) -> int:
    users = client.get("/users").json()
    assert isinstance(users, list)
    matches = [user for user in users if user["name"] == name]
    assert len(matches) == 1
    return _require_int(matches[0]["id"])


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


def _create_donated_order(
    client: TestClient, provider_id: int, patient_id: int
) -> dict[str, object]:
    response = client.post(
        "/orders",
        headers=_headers(provider_id),
        json={
            "patient_id": patient_id,
            "lines": _readme_lines(client, provider_id),
            "donate": True,
        },
    )
    assert response.status_code == 200
    return _require_dict(response.json())


def _remove(
    client: TestClient, order_id: int, line_id: int, user_id: int
):
    return client.post(
        f"/orders/{order_id}/lines/{line_id}/remove",
        headers=_headers(user_id),
    )


def _line_rows(application: FastAPI, order_id: int) -> list[OrderLine]:
    session: Session = application.state.session_factory()
    try:
        return list(
            session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order_id)
                .order_by(OrderLine.id)
            )
        )
    finally:
        session.close()


def _line_id_for_product(application: FastAPI, order_id: int, product_id: int) -> int:
    matches = [
        line for line in _line_rows(application, order_id) if line.product_id == product_id
    ]
    assert len(matches) == 1
    return _require_int(matches[0].id)


def _expected_split_for_active_lines(
    application: FastAPI, order_id: int
) -> object:
    session: Session = application.state.session_factory()
    try:
        order = session.get(Order, order_id)
        assert order is not None
        active = [
            line
            for line in session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order_id)
                .order_by(OrderLine.id)
            )
            if getattr(line, "removed_at", None) is None
        ]
        inputs = [
            LineInput(
                product_id=_require_int(line.product_id),
                qty=_require_int(line.qty),
                unit_price_cents=_require_int(line.unit_price_cents),
                unit_cogs_cents=_require_int(line.unit_cogs_cents),
                has_research_fund=line.fund_id is not None,
            )
            for line in active
        ]
        return compute_split(
            inputs,
            _require_int(order.fee_bps),
            _require_int(order.donation_bps),
        )
    finally:
        session.close()


def _charge_amount(application: FastAPI, order_id: int) -> int | None:
    provider = application.state.payment_provider
    assert isinstance(provider, FakePaymentProvider)
    stored = provider._attempts.get(str(order_id))
    if stored is None:
        return None
    amount_cents, _method, _result = stored
    return _require_int(amount_cents)


def _charge_count(application: FastAPI) -> int:
    provider = application.state.payment_provider
    assert isinstance(provider, FakePaymentProvider)
    return _require_int(provider.charge_count)


def _stocks(application: FastAPI) -> dict[int, int]:
    session: Session = application.state.session_factory()
    try:
        rows = list(session.scalars(select(Product).order_by(Product.id)))
        return {_require_int(product.id): _require_int(product.stock_qty) for product in rows}
    finally:
        session.close()


def _ledger_for_order(application: FastAPI, order_id: int) -> list[dict[str, object]]:
    session: Session = application.state.session_factory()
    try:
        rows = list(
            session.scalars(
                select(LedgerEntry)
                .where(LedgerEntry.order_id == order_id)
                .order_by(LedgerEntry.id)
            )
        )
        loaded: list[dict[str, object]] = []
        for row in rows:
            loaded.append(
                {
                    "entry_type": row.entry_type,
                    "amount_cents": _require_int(row.amount_cents),
                    "fund_id": row.fund_id,
                }
            )
        return loaded
    finally:
        session.close()


def _stored_order(application: FastAPI, order_id: int) -> Order:
    session: Session = application.state.session_factory()
    try:
        order = session.get(Order, order_id)
        assert order is not None
        session.expunge(order)
        return order
    finally:
        session.close()


def _assert_split_matches(body: dict[str, object], expected: object) -> None:
    assert _require_int(body["subtotal_cents"]) == expected.subtotal_cents
    assert _require_int(body["cogs_total_cents"]) == expected.cogs_total_cents
    assert _require_int(body["fee_bps"]) == expected.fee_bps
    assert _require_int(body["platform_fee_cents"]) == expected.platform_fee_cents
    assert _require_int(body["donation_bps"]) == expected.donation_bps
    assert _require_int(body["donation_cents"]) == expected.donation_cents
    assert _require_int(body["provider_payout_cents"]) == expected.provider_payout_cents


@contextmanager
def _seeded(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient]]:
    application = _application(tmp_path)
    with TestClient(application) as client:
        yield application, client


def _start_pay(
    application: FastAPI,
    order_id: int,
    call: _Call,
) -> threading.Thread:
    payment_provider = application.state.payment_provider
    fulfillment = application.state.fulfillment

    def _target() -> None:
        session: Session = application.state.session_factory()
        try:
            loaded = session.get(Order, order_id)
            assert loaded is not None
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


def _start_remove(
    application: FastAPI,
    order_id: int,
    line_id: int,
    call: _Call,
) -> threading.Thread:
    from app.services.orders import remove_order_line

    def _target() -> None:
        session: Session = application.state.session_factory()
        try:
            loaded = session.get(Order, order_id)
            assert loaded is not None
            call.view = remove_order_line(session, loaded, line_id)
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


def test_removing_a_line_recomputes_fee_and_donation_exactly(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        assert _require_int(created["subtotal_cents"]) == 6_600
        assert _require_int(created["platform_fee_cents"]) == 50
        assert _require_int(created["donation_cents"]) == 165
        assert _require_int(created["donation_bps"]) == 500
        assert _require_int(created["fee_bps"]) == 75

        d3_id = _product_id(client, provider_id, "D3-K2")
        line_id = _line_id_for_product(application, order_id, d3_id)
        response = _remove(client, order_id, line_id, jane_id)
        assert response.status_code == 200
        body = _require_dict(response.json())
        assert body["status"] == "pending_payment"
        assert _require_int(body["fee_bps"]) == 75
        assert _require_int(body["donation_bps"]) == 500

        expected = _expected_split_for_active_lines(application, order_id)
        # Mag 2×$24.00 only: fee and donation from money.py on stored prices/rates.
        assert expected.subtotal_cents == 4_800
        assert expected.cogs_total_cents == 2_400
        assert expected.platform_fee_cents == 36
        assert expected.donation_cents == 120
        assert expected.provider_payout_cents == 2_244
        _assert_split_matches(body, expected)

        stored = _stored_order(application, order_id)
        assert stored.subtotal_cents == expected.subtotal_cents
        assert stored.platform_fee_cents == expected.platform_fee_cents
        assert stored.donation_cents == expected.donation_cents
        assert stored.provider_payout_cents == expected.provider_payout_cents
        assert stored.fee_bps == 75
        assert stored.donation_bps == 500

        active = [_require_dict(line) for line in _require_list(body["lines"])]
        assert len(active) == 1
        assert _require_int(active[0]["product_id"]) == _product_id(
            client, provider_id, "MAG-GLY"
        )
        assert active[0]["removed_at"] is None
        removed = [_require_dict(line) for line in _require_list(body["removed_lines"])]
        assert len(removed) == 1
        assert _require_int(removed[0]["id"]) == line_id
        assert _require_int(removed[0]["product_id"]) == d3_id
        removed_at = _require_str(removed[0]["removed_at"])
        assert _TIMESTAMP.fullmatch(removed_at)


def test_removal_uses_stored_line_prices_not_live_catalog(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        mag_id = _product_id(client, provider_id, "MAG-GLY")
        line_id = _line_id_for_product(application, order_id, d3_id)

        session: Session = application.state.session_factory()
        try:
            mag = session.get(Product, mag_id)
            assert mag is not None
            mag.unit_cogs_cents = 5_000
            session.commit()
        finally:
            session.close()

        response = _remove(client, order_id, line_id, jane_id)
        assert response.status_code == 200
        body = _require_dict(response.json())
        expected = compute_split(
            [
                LineInput(
                    product_id=mag_id,
                    qty=2,
                    unit_price_cents=2_400,
                    unit_cogs_cents=1_200,
                    has_research_fund=True,
                )
            ],
            fee_bps=75,
            donation_bps=500,
        )
        _assert_split_matches(body, expected)


def test_cannot_remove_the_last_active_line(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        mag_id = _product_id(client, provider_id, "MAG-GLY")
        d3_line_id = _line_id_for_product(application, order_id, d3_id)
        mag_line_id = _line_id_for_product(application, order_id, mag_id)

        first = _remove(client, order_id, d3_line_id, jane_id)
        assert first.status_code == 200
        before = _stored_order(application, order_id)

        second = _remove(client, order_id, mag_line_id, jane_id)
        assert second.status_code == 409
        assert second.json() == _LAST_LINE
        after = _stored_order(application, order_id)
        assert after.subtotal_cents == before.subtotal_cents
        assert after.donation_cents == before.donation_cents
        assert after.platform_fee_cents == before.platform_fee_cents
        assert after.status == "pending_payment"
        remaining = [
            line
            for line in _line_rows(application, order_id)
            if getattr(line, "removed_at", None) is None
        ]
        assert len(remaining) == 1
        assert remaining[0].product_id == mag_id


def test_cannot_remove_after_paid_or_cancelled(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")

        paid_order = _create_donated_order(client, provider_id, jane_id)
        paid_id = _require_int(paid_order["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        paid_line_id = _line_id_for_product(application, paid_id, d3_id)
        paid = client.post(
            f"/orders/{paid_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200
        paid_before = _stored_order(application, paid_id)
        paid_remove = _remove(client, paid_id, paid_line_id, jane_id)
        assert paid_remove.status_code == 409
        assert paid_remove.json() == _NOT_REMOVABLE
        paid_after = _stored_order(application, paid_id)
        assert paid_after.status == "paid"
        assert paid_after.subtotal_cents == paid_before.subtotal_cents
        assert getattr(
            next(
                line
                for line in _line_rows(application, paid_id)
                if line.id == paid_line_id
            ),
            "removed_at",
            None,
        ) is None

        cancelled_order = _create_donated_order(client, provider_id, jane_id)
        cancelled_id = _require_int(cancelled_order["id"])
        cancelled_line_id = _line_id_for_product(application, cancelled_id, d3_id)
        cancelled = client.post(
            f"/orders/{cancelled_id}/cancel", headers=_headers(provider_id)
        )
        assert cancelled.status_code == 200
        cancelled_before = _stored_order(application, cancelled_id)
        cancelled_remove = _remove(client, cancelled_id, cancelled_line_id, jane_id)
        assert cancelled_remove.status_code == 409
        assert cancelled_remove.json() == _NOT_REMOVABLE
        cancelled_after = _stored_order(application, cancelled_id)
        assert cancelled_after.status == "cancelled"
        assert cancelled_after.subtotal_cents == cancelled_before.subtotal_cents


def test_another_patient_gets_404_on_remove(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        sam_id = _user_id(client, "Sam Lee")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        line_id = _line_id_for_product(application, order_id, d3_id)
        before = _stored_order(application, order_id)

        response = _remove(client, order_id, line_id, sam_id)
        assert response.status_code == 404
        assert response.json() == _NOT_FOUND
        after = _stored_order(application, order_id)
        assert after.subtotal_cents == before.subtotal_cents
        assert after.status == "pending_payment"
        assert all(
            getattr(line, "removed_at", None) is None
            for line in _line_rows(application, order_id)
        )


def test_provider_cannot_remove_a_line(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        line_id = _line_id_for_product(application, order_id, d3_id)

        response = _remove(client, order_id, line_id, provider_id)
        assert response.status_code == 403
        assert response.json() == _FORBIDDEN


def test_unknown_order_or_line_returns_404(tmp_path: Path) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        line_id = _line_id_for_product(application, order_id, d3_id)

        missing_order = _remove(client, _UNKNOWN_ID, line_id, jane_id)
        assert missing_order.status_code == 404
        assert missing_order.json() == _NOT_FOUND

        missing_line = _remove(client, order_id, _UNKNOWN_ID, jane_id)
        assert missing_line.status_code == 404
        assert missing_line.json() == _NOT_FOUND


def test_concurrent_remove_vs_pay_has_exactly_one_winner_and_charge_matches_total(
    tmp_path: Path,
) -> None:
    from app.services.orders import OrderNotRemovable

    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        original_subtotal = _require_int(created["subtotal_cents"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        mag_id = _product_id(client, provider_id, "MAG-GLY")
        line_id = _line_id_for_product(application, order_id, d3_id)
        before_stocks = _stocks(application)
        assert _charge_count(application) == 0

        # Reduced split if D3 is removed (Mag 2×$24.00, donate on).
        reduced = compute_split(
            [
                LineInput(
                    product_id=mag_id,
                    qty=2,
                    unit_price_cents=2_400,
                    unit_cogs_cents=1_200,
                    has_research_fund=True,
                )
            ],
            fee_bps=75,
            donation_bps=500,
        )

        pay_call = _Call()
        remove_call = _Call()
        _finish(
            [
                _start_pay(application, order_id, pay_call),
                _start_remove(application, order_id, line_id, remove_call),
            ]
        )

        pay_ok = pay_call.view is not None and pay_call.error is None
        remove_ok = remove_call.view is not None and remove_call.error is None
        # Conditional updates: exactly one of the two contested outcomes wins.
        # Pay-first → remove fails. Remove-first → pay either fails the claim race
        # or (if serialized after remove commits) charges the reduced stored total.
        assert pay_ok or remove_ok

        stored = _stored_order(application, order_id)
        lines = _line_rows(application, order_id)
        removed_line = next(line for line in lines if line.id == line_id)
        line_removed = getattr(removed_line, "removed_at", None) is not None
        active = [line for line in lines if getattr(line, "removed_at", None) is None]

        if stored.status == "paid":
            assert pay_ok
            assert _charge_count(application) == 1
            charged = _charge_amount(application, order_id)
            assert charged == stored.subtotal_cents
            if line_removed:
                # Remove won the composition; charge must be the recomputed total.
                assert remove_ok
                assert len(active) == 1
                assert stored.subtotal_cents == reduced.subtotal_cents
                assert charged == reduced.subtotal_cents
                expected_stocks = dict(before_stocks)
                expected_stocks[mag_id] = before_stocks[mag_id] - 2
                assert _stocks(application) == expected_stocks
            else:
                # Pay won before remove could apply.
                assert not remove_ok
                assert isinstance(remove_call.error, OrderNotRemovable)
                assert len(active) == 2
                assert stored.subtotal_cents == original_subtotal
                assert charged == original_subtotal
                expected_stocks = dict(before_stocks)
                expected_stocks[mag_id] = before_stocks[mag_id] - 2
                expected_stocks[d3_id] = before_stocks[d3_id] - 1
                assert _stocks(application) == expected_stocks
        elif stored.status == "pending_payment":
            # Remove applied; pay lost the race and did not charge.
            assert remove_ok
            assert line_removed
            assert not pay_ok
            assert pay_call.error is not None
            assert stored.subtotal_cents == reduced.subtotal_cents
            assert _charge_count(application) == 0
            assert _charge_amount(application, order_id) is None
            assert _stocks(application) == before_stocks
            assert _ledger_for_order(application, order_id) == []
        else:
            raise AssertionError(stored.status)

        # Never charge a total that disagrees with the final stored order.
        if _charge_count(application) == 1:
            assert _charge_amount(application, order_id) == stored.subtotal_cents
        # Never: line removed but still charged the pre-remove total.
        if line_removed and stored.status == "paid":
            assert stored.subtotal_cents == reduced.subtotal_cents


def test_pay_after_remove_uses_active_lines_only_for_stock_ledger_and_units(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        mag_id = _product_id(client, provider_id, "MAG-GLY")
        line_id = _line_id_for_product(application, order_id, d3_id)
        before_stocks = _stocks(application)

        removed = _remove(client, order_id, line_id, jane_id)
        assert removed.status_code == 200
        removed_body = _require_dict(removed.json())
        expected = _expected_split_for_active_lines(application, order_id)
        _assert_split_matches(removed_body, expected)

        paid = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200
        paid_body = _require_dict(paid.json())
        _assert_split_matches(paid_body, expected)
        assert _charge_amount(application, order_id) == expected.subtotal_cents

        stocks = _stocks(application)
        assert stocks[mag_id] == before_stocks[mag_id] - 2
        assert stocks[d3_id] == before_stocks[d3_id]

        ledger = _ledger_for_order(application, order_id)
        by_type: dict[str, list[dict[str, object]]] = {}
        for entry in ledger:
            entry_type = _require_str(entry["entry_type"])
            by_type.setdefault(entry_type, []).append(entry)
        assert _require_int(by_type["patient_payment"][0]["amount_cents"]) == (
            expected.subtotal_cents
        )
        assert _require_int(by_type["cerbo_cogs"][0]["amount_cents"]) == (
            expected.cogs_total_cents
        )
        assert _require_int(by_type["cerbo_fee"][0]["amount_cents"]) == (
            expected.platform_fee_cents
        )
        assert _require_int(by_type["provider_payable"][0]["amount_cents"]) == (
            expected.provider_payout_cents
        )
        donations = by_type["research_donation"]
        assert len(donations) == 1
        assert _require_int(donations[0]["amount_cents"]) == expected.donation_cents

        dashboard = client.get("/provider/dashboard", headers=_headers(provider_id))
        assert dashboard.status_code == 200
        dash = _require_dict(dashboard.json())
        assert _require_int(dash["gmv_cents"]) == expected.subtotal_cents
        assert _require_int(dash["donation_cents"]) == expected.donation_cents
        assert _require_int(dash["earnings_cents"]) == expected.provider_payout_cents
        units = [_require_dict(row) for row in _require_list(dash["units_sold"])]
        by_product = {_require_int(row["product_id"]): _require_int(row["qty"]) for row in units}
        assert by_product[mag_id] == 2
        assert d3_id not in by_product


def test_audit_lists_removed_line_separately_and_integrity_checks_pass(
    tmp_path: Path,
) -> None:
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        created = _create_donated_order(client, provider_id, jane_id)
        order_id = _require_int(created["id"])
        d3_id = _product_id(client, provider_id, "D3-K2")
        mag_id = _product_id(client, provider_id, "MAG-GLY")
        line_id = _line_id_for_product(application, order_id, d3_id)

        removed = _remove(client, order_id, line_id, jane_id)
        assert removed.status_code == 200
        paid = client.post(
            f"/orders/{order_id}/pay",
            headers=_headers(jane_id),
            json={"payment_method": "fake_card_ok"},
        )
        assert paid.status_code == 200
        expected = _expected_split_for_active_lines(application, order_id)

        audit = client.get(f"/orders/{order_id}/audit", headers=_headers(provider_id))
        assert audit.status_code == 200
        body = _require_dict(audit.json())
        _assert_split_matches(body, expected)
        assert body["recomputed_fee_matches"] is True
        assert body["donation_matches_rate"] is True
        assert body["split_adds_up"] is True
        assert body["ledger_matches_split"] is True

        active = [_require_dict(line) for line in _require_list(body["lines"])]
        assert len(active) == 1
        assert _require_int(active[0]["product_id"]) == mag_id
        assert active[0]["removed_at"] is None

        removed_lines = [_require_dict(line) for line in _require_list(body["removed_lines"])]
        assert len(removed_lines) == 1
        assert _require_int(removed_lines[0]["product_id"]) == d3_id
        assert _require_int(removed_lines[0]["id"]) == line_id
        removed_at = _require_str(removed_lines[0]["removed_at"])
        assert _TIMESTAMP.fullmatch(removed_at)
        # Snapshot of the removed line is preserved for display; excluded from totals.
        assert _require_int(removed_lines[0]["qty"]) == 1
        assert _require_int(removed_lines[0]["unit_price_cents"]) == 1_800


def test_removal_that_would_leave_a_negative_payout_is_refused(tmp_path: Path) -> None:
    # 2 × Omega-3 at $18.60 (COGS $18.50): margin 20, plus 1 × Magnesium at $24.00
    # (COGS $12.00), donation on. Together: subtotal 6120, fee
    # (6120×75+5000)//10000 = 46, donations 1 + 60 = 61, payout 1113.
    # Omega alone: subtotal 3720, fee (3720×75+5000)//10000 = 28, donation 1,
    # payout 3720 − 3700 − 28 − 1 = −9, so removing Magnesium must be refused.
    with _seeded(tmp_path) as (application, client):
        provider_id = _user_id(client, "Dr. Maya Patel")
        jane_id = _user_id(client, "Jane Doe")
        omega = _product_id(client, provider_id, "OMEGA3")
        mag = _product_id(client, provider_id, "MAG-GLY")
        dosing = "Example: 1 capsule daily with a meal"
        created = client.post(
            "/orders",
            headers=_headers(provider_id),
            json={
                "patient_id": jane_id,
                "lines": [
                    {"product_id": omega, "qty": 2, "unit_price_cents": 1_860,
                     "dosing": dosing, "note": None},
                    {"product_id": mag, "qty": 1, "unit_price_cents": 2_400,
                     "dosing": dosing, "note": None},
                ],
                "donate": True,
            },
        )
        assert created.status_code == 200
        body = _require_dict(created.json())
        order_id = _require_int(body["id"])
        assert _require_int(body["provider_payout_cents"]) == 1_113

        line_id = _line_id_for_product(application, order_id, mag)
        response = _remove(client, order_id, line_id, jane_id)
        assert response.status_code == 409
        assert _require_dict(response.json()["error"])["code"] == "LINE_NOT_REMOVABLE"

        # Nothing changed: line still active, stored totals untouched.
        assert all(line.removed_at is None for line in _line_rows(application, order_id))
        session: Session = application.state.session_factory()
        try:
            order = session.get(Order, order_id)
            assert order is not None
            assert (order.subtotal_cents, order.provider_payout_cents) == (6_120, 1_113)
        finally:
            session.close()

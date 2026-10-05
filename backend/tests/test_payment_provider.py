from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from app.config import build_payment_provider
from app.main import create_app
from app.seams.payment_provider import ChargeResult, FakePaymentProvider, PaymentProvider

_DECLINE_REASON = "Card declined."


def _provider() -> FakePaymentProvider:
    provider = FakePaymentProvider()
    _assert_count(provider, 0)
    return provider


def _assert_count(provider: FakePaymentProvider, expected: int) -> None:
    count = provider.charge_count
    assert isinstance(count, int) and not isinstance(count, bool)
    assert count == expected


def _assert_charge_result(result: ChargeResult) -> None:
    assert isinstance(result, ChargeResult)
    assert is_dataclass(result)
    assert type(result).__dataclass_params__.frozen is True
    assert {field.name for field in fields(result)} == {"approved", "ref", "decline_reason"}


def _assert_approved(result: ChargeResult, idempotency_key: str) -> None:
    _assert_charge_result(result)
    assert result.approved is True
    assert result.ref == f"fake_{idempotency_key}"
    assert result.decline_reason is None


def _assert_declined(result: ChargeResult) -> None:
    _assert_charge_result(result)
    assert result.approved is False
    assert result.ref is None
    assert result.decline_reason == _DECLINE_REASON


def _charge(
    provider: FakePaymentProvider,
    amount_cents: int,
    idempotency_key: str,
    payment_method: str,
) -> ChargeResult:
    return provider.charge(
        amount_cents=amount_cents,
        idempotency_key=idempotency_key,
        payment_method=payment_method,
    )


def test_payment_provider_protocol_exposes_charge() -> None:
    assert callable(PaymentProvider.charge)


def test_fake_card_ok_approves_with_a_ref() -> None:
    provider = _provider()
    key = "order-ok"
    result = _charge(provider, 4_000, key, "fake_card_ok")
    _assert_approved(result, key)
    _assert_count(provider, 1)


def test_unknown_payment_method_approves_with_a_ref() -> None:
    provider = _provider()
    key = "order-unknown"
    result = _charge(provider, 4_000, key, "visa_4242")
    _assert_approved(result, key)
    _assert_count(provider, 1)


def test_fake_card_decline_declines_with_a_reason() -> None:
    provider = _provider()
    result = _charge(provider, 4_000, "order-decline", "fake_card_decline")
    _assert_declined(result)
    _assert_count(provider, 1)


def test_same_approval_replays_twice_without_increasing_charge_count() -> None:
    provider = _provider()
    key = "order-replay-ok"
    original = _charge(provider, 4_000, key, "fake_card_ok")
    _assert_approved(original, key)
    _assert_count(provider, 1)

    for _ in range(2):
        replay = _charge(provider, 4_000, key, "fake_card_ok")
        _assert_approved(replay, key)
        assert replay == original
        _assert_count(provider, 1)


def test_same_decline_replays_twice_without_increasing_charge_count() -> None:
    provider = _provider()
    key = "order-replay-decline"
    original = _charge(provider, 1_800, key, "fake_card_decline")
    _assert_declined(original)
    _assert_count(provider, 1)

    for _ in range(2):
        replay = _charge(provider, 1_800, key, "fake_card_decline")
        _assert_declined(replay)
        assert replay == original
        _assert_count(provider, 1)


def test_approval_stays_sticky_when_amount_or_payment_method_changes() -> None:
    provider = _provider()
    key = "order-sticky"
    original = _charge(provider, 4_000, key, "fake_card_ok")
    _assert_approved(original, key)
    _assert_count(provider, 1)

    different_amount = _charge(provider, 1, key, "fake_card_ok")
    _assert_approved(different_amount, key)
    assert different_amount == original
    _assert_count(provider, 1)

    decline_method = _charge(provider, 4_000, key, "fake_card_decline")
    _assert_approved(decline_method, key)
    assert decline_method == original
    _assert_count(provider, 1)

    other_method = _charge(provider, 9_999, key, "visa_4242")
    _assert_approved(other_method, key)
    assert other_method == original
    _assert_count(provider, 1)


def test_stored_decline_then_different_method_approves_and_stays_sticky() -> None:
    provider = _provider()
    key = "order-retry"
    amount_cents = 2_500

    declined = _charge(provider, amount_cents, key, "fake_card_decline")
    _assert_declined(declined)
    _assert_count(provider, 1)

    approved = _charge(provider, amount_cents, key, "fake_card_ok")
    _assert_approved(approved, key)
    _assert_count(provider, 2)

    replay = _charge(provider, amount_cents, key, "fake_card_ok")
    _assert_approved(replay, key)
    assert replay == approved
    _assert_count(provider, 2)

    original_decline_method = _charge(provider, amount_cents, key, "fake_card_decline")
    _assert_approved(original_decline_method, key)
    assert original_decline_method == approved
    _assert_count(provider, 2)


def test_stored_decline_with_a_different_amount_is_a_new_decline() -> None:
    provider = _provider()
    key = "order-new-amount"
    first = _charge(provider, 1_000, key, "fake_card_decline")
    _assert_declined(first)
    _assert_count(provider, 1)

    second = _charge(provider, 1_500, key, "fake_card_decline")
    _assert_declined(second)
    _assert_count(provider, 2)

    replay = _charge(provider, 1_500, key, "fake_card_decline")
    _assert_declined(replay)
    assert replay == second
    _assert_count(provider, 2)


def test_different_idempotency_keys_each_increment_charge_count() -> None:
    provider = _provider()
    approved = _charge(provider, 4_000, "order-a", "fake_card_ok")
    declined = _charge(provider, 4_000, "order-b", "fake_card_decline")
    _assert_approved(approved, "order-a")
    _assert_declined(declined)
    assert approved != declined
    _assert_count(provider, 2)


def test_charge_result_is_frozen_and_a_failed_mutation_does_not_change_the_replay() -> None:
    provider = _provider()
    key = "order-frozen"
    result = _charge(provider, 4_000, key, "fake_card_ok")
    _assert_approved(result, key)
    _assert_count(provider, 1)

    with pytest.raises(AttributeError):
        result.approved = False

    assert result.approved is True
    replay = _charge(provider, 4_000, key, "fake_card_ok")
    _assert_approved(replay, key)
    assert replay.approved is True
    assert replay == result
    _assert_count(provider, 1)


def test_create_app_stores_a_separate_fake_provider_before_lifespan(tmp_path: Path) -> None:
    database_path = tmp_path / "payments.db"
    application = create_app(database_url=f"sqlite:///{database_path}")
    wired = application.state.payment_provider
    first = build_payment_provider()
    second = build_payment_provider()

    assert isinstance(wired, FakePaymentProvider)
    assert isinstance(first, FakePaymentProvider)
    assert isinstance(second, FakePaymentProvider)
    assert wired is not first
    assert first is not second
    assert application.state.database_url == f"sqlite:///{database_path}"
    assert not database_path.exists()
    _assert_count(wired, 0)
    _assert_count(first, 0)
    _assert_count(second, 0)

    wired_result = wired.charge(
        amount_cents=4_000,
        idempotency_key="order-wired",
        payment_method="fake_card_ok",
    )
    _assert_approved(wired_result, "order-wired")
    _assert_count(wired, 1)
    _assert_count(application.state.payment_provider, 1)
    _assert_count(first, 0)
    _assert_count(second, 0)

    other_result = second.charge(
        amount_cents=4_000,
        idempotency_key="order-other",
        payment_method="fake_card_decline",
    )
    _assert_declined(other_result)
    _assert_count(second, 1)
    _assert_count(application.state.payment_provider, 1)
    _assert_count(wired, 1)
    _assert_count(first, 0)
    assert not database_path.exists()

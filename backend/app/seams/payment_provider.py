from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    ref: str | None
    decline_reason: str | None


class PaymentProvider(Protocol):
    def charge(
        self, amount_cents: int, idempotency_key: str, payment_method: str
    ) -> ChargeResult:
        """Charge once per attempt. A stored approval stays sticky."""


class FakePaymentProvider:
    """Approves unless the method is fake_card_decline. Remembers attempts by key."""

    def __init__(self) -> None:
        self.charge_count = 0
        self._attempts: dict[str, tuple[int, str, ChargeResult]] = {}

    def charge(
        self, amount_cents: int, idempotency_key: str, payment_method: str
    ) -> ChargeResult:
        stored = self._attempts.get(idempotency_key)
        if stored is not None:
            stored_amount, stored_method, result = stored
            if result.approved or (
                stored_amount == amount_cents and stored_method == payment_method
            ):
                return result
        result = _result_for(idempotency_key, payment_method)
        self._attempts[idempotency_key] = (amount_cents, payment_method, result)
        self.charge_count += 1
        return result


def _result_for(idempotency_key: str, payment_method: str) -> ChargeResult:
    if payment_method == "fake_card_decline":
        return ChargeResult(approved=False, ref=None, decline_reason="Card declined.")
    return ChargeResult(approved=True, ref=f"fake_{idempotency_key}", decline_reason=None)

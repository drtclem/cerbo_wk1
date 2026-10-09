import os

from app.seams.fulfillment import FakeFulfillment, Fulfillment
from app.seams.notifier import FakeNotifier, Notifier
from app.seams.payment_provider import FakePaymentProvider, PaymentProvider

database_url = os.environ.get("DATABASE_URL", "sqlite:///./cerbo.db")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


demo_mode = _env_flag("DEMO_MODE", default=False)


def build_notifier() -> Notifier:
    """The only place the notifier stub is chosen."""
    return FakeNotifier()


def build_payment_provider() -> PaymentProvider:
    """The only place the payment stub is chosen."""
    return FakePaymentProvider()


def build_fulfillment() -> Fulfillment:
    """The only place the fulfillment stub is chosen."""
    return FakeFulfillment()

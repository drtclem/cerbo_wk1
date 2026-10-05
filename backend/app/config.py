from app.seams.fulfillment import FakeFulfillment, Fulfillment
from app.seams.notifier import FakeNotifier, Notifier
from app.seams.payment_provider import FakePaymentProvider, PaymentProvider

database_url = "sqlite:///./cerbo.db"


def build_notifier() -> Notifier:
    """The only place the notifier stub is chosen."""
    return FakeNotifier()


def build_payment_provider() -> PaymentProvider:
    """The only place the payment stub is chosen."""
    return FakePaymentProvider()


def build_fulfillment() -> Fulfillment:
    """The only place the fulfillment stub is chosen."""
    return FakeFulfillment()

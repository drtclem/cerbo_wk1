from typing import Protocol

from app.models import Order


class Notifier(Protocol):
    def order_created(self, order: Order, patient_link: str) -> None:
        """Tell the patient an order exists."""


class FakeNotifier:
    """Console stand-in. Records each call so tests can see the patient link."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def order_created(self, order: Order, patient_link: str) -> None:
        print(f"order created: {patient_link}")
        self.calls.append((order.id, patient_link))

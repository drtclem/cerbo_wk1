from typing import Protocol

from app.models import Order


class Fulfillment(Protocol):
    def ship(self, order: Order) -> None:
        """Hand a paid order to fulfillment."""


class FakeFulfillment:
    """Console stand-in. Records each shipped order id."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def ship(self, order: Order) -> None:
        print(f"would ship order #{order.id}")
        self.calls.append(order.id)

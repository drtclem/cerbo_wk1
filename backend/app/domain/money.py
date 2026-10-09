from collections.abc import Sequence
from dataclasses import dataclass

FEE_BPS_DEFAULT = 75
DONATION_BPS_OFF = 0
DONATION_BPS_ON = 500

_NEGATIVE_PAYOUT_DETAIL = "Price too low to cover the platform fee."
_DONATION_EXCEEDS_DETAIL = "Donation would leave the provider with a negative payout."


class PricingError(Exception):
    def __init__(self, code: str, detail: str, line_index: int | None = None) -> None:
        self.code = code
        self.detail = detail
        self.line_index = line_index
        super().__init__(detail)


@dataclass(frozen=True)
class LineInput:
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    has_research_fund: bool = False


@dataclass(frozen=True)
class LineSplit:
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int
    line_cogs_cents: int
    line_margin_cents: int
    donation_cents: int


@dataclass(frozen=True)
class OrderSplit:
    lines: tuple[LineSplit, ...]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    donation_bps: int
    donation_cents: int
    provider_payout_cents: int


def compute_fee(subtotal_cents: int, fee_bps: int) -> int:
    # Round half up. subtotal_cents >= 0, so floor division matches that rounding.
    return (subtotal_cents * fee_bps + 5_000) // 10_000


def line_donation_cents(line_margin_cents: int, donation_bps: int, has_research_fund: bool) -> int:
    """Per-line donation, floored. Zero when the product has no fund or bps is 0."""
    if not has_research_fund or donation_bps == 0:
        return 0
    return (line_margin_cents * donation_bps) // 10_000


def line_amounts(
    unit_price_cents: int, unit_cogs_cents: int, qty: int
) -> tuple[int, int, int]:
    """Display amounts for one line. The fee is not applied here."""
    line_total_cents = unit_price_cents * qty
    line_cogs_cents = unit_cogs_cents * qty
    return line_total_cents, line_cogs_cents, line_total_cents - line_cogs_cents


def compute_split(
    lines: Sequence[LineInput],
    fee_bps: int,
    donation_bps: int = DONATION_BPS_OFF,
) -> OrderSplit:
    priced: list[LineSplit] = []
    for line in lines:
        line_total_cents, line_cogs_cents, line_margin_cents = line_amounts(
            line.unit_price_cents, line.unit_cogs_cents, line.qty
        )
        priced.append(
            LineSplit(
                product_id=line.product_id,
                qty=line.qty,
                unit_price_cents=line.unit_price_cents,
                unit_cogs_cents=line.unit_cogs_cents,
                line_total_cents=line_total_cents,
                line_cogs_cents=line_cogs_cents,
                line_margin_cents=line_margin_cents,
                donation_cents=line_donation_cents(
                    line_margin_cents, donation_bps, line.has_research_fund
                ),
            )
        )
    subtotal_cents = sum(line.line_total_cents for line in priced)
    cogs_total_cents = sum(line.line_cogs_cents for line in priced)
    donation_cents = sum(line.donation_cents for line in priced)
    platform_fee_cents = compute_fee(subtotal_cents, fee_bps)
    return OrderSplit(
        lines=tuple(priced),
        subtotal_cents=subtotal_cents,
        cogs_total_cents=cogs_total_cents,
        fee_bps=fee_bps,
        platform_fee_cents=platform_fee_cents,
        donation_bps=donation_bps,
        donation_cents=donation_cents,
        provider_payout_cents=(
            subtotal_cents - cogs_total_cents - platform_fee_cents - donation_cents
        ),
    )


def validate_order(
    lines: Sequence[LineInput],
    fee_bps: int,
    donation_bps: int = DONATION_BPS_OFF,
) -> OrderSplit:
    """compute_split plus guardrails. The first failure wins."""
    if donation_bps not in (DONATION_BPS_OFF, DONATION_BPS_ON):
        raise PricingError(
            "INVALID_DONATION_BPS",
            "Donation rate must be 0 or 500 bps.",
            None,
        )
    if len(lines) == 0:
        raise PricingError("EMPTY_ORDER", "Order must contain at least one line.", None)

    for index, line in enumerate(lines):
        if line.qty < 1:
            raise PricingError("INVALID_QUANTITY", "Quantity must be at least 1.", index)

    for index, line in enumerate(lines):
        if line.unit_price_cents <= 0 or line.unit_cogs_cents <= 0:
            raise PricingError(
                "INVALID_PRICE",
                "Unit price and unit COGS must be positive cents.",
                index,
            )

    for index, line in enumerate(lines):
        if line.unit_price_cents < line.unit_cogs_cents:
            raise PricingError(
                "LINE_BELOW_COGS",
                "Unit price must be at least the unit cost.",
                index,
            )

    split = compute_split(lines, fee_bps, donation_bps)
    if split.provider_payout_cents < 0:
        # Blame the donation only if the order pays out without it; otherwise the
        # price itself is too low and turning the donation off would not help.
        if split.provider_payout_cents + split.donation_cents >= 0:
            raise PricingError("DONATION_EXCEEDS_PAYOUT", _DONATION_EXCEEDS_DETAIL, None)
        raise PricingError("NEGATIVE_PAYOUT", _NEGATIVE_PAYOUT_DETAIL, None)
    return split

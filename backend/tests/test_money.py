import ast
from collections.abc import Sequence
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.money import (
    DONATION_BPS_OFF,
    DONATION_BPS_ON,
    FEE_BPS_DEFAULT,
    LineInput,
    LineSplit,
    OrderSplit,
    PricingError,
    compute_fee,
    compute_split,
    validate_order,
)

_NEGATIVE_PAYOUT_DETAIL = "Price too low to cover the platform fee."
_DONATION_EXCEEDS_DETAIL = "Donation would leave the provider with a negative payout."
_MAX_UNIT_CENTS = 300_000  # a few thousand dollars
_MAX_QTY = 20


def _line(
    *,
    unit_price_cents: int,
    unit_cogs_cents: int,
    qty: int = 1,
    product_id: int = 1,
    has_research_fund: bool = False,
) -> LineInput:
    return LineInput(
        product_id=product_id,
        qty=qty,
        unit_price_cents=unit_price_cents,
        unit_cogs_cents=unit_cogs_cents,
        has_research_fund=has_research_fund,
    )


def _assert_int(value: object) -> None:
    assert isinstance(value, int) and not isinstance(value, bool)


def _assert_split(
    split: OrderSplit,
    *,
    subtotal_cents: int,
    cogs_total_cents: int,
    platform_fee_cents: int,
    provider_payout_cents: int,
    donation_cents: int = 0,
    donation_bps: int = DONATION_BPS_OFF,
) -> None:
    assert isinstance(split, OrderSplit)
    assert isinstance(split.lines, tuple)
    assert all(isinstance(line, LineSplit) for line in split.lines)
    for amount in (
        split.subtotal_cents,
        split.cogs_total_cents,
        split.platform_fee_cents,
        split.donation_cents,
        split.provider_payout_cents,
        split.fee_bps,
        split.donation_bps,
    ):
        _assert_int(amount)
    assert split.subtotal_cents == subtotal_cents
    assert split.cogs_total_cents == cogs_total_cents
    assert split.platform_fee_cents == platform_fee_cents
    assert split.donation_cents == donation_cents
    assert split.provider_payout_cents == provider_payout_cents
    assert split.fee_bps == FEE_BPS_DEFAULT
    assert split.donation_bps == donation_bps
    assert compute_fee(subtotal_cents, FEE_BPS_DEFAULT) == platform_fee_cents
    assert (
        split.subtotal_cents
        == split.cogs_total_cents
        + split.platform_fee_cents
        + split.donation_cents
        + split.provider_payout_cents
    )


def _validated(
    lines: Sequence[LineInput],
    *,
    donation_bps: int = DONATION_BPS_OFF,
) -> OrderSplit:
    split = validate_order(lines, FEE_BPS_DEFAULT, donation_bps)
    assert compute_split(lines, FEE_BPS_DEFAULT, donation_bps) == split
    assert len(split.lines) == len(lines)
    return split


def _rejected(
    lines: Sequence[LineInput],
    code: str,
    line_index: int | None,
    *,
    donation_bps: int = DONATION_BPS_OFF,
) -> PricingError:
    assert issubclass(PricingError, Exception)
    with pytest.raises(PricingError) as exc_info:
        validate_order(lines, FEE_BPS_DEFAULT, donation_bps)
    error = exc_info.value
    assert error.code == code
    assert error.line_index == line_index
    if code == "NEGATIVE_PAYOUT":
        assert error.detail == _NEGATIVE_PAYOUT_DETAIL
    elif code == "DONATION_EXCEEDS_PAYOUT":
        assert error.detail == _DONATION_EXCEEDS_DETAIL
    else:
        assert isinstance(error.detail, str)
    return error


def test_basic_order_fee_is_30_cents_and_payout_is_1970() -> None:
    assert FEE_BPS_DEFAULT == 75
    split = _validated((_line(unit_price_cents=4_000, unit_cogs_cents=2_000),))
    _assert_split(
        split,
        subtotal_cents=4_000,
        cogs_total_cents=2_000,
        platform_fee_cents=30,
        provider_payout_cents=1_970,
    )


def test_two_units_of_10_10_round_the_fee_once_per_order_to_15_cents() -> None:
    product_id = 17
    split = _validated(
        (
            _line(
                product_id=product_id,
                qty=2,
                unit_price_cents=1_010,
                unit_cogs_cents=500,
            ),
        )
    )
    _assert_split(
        split,
        subtotal_cents=2_020,
        cogs_total_cents=1_000,
        platform_fee_cents=15,
        provider_payout_cents=1_005,
    )
    assert split.platform_fee_cents != 16
    assert compute_fee(1_010, FEE_BPS_DEFAULT) * 2 == 16

    priced = split.lines[0]
    assert priced.product_id == product_id
    assert priced.qty == 2
    assert priced.unit_price_cents == 1_010
    assert priced.unit_cogs_cents == 500
    assert priced.line_total_cents == 2_020
    assert priced.line_cogs_cents == 1_000
    assert priced.line_margin_cents == 1_020
    for amount in (
        priced.product_id,
        priced.qty,
        priced.unit_price_cents,
        priced.unit_cogs_cents,
        priced.line_total_cents,
        priced.line_cogs_cents,
        priced.line_margin_cents,
    ):
        _assert_int(amount)


def test_10_10_subtotal_rounds_the_fee_up_to_8_cents() -> None:
    split = _validated((_line(unit_price_cents=1_010, unit_cogs_cents=500),))
    _assert_split(
        split,
        subtotal_cents=1_010,
        cogs_total_cents=500,
        platform_fee_cents=8,
        provider_payout_cents=502,
    )


def test_2_dollar_half_cent_tie_rounds_the_fee_up_to_2_cents() -> None:
    split = _validated((_line(unit_price_cents=200, unit_cogs_cents=100),))
    _assert_split(
        split,
        subtotal_cents=200,
        cogs_total_cents=100,
        platform_fee_cents=2,
        provider_payout_cents=98,
    )


def test_66_cent_subtotal_rounds_the_fee_to_zero() -> None:
    split = _validated((_line(unit_price_cents=66, unit_cogs_cents=30),))
    _assert_split(
        split,
        subtotal_cents=66,
        cogs_total_cents=30,
        platform_fee_cents=0,
        provider_payout_cents=36,
    )


def test_payout_of_exactly_zero_is_accepted() -> None:
    split = _validated((_line(unit_price_cents=10_000, unit_cogs_cents=9_925),))
    _assert_split(
        split,
        subtotal_cents=10_000,
        cogs_total_cents=9_925,
        platform_fee_cents=75,
        provider_payout_cents=0,
    )


def test_payout_one_cent_below_zero_is_rejected() -> None:
    _rejected(
        (_line(unit_price_cents=10_000, unit_cogs_cents=9_926),),
        "NEGATIVE_PAYOUT",
        None,
    )
    assert compute_fee(10_000, 75) == 75
    _assert_int(compute_fee(10_000, 75))


def test_compute_fee_is_2_cents_at_200_0_at_66_and_1_at_67() -> None:
    assert FEE_BPS_DEFAULT == 75
    tie = compute_fee(200, 75)
    zero = compute_fee(66, 75)
    one = compute_fee(67, 75)
    assert tie == 2
    assert zero == 0
    assert one == 1
    for fee in (tie, zero, one):
        _assert_int(fee)


def test_price_equal_to_cogs_on_every_line_is_negative_payout() -> None:
    # $20.00 subtotal: the fee is nonzero, so price == COGS cannot pay out.
    _rejected(
        (_line(unit_price_cents=2_000, unit_cogs_cents=2_000),),
        "NEGATIVE_PAYOUT",
        None,
    )


def test_line_below_cogs_reports_that_line_even_if_payout_would_be_positive() -> None:
    lines = (
        _line(product_id=1, unit_price_cents=5_000, unit_cogs_cents=1_000),
        _line(product_id=2, unit_price_cents=100, unit_cogs_cents=200),
    )
    _rejected(lines, "LINE_BELOW_COGS", 1)


@pytest.mark.parametrize("lines", [(), []], ids=["empty-tuple", "empty-list"])
def test_empty_order_is_rejected(lines: Sequence[LineInput]) -> None:
    _rejected(lines, "EMPTY_ORDER", None)


@pytest.mark.parametrize("qty", [0, -1])
def test_quantity_below_one_is_invalid_quantity(qty: int) -> None:
    _rejected(
        (_line(unit_price_cents=1_000, unit_cogs_cents=500, qty=qty),),
        "INVALID_QUANTITY",
        0,
    )


@pytest.mark.parametrize(
    ("unit_price_cents", "unit_cogs_cents"),
    [
        pytest.param(0, 500, id="unit-price-zero"),
        pytest.param(-1, 500, id="unit-price-negative"),
        pytest.param(500, 0, id="unit-cogs-zero"),
        pytest.param(500, -1, id="unit-cogs-negative"),
    ],
)
def test_non_positive_unit_price_or_cogs_is_invalid_price(
    unit_price_cents: int,
    unit_cogs_cents: int,
) -> None:
    _rejected(
        (
            _line(
                unit_price_cents=unit_price_cents,
                unit_cogs_cents=unit_cogs_cents,
                qty=1,
            ),
        ),
        "INVALID_PRICE",
        0,
    )


def test_zero_quantity_is_reported_before_price_below_cogs() -> None:
    _rejected(
        (_line(unit_price_cents=100, unit_cogs_cents=200, qty=0),),
        "INVALID_QUANTITY",
        0,
    )


def _spec_payout_cents(
    lines: Sequence[LineInput],
    fee_bps: int,
    donation_bps: int = DONATION_BPS_OFF,
) -> int:
    subtotal_cents = sum(line.unit_price_cents * line.qty for line in lines)
    cogs_total_cents = sum(line.unit_cogs_cents * line.qty for line in lines)
    fee_cents = (subtotal_cents * fee_bps + 5_000) // 10_000
    donation_cents = 0
    for line in lines:
        if line.has_research_fund and donation_bps:
            margin = (line.unit_price_cents - line.unit_cogs_cents) * line.qty
            donation_cents += (margin * donation_bps) // 10_000
    return subtotal_cents - cogs_total_cents - fee_cents - donation_cents


@st.composite
def _valid_orders(draw: st.DrawFn) -> tuple[tuple[LineInput, ...], int, int]:
    """Qty, prices, and COGS already satisfy the line rules. Payout is >= 0."""
    fee_bps = draw(st.one_of(st.just(75), st.integers(min_value=0, max_value=200)))
    donation_bps = draw(st.sampled_from([DONATION_BPS_OFF, DONATION_BPS_ON]))
    count = draw(st.integers(min_value=1, max_value=4))
    lines: list[LineInput] = []
    for _ in range(count):
        unit_price_cents = draw(st.integers(min_value=1, max_value=_MAX_UNIT_CENTS))
        lines.append(
            LineInput(
                product_id=draw(st.integers(min_value=1, max_value=10_000)),
                qty=draw(st.integers(min_value=1, max_value=_MAX_QTY)),
                unit_price_cents=unit_price_cents,
                unit_cogs_cents=draw(st.integers(min_value=1, max_value=unit_price_cents)),
                has_research_fund=draw(st.booleans()),
            )
        )
    if _spec_payout_cents(lines, fee_bps, donation_bps) < 0:
        # Move only the invalid draws into the valid region (COGS 1¢, price at
        # least $1) so the property is not fed orders validate_order rejects.
        lines = [
            LineInput(
                product_id=line.product_id,
                qty=line.qty,
                unit_price_cents=max(line.unit_price_cents, 100),
                unit_cogs_cents=1,
                has_research_fund=line.has_research_fund,
            )
            for line in lines
        ]
    return tuple(lines), fee_bps, donation_bps


@settings(max_examples=100)
@given(order=_valid_orders())
def test_valid_orders_keep_four_way_split_and_donation_at_most_five_percent_of_margin(
    order: tuple[tuple[LineInput, ...], int, int],
) -> None:
    lines, fee_bps, donation_bps = order
    subtotal_cents = sum(line.unit_price_cents * line.qty for line in lines)
    cogs_total_cents = sum(line.unit_cogs_cents * line.qty for line in lines)
    assume(_spec_payout_cents(lines, fee_bps, donation_bps) >= 0)

    split = validate_order(lines, fee_bps, donation_bps)

    assert split.subtotal_cents == subtotal_cents
    assert split.cogs_total_cents == cogs_total_cents
    assert (
        split.subtotal_cents
        == split.cogs_total_cents
        + split.platform_fee_cents
        + split.donation_cents
        + split.provider_payout_cents
    )
    assert split.platform_fee_cents == compute_fee(split.subtotal_cents, fee_bps)
    assert split.fee_bps == fee_bps
    assert split.donation_bps == donation_bps
    assert split.provider_payout_cents >= 0
    assert compute_split(lines, fee_bps, donation_bps) == split
    assert isinstance(split.lines, tuple)
    assert len(split.lines) == len(lines)
    margin_total = 0
    for source, priced in zip(lines, split.lines, strict=True):
        assert isinstance(priced, LineSplit)
        assert priced.product_id == source.product_id
        assert priced.qty == source.qty
        assert priced.unit_price_cents == source.unit_price_cents
        assert priced.unit_cogs_cents == source.unit_cogs_cents
        assert priced.line_total_cents == source.unit_price_cents * source.qty
        assert priced.line_cogs_cents == source.unit_cogs_cents * source.qty
        assert priced.line_margin_cents == priced.line_total_cents - priced.line_cogs_cents
        margin_total += priced.line_margin_cents
        if not source.has_research_fund or donation_bps == 0:
            assert priced.donation_cents == 0
        else:
            assert priced.donation_cents == (priced.line_margin_cents * donation_bps) // 10_000
        for amount in (
            split.subtotal_cents,
            split.cogs_total_cents,
            split.platform_fee_cents,
            split.donation_cents,
            split.provider_payout_cents,
            priced.line_total_cents,
            priced.line_cogs_cents,
            priced.line_margin_cents,
            priced.donation_cents,
        ):
            _assert_int(amount)
    assert split.donation_cents <= (margin_total * DONATION_BPS_ON) // 10_000



def test_inputs_and_splits_are_frozen() -> None:
    line = _line(unit_price_cents=4_000, unit_cogs_cents=2_000)
    assert line.qty == 1
    with pytest.raises(AttributeError):
        line.qty = 2
    split = validate_order((line,), FEE_BPS_DEFAULT)
    _assert_int(split.subtotal_cents)
    assert split.lines[0].line_total_cents == 4_000
    with pytest.raises(AttributeError):
        split.subtotal_cents = 0
    with pytest.raises(AttributeError):
        split.lines[0].line_total_cents = 0


def test_readme_order_donation_off_matches_today_and_on_matches_worked_example() -> None:
    """README Mag×2 + D3×1.

    Off: subtotal 6600, COGS 3300, fee 50, donation 0, payout 3250.
    On:  margins 2400 and 900 → donations (2400×500)//10000=120 and
         (900×500)//10000=45 → total 165; payout 3085.
    """
    lines = (
        _line(
            product_id=1,
            qty=2,
            unit_price_cents=2_400,
            unit_cogs_cents=1_200,
            has_research_fund=True,
        ),
        _line(
            product_id=2,
            qty=1,
            unit_price_cents=1_800,
            unit_cogs_cents=900,
            has_research_fund=True,
        ),
    )
    off = _validated(lines, donation_bps=DONATION_BPS_OFF)
    _assert_split(
        off,
        subtotal_cents=6_600,
        cogs_total_cents=3_300,
        platform_fee_cents=50,
        provider_payout_cents=3_250,
        donation_cents=0,
        donation_bps=DONATION_BPS_OFF,
    )
    assert tuple(line.donation_cents for line in off.lines) == (0, 0)

    on = _validated(lines, donation_bps=DONATION_BPS_ON)
    _assert_split(
        on,
        subtotal_cents=6_600,
        cogs_total_cents=3_300,
        platform_fee_cents=50,
        provider_payout_cents=3_085,
        donation_cents=165,
        donation_bps=DONATION_BPS_ON,
    )
    assert on.lines[0].line_margin_cents == 2_400
    assert on.lines[0].donation_cents == 120
    assert on.lines[1].line_margin_cents == 900
    assert on.lines[1].donation_cents == 45


def test_donation_rounds_down_per_line() -> None:
    # margin 199 → (199 × 500) // 10000 = 9
    split = _validated(
        (_line(unit_price_cents=1_199, unit_cogs_cents=1_000, has_research_fund=True),),
        donation_bps=DONATION_BPS_ON,
    )
    assert split.lines[0].line_margin_cents == 199
    assert split.lines[0].donation_cents == 9
    assert split.donation_cents == 9


def test_line_without_research_fund_donates_zero_when_donation_is_on() -> None:
    split = _validated(
        (
            _line(
                product_id=1,
                unit_price_cents=2_400,
                unit_cogs_cents=1_200,
                has_research_fund=False,
            ),
            _line(
                product_id=2,
                unit_price_cents=1_800,
                unit_cogs_cents=900,
                has_research_fund=True,
            ),
        ),
        donation_bps=DONATION_BPS_ON,
    )
    assert split.lines[0].donation_cents == 0
    assert split.lines[1].donation_cents == 45
    assert split.donation_cents == 45


def test_donation_exceeds_payout_only_when_the_order_pays_out_without_it() -> None:
    # $27.00 price, $26.80 COGS: margin 20, fee (2700×75+5000)//10000 = 20,
    # so payout is exactly 0 without a donation. Donation (20×500)//10000 = 1
    # would make it −1: the donation is what breaks it.
    thin = (_line(unit_price_cents=2_700, unit_cogs_cents=2_680, has_research_fund=True),)
    assert validate_order(thin, FEE_BPS_DEFAULT).provider_payout_cents == 0
    with pytest.raises(PricingError) as exc_info:
        validate_order(thin, FEE_BPS_DEFAULT, donation_bps=DONATION_BPS_ON)
    assert exc_info.value.code == "DONATION_EXCEEDS_PAYOUT"
    assert exc_info.value.detail == _DONATION_EXCEEDS_DETAIL


def test_price_too_low_is_negative_payout_even_with_donation_on() -> None:
    # $27.40 price, $27.20 COGS: margin 20, fee (2740×75+5000)//10000 = 21,
    # so payout is −1 before any donation (donation would be 1 → −2). The price
    # is the problem; turning the donation off would not help.
    too_low = (_line(unit_price_cents=2_740, unit_cogs_cents=2_720, has_research_fund=True),)
    split = compute_split(too_low, FEE_BPS_DEFAULT, DONATION_BPS_ON)
    assert (split.donation_cents, split.provider_payout_cents) == (1, -2)
    with pytest.raises(PricingError) as exc_info:
        validate_order(too_low, FEE_BPS_DEFAULT, donation_bps=DONATION_BPS_ON)
    assert exc_info.value.code == "NEGATIVE_PAYOUT"


def test_money_module_imports_nothing_from_fastapi_sqlalchemy_or_app() -> None:
    money_path = Path(__file__).resolve().parents[1] / "app" / "domain" / "money.py"
    tree = ast.parse(money_path.read_text(encoding="utf-8"), filename=str(money_path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _forbidden_import(alias.name):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                offenders.append("." * node.level + (node.module or ""))
            elif node.module is not None and _forbidden_import(node.module):
                offenders.append(node.module)
    assert offenders == []


def _forbidden_import(module: str) -> bool:
    root = module.split(".", 1)[0]
    return root in {"fastapi", "sqlalchemy", "app"}

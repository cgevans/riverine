"""Hypothesis strategies and helpers for property-based tests."""

from __future__ import annotations

import decimal
from decimal import Decimal
from math import isnan

from hypothesis import strategies as st

from riverine import Component
from riverine.units import DecimalQuantity, Q_, nM, uL


# `riverine.units` sets decimal.ExtendedContext (prec=9) at import time.
# Strategy arithmetic runs in a local higher-precision context so that
# intermediate quantize/divide steps don't silently produce NaN.
_HI_PREC = decimal.Context(prec=28, rounding=decimal.ROUND_HALF_EVEN)
_DEC_PLACES = 3


@st.composite
def decimal_values(
    draw,
    min_value: str = "0.01",
    max_value: str = "10000",
    places: int = _DEC_PLACES,
) -> Decimal:
    """Decimal values in [min_value, max_value], at most `places` fractional digits.

    `places` defaults to 3 — enough to get meaningful variety without pushing
    values past the 9-digit precision cap set by riverine's Decimal context.
    """
    with decimal.localcontext(_HI_PREC):
        lo = Decimal(min_value)
        hi = Decimal(max_value)
        scale = Decimal(10) ** places
        lo_i = int(lo * scale)
        hi_i = int(hi * scale)
    n = draw(st.integers(min_value=lo_i, max_value=hi_i))
    with decimal.localcontext(_HI_PREC):
        return (Decimal(n) / scale).quantize(Decimal(10) ** -places)


def volumes(min_uL: str = "1", max_uL: str = "1000") -> st.SearchStrategy[DecimalQuantity]:
    """μL volumes as `DecimalQuantity`."""
    return decimal_values(min_value=min_uL, max_value=max_uL).map(lambda d: Q_(d, uL))


def concentrations(
    min_nM: str = "1", max_nM: str = "100000"
) -> st.SearchStrategy[DecimalQuantity]:
    """nM concentrations as `DecimalQuantity`."""
    return decimal_values(min_value=min_nM, max_value=max_nM).map(lambda d: Q_(d, nM))


def component_names() -> st.SearchStrategy[str]:
    """Short ASCII names suitable for component identifiers."""
    return st.text(
        alphabet=st.characters(
            min_codepoint=ord("a"), max_codepoint=ord("z")
        ),
        min_size=1,
        max_size=8,
    )


@st.composite
def components(
    draw,
    name_strategy: st.SearchStrategy[str] = component_names(),
    conc_strategy: st.SearchStrategy[DecimalQuantity] = concentrations(),
) -> Component:
    return Component(draw(name_strategy), draw(conc_strategy))


def component_lists(
    min_size: int = 2,
    max_size: int = 6,
    conc_strategy: st.SearchStrategy[DecimalQuantity] = concentrations(),
) -> st.SearchStrategy[list[Component]]:
    """Lists of `Component` with unique names.

    Name uniqueness is enforced at list level to avoid validation errors that
    aren't the invariant under test (duplicate components fail Mix construction).
    """
    names = st.lists(
        component_names(), min_size=min_size, max_size=max_size, unique=True
    )
    return names.flatmap(
        lambda ns: st.tuples(*[conc_strategy for _ in ns]).map(
            lambda concs: [Component(n, c) for n, c in zip(ns, concs)]
        )
    )


def assert_decimal_close(
    a: DecimalQuantity,
    b: DecimalQuantity,
    rel_tol: str = "1e-6",
    abs_tol: str = "1e-9",
) -> None:
    """Assert two `DecimalQuantity` values are equal within a relative tolerance.

    Converts both to the units of `b` before comparing magnitudes; needed because
    `pint` may store compacted units (nM ↔ μM) after arithmetic.

    Default tolerance is 1e-6: riverine runs Decimal arithmetic at 9-digit
    precision, so anything tighter is noise.
    """
    with decimal.localcontext(_HI_PREC):
        a_m = Decimal(str(a.to(b.u).m))
        b_m = Decimal(str(b.m))
        if isnan(a_m) or isnan(b_m):
            assert isnan(a_m) and isnan(b_m), f"NaN mismatch: {a} vs {b}"
            return
        diff = abs(a_m - b_m)
        scale = max(abs(a_m), abs(b_m), Decimal(abs_tol))
        rel = diff / scale
        assert rel <= Decimal(rel_tol), (
            f"{a} ({a_m}) not close to {b} ({b_m}); diff={diff}, rel={rel}"
        )


def concentrations_list(
    min_size: int, max_size: int, min_nM: str = "1", max_nM: str = "100000"
) -> st.SearchStrategy[list[DecimalQuantity]]:
    return st.lists(
        concentrations(min_nM=min_nM, max_nM=max_nM),
        min_size=min_size,
        max_size=max_size,
    )


def volumes_list(
    min_size: int, max_size: int, min_uL: str = "1", max_uL: str = "1000"
) -> st.SearchStrategy[list[DecimalQuantity]]:
    return st.lists(
        volumes(min_uL=min_uL, max_uL=max_uL),
        min_size=min_size,
        max_size=max_size,
    )

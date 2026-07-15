from __future__ import annotations

import decimal
from decimal import Decimal
from typing import Sequence, TypeVar, Union, cast, overload

import pint
from pint import Quantity
from pint.facets.plain import PlainQuantity, PlainUnit
from typing_extensions import TypeAlias

# This needs to be here to make Decimal NaNs behave the way that NaNs
# *everywhere else in the standard library* behave (ExtendedContext clears
# the InvalidOperation/DivisionByZero traps). Precision is bumped from
# ExtendedContext's default 9 to match Python's default 28, so ordinary
# arithmetic doesn't silently fall into NaN when a result needs more than
# 9 significant digits.
_riverine_decimal_ctx = decimal.ExtendedContext.copy()
_riverine_decimal_ctx.prec = 28
decimal.setcontext(_riverine_decimal_ctx)

__all__ = [
    "ureg",
    "uL",
    "nM",
    "uM",
    "nmol",
    "Q_",
    "DNAN",
    "ZERO_VOL",
    "ZERO_CONC",
    "NAN_VOL",
    "Decimal",
    "Quantity",
    "DecimalQuantity",
]

ureg = pint.UnitRegistry(non_int_type=Decimal)
ureg.formatter.default_format = "~P"

uL = ureg.Unit("uL")
# µL = ureg.uL
uM = ureg.Unit("uM")
nM = ureg.Unit("nM")
nmol = ureg.Unit("nmol")

# A dimensionless "fold" concentration, written "x" (e.g. a 10x buffer).
ureg.define("fold = [] = x")

# Storage unit for a mass/volume concentration.
_MASS_CONC_UNIT = ureg.Unit("g/L")

DecimalQuantity: TypeAlias = Quantity # "PlainQuantity[Decimal]"


def is_concentration(q: Quantity) -> bool:
    """Whether `q` is a kind of concentration riverine tracks: a molarity, a
    mass/volume, or a dimensionless fold (x)."""
    return q.check(nM) or q.check(_MASS_CONC_UNIT) or q.dimensionless


def concentrations_same_kind(a: Quantity, b: Quantity) -> bool:
    """Whether two concentrations are the same kind (molarity, mass/volume, or
    fold), and so can be compared or combined."""
    return a.dimensionality == b.dimensionality


def canonical_concentration_unit(q: Quantity) -> pint.Unit:
    """The unit riverine stores `q`'s magnitude in, chosen by its kind."""
    if q.check(nM):
        return nM
    if q.check(_MASS_CONC_UNIT):
        return _MASS_CONC_UNIT
    if q.dimensionless:
        return ureg.Unit("x")
    raise ValueError(f"{q} is not a concentration.")


def Q_(
    qty: int | str | Decimal | float, unit: str | pint.Unit | PlainUnit | Quantity | None = None
) -> DecimalQuantity:
    "Convenient constructor for units, eg, :code:`Q_(5.0, 'nM')`.  Ensures that the quantity is a Decimal."
    if unit is not None:
        if isinstance(unit, Quantity):
            unit = unit.u
        return ureg.Quantity(Decimal(qty), unit)
    else:
        return ureg.Quantity(qty)


class VolumeError(ValueError):
    pass


DNAN = Decimal("nan")
ZERO_VOL = Q_("0.0", "µL")
NAN_VOL = Q_("nan", "µL")
ZERO_CONC = Q_("0.0", "nM")
NAN_CONC = Q_("nan", "nM")
NAN_AMOUNT = Q_("nan", "nmol")

T = TypeVar("T", bound=Union[float, Decimal])


@overload
def _ratio(
    top: Sequence[PlainQuantity[T]] | Sequence[DecimalQuantity], bottom: Sequence[PlainQuantity[T]] | Sequence[DecimalQuantity]
) -> Sequence[Union[float, Decimal]]:
    ...


@overload
def _ratio(
    top: PlainQuantity[T] | DecimalQuantity, bottom: Sequence[PlainQuantity[T]] | Sequence[DecimalQuantity]
) -> Sequence[Union[float, Decimal]]:
    ...


@overload
def _ratio(
    top: Sequence[PlainQuantity[T]] | Sequence[DecimalQuantity], bottom: PlainQuantity[T] | DecimalQuantity
) -> Sequence[Union[float, Decimal]]:
    ...


@overload
def _ratio(top: PlainQuantity[T] | DecimalQuantity, bottom: PlainQuantity[T] | DecimalQuantity) -> Union[float, Decimal]:
    ...


def _ratio(
    top: PlainQuantity[T] | Sequence[PlainQuantity[T]] | DecimalQuantity | Sequence[DecimalQuantity],
    bottom: PlainQuantity[T] | Sequence[PlainQuantity[T]] | DecimalQuantity | Sequence[DecimalQuantity],
) -> Union[float, Decimal] | Sequence[Union[float, Decimal]]:
    if isinstance(top, Sequence) and isinstance(bottom, Sequence):
        return [(x / y).m_as("") for x, y in zip(top, bottom)]
    elif isinstance(top, Sequence):
        return [(x / bottom).m_as("") for x in top]
    elif isinstance(bottom, Sequence):
        return [(top / y).m_as("") for y in bottom]
    return (top / bottom).m_as("")


_CONC_ERR = "should be a concentration (molarity, mass/volume, or fold/x)"


def _compact_conc(v: Quantity) -> DecimalQuantity:
    v = Q_(v.m, v.u)
    if v.dimensionless:
        return v
    return cast(DecimalQuantity, v.to_compact())


def _parse_conc_optional(v: str | Quantity | None) -> DecimalQuantity:
    """Parses a string or Quantity as a concentration; if None, returns a NaN
    concentration."""
    if isinstance(v, str):
        q = ureg.Quantity(v)
        if not is_concentration(q):
            raise ValueError(f"{v} is not a valid quantity here ({_CONC_ERR}).")
        return q
    elif isinstance(v, Quantity):
        if not is_concentration(v):
            raise ValueError(f"{v} is not a valid quantity here ({_CONC_ERR}).")
        return _compact_conc(v)
    elif v is None:
        return NAN_CONC
    raise ValueError


def _parse_conc_required(v: str | Quantity) -> DecimalQuantity:
    """Parses a string or Quantity as a concentration, requiring that
    it result in a value."""
    if isinstance(v, str):
        q = ureg.Quantity(v)
        if not is_concentration(q):
            raise ValueError(f"{v} is not a valid quantity here ({_CONC_ERR}).")
        return q
    elif isinstance(v, Quantity):
        if not is_concentration(v):
            raise ValueError(f"{v} is not a valid quantity here ({_CONC_ERR}).")
        return _compact_conc(v)
    raise ValueError(f"{v} is not a valid quantity here ({_CONC_ERR}).")


def _parse_vol_optional(v: str | Quantity) -> DecimalQuantity:
    """Parses a string or quantity as a volume, returning a NaN volume
    if the value is None.
    """
    # if isinstance(v, (float, int)):  # FIXME: was in quantitate.py, but potentially unsafe
    #    v = f"{v} µL"
    if isinstance(v, str):
        q = ureg.Quantity(v)
        if not q.check(uL):
            raise ValueError(f"{v} is not a valid quantity here (should be volume).")
        return q
    elif isinstance(v, Quantity):
        if not v.check(uL):
            raise ValueError(f"{v} is not a valid quantity here (should be volume).")
        v = Q_(v.m, v.u)
        return cast(DecimalQuantity, v.to_compact())
    elif v is None:
        return NAN_VOL
    raise ValueError


def _parse_vol_optional_none_zero(v: str | Quantity) -> DecimalQuantity:
    """Parses a string or quantity as a volume, returning a NaN volume
    if the value is None.
    """
    # if isinstance(v, (float, int)):  # FIXME: was in quantitate.py, but potentially unsafe
    #    v = f"{v} µL"
    if isinstance(v, str):
        q = ureg.Quantity(v)
        if not q.check(uL):
            raise ValueError(f"{v} is not a valid quantity here (should be volume).")
        return q
    elif isinstance(v, Quantity):
        if not v.check(uL):
            raise ValueError(f"{v} is not a valid quantity here (should be volume).")
        v = Q_(v.m, v.u)
        return cast(DecimalQuantity, v.to_compact())
    elif v is None:
        return ZERO_VOL
    raise ValueError


def _parse_vol_required(v: str | Quantity) -> DecimalQuantity:
    """Parses a string or quantity as a volume, requiring that it result in a
    value.
    """
    # if isinstance(v, (float, int)):
    #    v = f"{v} µL"
    if isinstance(v, str):
        q = ureg.Quantity(v)
        if not q.check(uL):
            raise ValueError(f"{v} is not a valid quantity here (should be volume).")
        return q
    elif isinstance(v, Quantity):
        if not v.check(uL):
            raise ValueError(f"{v} is not a valid quantity here (should be volume).")
        v = Q_(v.m, v.u)
        return cast(DecimalQuantity, v.to_compact())
    raise ValueError(f"{v} is not a valid quantity here (should be volume).")


def normalize(quantity: DecimalQuantity) -> DecimalQuantity:
    """
    Normalize `quantity` so that it is "compact" (uses units within the correct "3 orders of magnitude":
    https://pint.readthedocs.io/en/0.18/tutorial.html#simplifying-units)
    and eliminate trailing zeros.

    Parameters
    ----------

    quantity:
        a pint DecimalQuantity

    Returns
    -------
        `quantity` normalized to be compact and without trailing zeros.
    """
    quantity = cast(DecimalQuantity, quantity.to_compact())
    mag_int = quantity.magnitude.to_integral()
    if mag_int == quantity.magnitude:
        # can be represented exactly as integer, so return that;
        # quantity.magnitude.normalize() would use scientific notation in this case, which we don't want
        quantity = Q_(mag_int, quantity.units)
    else:
        # is not exact integer, so normalize will return normal float literal such as 10.2
        # and not scientific notation like it would for an integer
        mag_norm = quantity.magnitude.normalize()
        quantity = Q_(mag_norm, quantity.units)
    return quantity

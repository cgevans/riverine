from decimal import Decimal

import pint.testing
import pytest

from riverine import (
    Component,
    FillToVolume,
    FixedConcentration,
    FixedVolume,
    Mix,
    Q_,
    Strand,
    StoredMix,
    ToConcentration,
)
from riverine.abbreviated import uM, x
from riverine.units import (
    _parse_conc_optional,
    canonical_concentration_unit,
    is_concentration,
)


def assert_close(actual, expected):
    pint.testing.assert_allclose(actual, expected, Decimal("1e-9"), Decimal(0))


@pytest.mark.parametrize(
    "text,canonical",
    [
        ("200 uM", "nM"),
        ("10 x", "x"),
        ("5 g/L", "g/l"),
        ("2 mg/mL", "g/l"),
    ],
)
def test_parse_and_canonical(text, canonical):
    q = _parse_conc_optional(text)
    assert is_concentration(q)
    assert str(canonical_concentration_unit(q)) == canonical


def test_volume_is_not_a_concentration():
    with pytest.raises(ValueError):
        _parse_conc_optional("5 uL")


def test_fold_and_mass_tracked_through_mix():
    mix = Mix(
        [
            FixedConcentration(Strand("S1", "100 uM"), "1 uM"),
            FixedConcentration(Component("TE_10x", "10 x"), "1 x"),
            FixedConcentration(Component("BSA", "5 g/L"), "0.05 g/L"),
            FillToVolume("Buffer", "100 uL"),
        ],
        name="multiunit",
    )
    ac = mix.all_components()
    assert_close(Q_(ac.loc["S1", "concentration_nM"], ac.loc["S1", "concentration_unit"]), Q_(1, uM))
    assert_close(Q_(ac.loc["TE_10x", "concentration_nM"], ac.loc["TE_10x", "concentration_unit"]), Q_(1, x))
    assert_close(
        Q_(ac.loc["BSA", "concentration_nM"], ac.loc["BSA", "concentration_unit"]),
        Q_("0.05", "g/L"),
    )


def test_storedmix_fold_content_diluted():
    stock = StoredMix(
        "S1_stock",
        [Strand("S1", "200 uM"), Component("TE", "10 x")],
        fixed_concentration="S1",
    )
    mix = Mix(
        [FixedConcentration(stock, "50 nM"), FillToVolume("Buffer", "100 uL")],
        name="m",
    )
    ac = mix.all_components()
    # 50 nM / 200 uM = 1/4000; 10 x / 4000 = 0.0025 x
    assert_close(
        Q_(ac.loc["TE", "concentration_nM"], ac.loc["TE", "concentration_unit"]),
        Q_("0.0025", x),
    )


def test_fixed_concentration_kind_mismatch_errors():
    mix = Mix(
        [FixedConcentration(Component("X", "1 x"), "50 nM")],
        name="bad",
    )
    with pytest.raises(ValueError, match="different kind of unit"):
        mix.all_components()


def test_toconcentration_kind_mismatch_errors_when_rendering():
    mix = Mix(
        [
            ToConcentration(Component("X", "10 x"), "5 g/L"),
            FillToVolume("Buffer", "100 uL"),
        ],
        name="bad",
    )
    with pytest.raises(ValueError, match="different kind of unit"):
        mix.table()


def test_duplicate_component_kinds_across_actions_error():
    mix = Mix(
        [
            FixedVolume(Component("X", "10 x"), "1 uL"),
            FixedVolume(Component("X", "2 g/L"), "1 uL"),
        ],
        name="bad",
    )
    with pytest.raises(ValueError, match="different kinds"):
        mix.all_components()


def test_duplicate_component_kinds_within_stored_mix_error():
    stock = StoredMix(
        "stock",
        [Component("X", "10 x"), Component("X", "2 g/L")],
        fixed_concentration=Q_(10, x),
    )
    mix = Mix([FixedVolume(stock, "1 uL")], name="bad")
    with pytest.raises(ValueError, match="different kinds"):
        mix.all_components()


def test_mix_effective_concentration_keeps_unit():
    mix = Mix(
        [
            FixedConcentration(Component("TE_10x", "10 x"), "2 x"),
            FillToVolume("Buffer", "100 uL"),
        ],
        name="m",
        fixed_concentration="TE_10x",
    )
    assert_close(mix.concentration, Q_(2, x))

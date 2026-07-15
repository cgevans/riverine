import json
from decimal import Decimal

import pint.testing
import pytest

from riverine import (
    Component,
    Experiment,
    FillToVolume,
    FixedConcentration,
    FixedVolume,
    Mix,
    MultiFixedConcentration,
    Q_,
    Strand,
    StoredMix,
    nM,
    uM,
)
from riverine.dictstructure import _structure


def assert_close(actual, expected):
    pint.testing.assert_allclose(actual, expected, Decimal("1e-9"), Decimal(0))


def test_effective_concentration_default_first_content():
    s = StoredMix("stock", {"S1": "200 uM", "S2": "150 uM"})
    assert_close(s.concentration, Q_(200, uM))


def test_effective_concentration_by_name():
    s = StoredMix("stock", {"S1": "200 uM", "S2": "150 uM"}, fixed_concentration="S2")
    assert_close(s.concentration, Q_(150, uM))


def test_effective_concentration_fixed_quantity():
    s = StoredMix("stock", {"S1": "200 uM"}, fixed_concentration=Q_(90, uM))
    assert_close(s.concentration, Q_(90, uM))


def test_unknown_fixed_concentration_name():
    s = StoredMix("stock", {"S1": "200 uM"}, fixed_concentration="nope")
    with pytest.raises(ValueError):
        s.concentration


def test_strand_in_buffer_contributes_to_mix():
    # The carried buffer is a content like any other; if it has a concentration
    # it is diluted along with the strand and tracked in the mix.
    stock = StoredMix(
        "S1_stock", {"S1": "200 uM", "Mg": "200 mM"}, fixed_concentration="S1"
    )
    mix = Mix(
        [FixedConcentration(stock, "50 nM"), FillToVolume("Buffer", "100 uL")],
        name="mixA",
    )
    ac = mix.all_components()
    assert_close(Q_(ac.loc["S1", "concentration_magnitude"], nM), Q_(50, nM))
    # Mg is 200 mM in the stock; drawn at the same 50 nM / 200 uM ratio gives 50 uM.
    assert_close(Q_(ac.loc["Mg", "concentration_magnitude"], nM), Q_(50, uM))


def test_premade_mix_dilutes_all_contents_together():
    stock = StoredMix(
        "premade",
        {f"S{i}": "10 uM" for i in range(1, 5)},
        fixed_concentration="S1",
    )
    mix = Mix(
        [FixedConcentration(stock, "1 uM"), FillToVolume("Buffer", "40 uL")],
        name="mixB",
    )
    ac = mix.all_components()
    for i in range(1, 5):
        assert_close(Q_(ac.loc[f"S{i}", "concentration_magnitude"], nM), Q_(1, uM))


def test_from_mix_captures_contents():
    premade = Mix(
        [
            MultiFixedConcentration(
                [Strand(f"S{i}", "100 uM", sequence="ACGT") for i in range(1, 4)],
                "10 uM",
            ),
            FillToVolume("Buffer", "50 uL"),
        ],
        name="premade_mix",
    )
    stock = StoredMix.from_mix(premade, volume="50 uL")
    ac = stock.all_components()
    for i in range(1, 4):
        assert_close(Q_(ac.loc[f"S{i}", "concentration_magnitude"], nM), Q_(10, uM))


def test_from_mix_preserves_effective_concentration():
    premade = Mix(
        [
            FixedVolume(Component("A", "10 uM"), "1 uL"),
            FixedVolume(Component("B", "40 uM"), "1 uL"),
        ],
        name="premade_mix",
        fixed_concentration="B",
    )

    stocks = [StoredMix.from_mix(premade) for _ in range(10)]
    for stock in stocks:
        assert_close(stock.concentration, premade.concentration)


def test_volume_consumed_from_stock_not_contents():
    stock = StoredMix("S1_stock", {"S1": "200 uM"}, volume="20 uL")
    mix = Mix(
        [FixedConcentration(stock, "50 nM"), FillToVolume("Buffer", "100 uL")],
        name="mixA",
    )
    exp = Experiment(volume_checks=False)
    exp.add(stock)
    exp.add_mix(mix)
    vols = exp.consumed_and_produced_volumes()

    consumed, made = vols["S1_stock"]
    assert_close(made, Q_("20", "uL"))
    assert consumed.m > 0
    # The strand inside the stock is not itself tracked as consumed/made.
    assert "S1" not in vols


def test_stored_mix_roundtrip():
    stock = StoredMix(
        "premade",
        [Strand("S1", "10 uM", sequence="ACGT"), Component("Mg", "1 M")],
        fixed_concentration="S1",
        plate="freezer",
        well="B2",
        volume="50 uL",
    )
    d = json.loads(json.dumps(stock._unstructure()))
    back = _structure(d)
    assert back == stock


def test_stored_mix_quantity_fixed_concentration_roundtrip():
    stock = StoredMix(
        "premade",
        {"S1": "200 uM"},
        fixed_concentration=Q_(90, uM),
    )
    d = json.loads(json.dumps(stock._unstructure()))
    back = _structure(d)
    assert back == stock
    assert_close(back.concentration, Q_(90, uM))

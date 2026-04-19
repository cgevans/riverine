"""Solver behavior / acceptance tests.

These capture exact numerical results from the current solver and serve
as acceptance tests for the future Rust port.
"""

from decimal import Decimal

import pytest

from riverine import (
    Component,
    EqualConcentration,
    FillToVolume,
    FixedConcentration,
    FixedVolume,
    Mix,
    Q_,
    ToConcentration,
    VolumeError,
    ureg,
)


# --- Volume computation tests ---


def test_fixed_volume_total():
    """Total volume of a FixedVolume mix = sum of fixed volumes."""
    c1 = Component("c1", "100 nM")
    c2 = Component("c2", "200 nM")
    c3 = Component("c3", "300 nM")
    mix = Mix(FixedVolume([c1, c2, c3], "5 uL"), name="fv_test")

    assert mix.total_volume == Q_("15", "uL")


def test_fixed_concentration_volume():
    """FixedConcentration: each vol = mix_vol * (dest_conc / src_conc)."""
    c1 = Component("c1", "200 nM")
    c2 = Component("c2", "100 nM")
    mix = Mix(
        FixedConcentration([c1, c2], "20 nM"),
        name="fc_test",
        fixed_total_volume="50 uL",
    )

    vols = mix.actions[0].each_volumes(mix.total_volume, mix.actions)
    # c1: 50 * (20/200) = 5 uL
    assert vols[0] == Q_("5", "uL")
    # c2: 50 * (20/100) = 10 uL
    assert vols[1] == Q_("10", "uL")


def test_fill_to_volume():
    """FillToVolume: buffer = target - sum(others)."""
    c1 = Component("c1", "100 nM")
    c2 = Component("c2", "200 nM")
    mix = Mix(
        [FixedVolume([c1, c2], "5 uL")],
        name="ftv_test",
        fixed_total_volume="25 uL",
    )

    # Total from FixedVolume = 10 uL, buffer = 25 - 10 = 15 uL
    assert mix.total_volume == Q_("25", "uL")
    assert mix.buffer_volume == Q_("15", "uL")


def test_equal_concentration_min_volume():
    """EqualConcentration min_volume: highest-conc gets fixed_volume, others scaled up."""
    c1 = Component("c1", "200 nM")
    c2 = Component("c2", "100 nM")
    action = EqualConcentration([c1, c2], "5 uL", method="min_volume")

    mix = Mix(action, name="eq_min")
    vols = action.each_volumes(mix.total_volume, mix.actions)

    # c1 has highest conc (200 nM), gets 5 uL
    assert vols[0] == Q_("5", "uL")
    # c2 has half the conc, gets 2x volume = 10 uL
    assert vols[1] == Q_("10", "uL")


def test_equal_concentration_max_volume():
    """EqualConcentration max_volume: lowest-conc gets fixed_volume, others scaled down."""
    c1 = Component("c1", "200 nM")
    c2 = Component("c2", "100 nM")
    action = EqualConcentration([c1, c2], "5 uL", method="max_volume")

    mix = Mix(action, name="eq_max")
    vols = action.each_volumes(mix.total_volume, mix.actions)

    # c2 has lowest conc (100 nM), gets 5 uL
    assert vols[1] == Q_("5", "uL")
    # c1 has 2x the conc, gets half volume = 2.5 uL
    assert vols[0] == Q_("2.5", "uL")


def test_toconcentration_subtracts_existing():
    """ToConcentration: dest_conc = target - contributed by other actions."""
    c1 = Component("c1", "500 nM")
    c2 = Component("c2", "1000 nM")

    # FixedConcentration adds 10 nM of c1
    fc = FixedConcentration([c1], "10 nM")
    # ToConcentration should top up c1 to 50 nM, so it needs to add 40 nM more
    tc = ToConcentration([c2], "50 nM")

    mix = Mix([fc, tc], name="tc_test", fixed_total_volume="100 uL")

    # tc dest_concentrations should be [50 nM] since c2 is not in fc
    tc_dconcs = tc.dest_concentrations(mix.total_volume, mix.actions)
    assert tc_dconcs[0] == Q_("50", "nM")


def test_mixed_actions():
    """FixedVolume + FixedConcentration + FillToVolume together."""
    c1 = Component("c1", "200 nM")
    c2 = Component("c2", "100 nM")
    c3 = Component("c3", "500 nM")

    fv = FixedVolume([c1], "5 uL")
    fc = FixedConcentration([c2, c3], "10 nM")

    mix = Mix([fv, fc], name="mixed", fixed_total_volume="50 uL")

    assert mix.total_volume == Q_("50", "uL")

    fv_vols = fv.each_volumes(mix.total_volume, mix.actions)
    assert fv_vols == [Q_("5", "uL")]

    fc_vols = fc.each_volumes(mix.total_volume, mix.actions)
    # c2: 50 * (10/100) = 5 uL
    assert fc_vols[0] == Q_("5", "uL")
    # c3: 50 * (10/500) = 1 uL
    assert fc_vols[1] == Q_("1", "uL")

    # buffer = 50 - 5 - 5 - 1 = 39 uL
    assert mix.buffer_volume == Q_("39", "uL")


# --- Validation tests ---


def test_validate_fixed_conc_without_total_volume():
    """FixedConcentration without fixed_total_volume should produce validation error."""
    c1 = Component("c1", "100 nM")
    mix = Mix(FixedConcentration([c1], "10 nM"), name="no_vol")

    errors = mix.validate(tablefmt="pipe")
    error_messages = [str(e) for e in errors]
    assert any("fixed_total_volume must be specified" in msg for msg in error_messages)


def test_validate_negative_volume():
    """Negative volume should produce a validation error."""
    # Source conc too low for requested dest conc given the volume
    c1 = Component("c1", "10 nM")
    mix = Mix(
        FixedConcentration([c1], "100 nM"),
        name="neg_vol",
        fixed_total_volume="50 uL",
    )

    errors = mix.validate(tablefmt="pipe")
    error_messages = [str(e) for e in errors]
    assert any("higher transfer volume" in msg or "negative" in msg.lower() for msg in error_messages)


def test_validate_below_min_volume():
    """Transfer volume below min_volume should produce a validation error."""
    c1 = Component("c1", "10000 nM")
    mix = Mix(
        FixedConcentration([c1], "1 nM"),
        name="below_min",
        fixed_total_volume="10 uL",
        min_volume="0.5 uL",
    )

    # c1 vol = 10 * (1/10000) = 0.001 uL, well below min_volume of 0.5 uL
    errors = mix.validate(tablefmt="pipe")
    error_messages = [str(e) for e in errors]
    assert any("lower transfer volume" in msg for msg in error_messages)


def test_validate_transfer_exceeds_total():
    """Transfer volume exceeding total should produce a validation error."""
    c1 = Component("c1", "20 nM")
    c2 = Component("c2", "20 nM")
    c3 = Component("c3", "20 nM")
    # Each needs 10 * (15/20) = 7.5 uL, total = 22.5 uL > 10 uL
    mix = Mix(
        FixedConcentration([c1, c2, c3], "15 nM"),
        name="exceeds",
        fixed_total_volume="10 uL",
    )

    errors = mix.validate(tablefmt="pipe")
    error_messages = [str(e) for e in errors]
    assert any(
        "higher transfer volume" in msg or "negative" in msg.lower()
        for msg in error_messages
    )


def test_validate_intermediate_mix_insufficient():
    """Using more of an intermediate mix than it produces should fail in Experiment."""
    from riverine import Experiment

    c1 = Component("c1", "100 nM")
    inner = Mix(FixedVolume([c1], "5 uL"), name="inner")

    exp = Experiment()
    exp.add(inner, check_volumes=False)

    # inner produces 5 uL, but outer wants 10 uL of it
    outer = Mix(FixedVolume([inner], "10 uL"), name="outer")

    with pytest.raises(VolumeError):
        exp.add(outer, check_volumes=True)

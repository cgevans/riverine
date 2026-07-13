"""Tests for fill-to-volume / buffer handling: the rename, the shared base,
the single-determiner invariant, and the deprecation of the
``fixed_total_volume=`` / ``buffer_name=`` API.
"""

import pytest

from riverine import (
    Component,
    FillToVolume,
    FixedConcentration,
    FixedVolume,
    Mix,
    PipetteFillToVolume,
    AbstractFillToVolume,
    RiverineDeprecationWarning,
)
from riverine.dictstructure import _structure, _unstructure


def _comps():
    return [Component("c1", "200 nM"), Component("c2", "200 nM")]


# --- rename + alias ---------------------------------------------------------


def test_fill_to_volume_alias_is_pipette():
    assert FillToVolume is PipetteFillToVolume
    assert issubclass(PipetteFillToVolume, AbstractFillToVolume)


def test_pipette_fill_constructs_via_either_name():
    a = FillToVolume("TE", "25 uL")
    b = PipetteFillToVolume("TE", "25 uL")
    assert type(a) is type(b) is PipetteFillToVolume


# --- serialization: new and legacy class names ------------------------------


def test_serialization_roundtrip_new_name():
    m = Mix([FixedVolume(_comps(), "5 uL"), FillToVolume("TE", "25 uL")], name="y")
    m2 = _structure(_unstructure(m))
    assert m2._get_total_volume() == m._get_total_volume()
    assert m2._get_buffer_name() == "TE"


def test_serialization_accepts_legacy_class_name():
    m = Mix([FixedVolume(_comps(), "5 uL"), FillToVolume("TE", "25 uL")], name="y")
    d = _unstructure(m)

    def rewrite(o):
        if isinstance(o, dict):
            if o.get("class") == "PipetteFillToVolume":
                o["class"] = "FillToVolume"
            for v in o.values():
                rewrite(v)
        elif isinstance(o, list):
            for v in o:
                rewrite(v)

    rewrite(d)
    m3 = _structure(d)
    assert type(m3.actions[-1]) is PipetteFillToVolume
    assert m3._get_total_volume().m_as("uL") == 25


# --- Echo buffer_name detection (problem 4) ---------------------------------


def test_echo_fill_buffer_name_detected():
    pytest.importorskip("kithairon")
    from riverine import EchoFixedVolume, EchoFillToVolume

    comps = [Component("c1", "200 nM", plate="p1", well="A1")]
    m = Mix(
        [EchoFixedVolume(comps, "1 uL"), EchoFillToVolume("water", "25 uL")],
        name="x",
    )
    assert m._get_buffer_name() == "water"


# --- single-determiner invariant / recursion guard (problem 3) --------------


def test_two_pipette_fills_raise_valueerror_not_recursion():
    with pytest.raises(ValueError, match="at most one action"):
        Mix(
            [
                FixedVolume(_comps(), "5 uL"),
                PipetteFillToVolume("w1", "25 uL"),
                PipetteFillToVolume("w2", "40 uL"),
            ],
            name="x",
        )


def test_pipette_plus_echo_fill_raise_valueerror():
    pytest.importorskip("kithairon")
    from riverine import EchoFixedVolume, EchoFillToVolume

    comps = [Component("c1", "200 nM", plate="p1", well="A1")]
    with pytest.raises(ValueError, match="at most one action"):
        Mix(
            [
                EchoFixedVolume(comps, "1 uL"),
                EchoFillToVolume("w1", "25 uL"),
                PipetteFillToVolume("w2", "40 uL"),
            ],
            name="x",
        )


# --- deprecation: kwargs warn but work --------------------------------------


def test_fixed_total_volume_kwarg_warns():
    with pytest.warns(RiverineDeprecationWarning):
        m = Mix([FixedVolume(_comps(), "5 uL")], name="x", fixed_total_volume="25 uL")
    assert m._get_total_volume().m_as("uL") == 25


def test_buffer_name_kwarg_warns():
    with pytest.warns(RiverineDeprecationWarning):
        m = Mix(
            [FixedVolume(_comps(), "5 uL")],
            name="x",
            fixed_total_volume="25 uL",
            buffer_name="TE",
        )
    assert m._get_buffer_name() == "TE"


def test_property_get_and_set_warn():
    m = Mix([FixedVolume(_comps(), "5 uL"), FillToVolume("TE", "25 uL")], name="x")
    with pytest.warns(RiverineDeprecationWarning):
        _ = m.fixed_total_volume
    with pytest.warns(RiverineDeprecationWarning):
        _ = m.buffer_name
    with pytest.warns(RiverineDeprecationWarning):
        m.fixed_total_volume = "30 uL"
    assert m._get_total_volume().m_as("uL") == 30


def test_new_api_emits_no_deprecation_warning(recwarn):
    m = Mix([FixedVolume(_comps(), "5 uL"), FillToVolume("TE", "25 uL")], name="x")
    m.table()
    assert not [w for w in recwarn.list if issubclass(w.category, RiverineDeprecationWarning)]


# --- composition vs dual-setting (problems 1 and 2) -------------------------


def test_component_in_action_volume_in_kwarg_composes():
    # Previously a hard ValueError; now composes (with a deprecation warning).
    with pytest.warns(RiverineDeprecationWarning):
        m = Mix(
            [FixedVolume(_comps(), "5 uL"), FillToVolume("water")],
            name="x",
            fixed_total_volume="25 uL",
        )
    assert m._get_total_volume().m_as("uL") == 25
    assert m._get_buffer_name() == "water"


def test_dual_finite_volume_raises():
    with pytest.raises(ValueError, match="already determined"):
        Mix(
            [FixedVolume(_comps(), "5 uL"), FillToVolume("water", "25 uL")],
            name="x",
            fixed_total_volume="30 uL",
        )


def test_dual_finite_volume_raises_even_when_equal():
    with pytest.raises(ValueError, match="already determined"):
        Mix(
            [FixedVolume(_comps(), "5 uL"), FillToVolume("water", "25 uL")],
            name="x",
            fixed_total_volume="25 uL",
        )


def test_conflicting_buffer_name_raises():
    with pytest.raises(ValueError, match="already uses buffer"):
        Mix(
            [FixedVolume(_comps(), "5 uL"), FillToVolume("water")],
            name="x",
            fixed_total_volume="25 uL",
            buffer_name="TE",
        )


def test_agreeing_buffer_name_ok():
    with pytest.warns(RiverineDeprecationWarning):
        m = Mix(
            [FixedVolume(_comps(), "5 uL"), FillToVolume("TE")],
            name="x",
            fixed_total_volume="25 uL",
            buffer_name="TE",
        )
    assert m._get_buffer_name() == "TE"
    assert m._get_total_volume().m_as("uL") == 25


# --- setter no longer creates a zero-volume fill (problem 7) -----------------


def test_buffer_name_setter_without_fill_does_not_zero_volume():
    from math import isnan

    m = Mix([FixedVolume(_comps(), "5 uL")], name="x")
    with pytest.warns(RiverineDeprecationWarning):
        m.buffer_name = "TE"
    # A fill naming the buffer was added with an unset target: the volume is
    # underspecified (NaN), NOT forced to zero (the previous bug).
    assert isnan(m._get_total_volume().m)
    assert m._get_buffer_name() == "TE"

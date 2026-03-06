"""Round-trip serialization tests for components, actions, and mixes."""

import pytest

from riverine import (
    Component,
    EqualConcentration,
    Experiment,
    FillToVolume,
    FixedConcentration,
    FixedVolume,
    Mix,
    Q_,
    Strand,
    ToConcentration,
)
from riverine.dictstructure import _structure, _unstructure


@pytest.fixture
def experiment():
    """Minimal experiment for structuring context."""
    return Experiment()


def _roundtrip_component(comp, experiment=None):
    d = comp._unstructure(experiment)
    rebuilt = _structure(d, experiment)
    assert type(rebuilt) is type(comp)
    assert rebuilt.name == comp.name
    return rebuilt


def _roundtrip_action(action, experiment):
    d = action._unstructure(experiment)
    rebuilt = _structure(d, experiment)
    assert type(rebuilt) is type(action)
    return rebuilt


def test_component_roundtrip():
    c = Component("strand_a", "100 nM")
    rebuilt = _roundtrip_component(c)
    assert rebuilt.concentration == c.concentration


def test_component_with_location_roundtrip():
    c = Component("strand_b", "200 nM", plate="plate1", well="A3")
    rebuilt = _roundtrip_component(c)
    assert rebuilt.plate == "plate1"
    assert str(rebuilt.well) == "A3"
    assert rebuilt.concentration == c.concentration


def test_strand_roundtrip():
    s = Strand("oligo1", "150 nM", sequence="ATCGATCG")
    rebuilt = _roundtrip_component(s)
    assert isinstance(rebuilt, Strand)
    assert rebuilt.sequence == "ATCGATCG"
    assert rebuilt.concentration == s.concentration


def test_fixed_volume_roundtrip(experiment):
    comps = [Component("c1", "100 nM"), Component("c2", "200 nM")]
    action = FixedVolume(comps, "5 uL")
    rebuilt = _roundtrip_action(action, experiment)
    assert rebuilt.fixed_volume == action.fixed_volume
    assert len(rebuilt.components) == 2


def test_fixed_concentration_roundtrip(experiment):
    comps = [Component("c1", "100 nM"), Component("c2", "200 nM")]
    action = FixedConcentration(comps, "10 nM")
    rebuilt = _roundtrip_action(action, experiment)
    assert rebuilt.fixed_concentration == action.fixed_concentration
    assert len(rebuilt.components) == 2


def test_equal_concentration_roundtrip(experiment):
    comps = [Component("c1", "100 nM"), Component("c2", "200 nM")]
    for method in ["min_volume", "max_volume", "check"]:
        if method == "check":
            # check requires equal concentrations
            test_comps = [Component("c1", "100 nM"), Component("c2", "100 nM")]
        else:
            test_comps = comps
        action = EqualConcentration(test_comps, "5 uL", method=method)
        rebuilt = _roundtrip_action(action, Experiment())
        assert rebuilt.method == method
        assert rebuilt.fixed_volume == action.fixed_volume


def test_toconcentration_roundtrip(experiment):
    comps = [Component("c1", "500 nM")]
    action = ToConcentration(comps, "50 nM")
    rebuilt = _roundtrip_action(action, experiment)
    assert rebuilt.fixed_concentration == action.fixed_concentration


def test_filltovolume_roundtrip(experiment):
    action = FillToVolume("Buffer", "25 uL")
    rebuilt = _roundtrip_action(action, experiment)
    assert rebuilt.target_total_volume == action.target_total_volume
    assert rebuilt.components[0].name == "Buffer"


def test_simple_mix_roundtrip():
    c1 = Component("c1", "100 nM")
    c2 = Component("c2", "200 nM")
    mix = Mix(FixedVolume([c1, c2], "5 uL"), name="simple_mix")

    exp = Experiment()
    exp.add(mix, check_volumes=False)

    d = exp._unstructure()
    exp2 = Experiment._structure(d)

    assert exp2._unstructure() == exp._unstructure()


def test_multi_action_mix_roundtrip():
    c1 = Component("c1", "100 nM")
    c2 = Component("c2", "200 nM")
    c3 = Component("c3", "500 nM")
    mix = Mix(
        [FixedVolume([c1], "5 uL"), FixedConcentration([c2, c3], "20 nM")],
        name="multi_mix",
        fixed_total_volume="50 uL",
    )

    exp = Experiment()
    exp.add(mix, check_volumes=False)

    d = exp._unstructure()
    exp2 = Experiment._structure(d)

    assert exp2._unstructure() == exp._unstructure()


def test_nested_mix_roundtrip():
    c1 = Component("c1", "100 nM")
    c2 = Component("c2", "200 nM")
    inner = Mix(FixedVolume([c1, c2], "5 uL"), name="inner_mix")
    c3 = Component("c3", "500 nM")
    outer = Mix(
        FixedVolume([inner, c3], "3 uL"),
        name="outer_mix",
    )

    exp = Experiment()
    exp.add(inner, check_volumes=False)
    exp.add(outer, check_volumes=False)

    d = exp._unstructure()
    exp2 = Experiment._structure(d)

    assert exp2._unstructure() == exp._unstructure()

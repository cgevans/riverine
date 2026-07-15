import math
import re
from decimal import Decimal
from typing import cast

import pytest

from riverine import Q_, Component, Experiment, Mix, Reference, VolumeError, ureg
from riverine.abbreviated import FC, FV, C, Exp


@pytest.fixture
def experiment():
    exp = Exp()

    # We'll make some components:
    c1 = C("c1", "10 µM", plate="plate1", well="A1")
    c2 = C("c2", "10 µM", plate="plate1", well="A2")
    c3 = C("c3", "5 µM", plate="plate1", well="A3")
    c4 = C("c4", "5 µM", plate="plate2", well="B3")

    # Add a mix with add_mix
    exp.add_mix(FV([c2, c3], "10 µL"), "mix1")

    # Add a mix by assignment
    exp["mix2"] = Mix(FC([c1, c4], "1 µM"), fixed_total_volume="10 µL")

    # Add a mix that has a NaN value
    exp.add_mix(Mix(FC([c1], "1 µM"), "mix3"))

    # Add a mix with mixes, by reference
    exp.add_mix(
        FC(["mix1", "mix2", c3], "100 nM"), "mixmix", fixed_total_volume="90 µL"
    )

    return exp


def test_forward_reference():
    exp = Exp()

    exp.add_mix(Mix(FV(["mix1", "mix2"], "10 µL"), "mix3"))
    exp["mix1"] = Mix(FC(["c1", "c2"], "1 µM"), fixed_total_volume="10 µL")
    exp["mix2"] = Mix(FC(["c1", "c2"], "1 µM"), fixed_total_volume="10 µL")
    exp["c1"] = C("c1", "10 µM", plate="plate1", well="A1")

    exp.resolve_components()

    assert exp["mix3"].actions[0].components == [exp["mix1"], exp["mix2"]]


def test_use_reference():
    exp = Exp()

    exp["mix1"] = Mix(FC(["c1", "c2"], "1 µM"), fixed_total_volume="10 µL")
    exp["mix2"] = Mix(FC(["c1", "c2"], "1 µM"), fixed_total_volume="10 µL")
    exp.add_mix(Mix(FV(["mix1", "mix2"], "10 µL"), "mix3"))


def test_iterate_mixes(experiment):
    assert len(experiment) == 4
    assert list(experiment) == [
        experiment["mix1"],
        experiment["mix2"],
        experiment["mix3"],
        experiment["mixmix"],
    ]


def test_reference():
    r_platespec = Reference.compile("tests/data/holes-platespecs.xlsx")

    exp = Exp(reference=r_platespec)

    exp.add_mix(FC("h_4-13", "20 µM"), fixed_total_volume="100 µL", name="testmix")

    assert exp["testmix"].actions[0].each_volumes(exp["testmix"].total_volume) == [
        ureg("10 µL")
    ]


def test_delitem():
    exp = Exp()

    exp["mix1"] = Mix(FC(["a"], "1 µM"), fixed_total_volume="10 µL")

    del exp["mix1"]
    # FIXME: should check if deletion breaks links

    assert len(exp) == 0


def test_setitem_reference():
    r_platespec = Reference.compile("tests/data/holes-platespecs.xlsx")

    exp = Exp(reference=r_platespec)

    exp["testmix"] = Mix(
        FC("h_4-13", "20 µM"), fixed_total_volume="100 µL", name="testmix"
    )

    assert exp["testmix"].actions[0].each_volumes(exp["testmix"].total_volume) == [
        ureg("10 µL")
    ]


def test_post_reference():
    r_platespec = Reference.compile("tests/data/holes-platespecs.xlsx")

    exp = Exp()

    exp.add_mix(FC("h_4-13", "20 µM"), fixed_total_volume="100 µL", name="testmix")

    exp.reference = r_platespec

    assert exp["testmix"].actions[0].each_volumes(exp["testmix"].total_volume) == [
        ureg("10 µL")
    ]

    assert exp.reference == r_platespec


def test_consumed_and_produced_volumes(experiment):
    cp = experiment.consumed_and_produced_volumes()

    # c1 and mix3 can't be directly compared because they have NaN values
    assert math.isnan(cp["c1"][0].m)
    assert math.isnan(cp["mix3"][1].m)

    del cp["c1"]
    del cp["mix3"]

    assert cp == {
        "mix1": (ureg("1.80000 µL"), ureg("20 µL")),
        "mix2": (ureg("9 µL"), ureg("10 µL")),
        "mixmix": (ureg("0 µL"), 90 * ureg("µL")),
        "c2": (Decimal("10") * ureg("µL"), ureg("0.0 µL")),
        "c3": (Decimal("11.8") * ureg("µL"), ureg("0.0 µL")),
        "c4": (Decimal("2.0") * ureg("µL"), ureg("0.0 µL")),
        "Buffer": (ureg("84.4 µL"), ureg("0 µL")),
    }


def test_check_volumes(experiment, capsys):
    # First, try adding a mix that will cause a problem
    with pytest.raises(VolumeError):
        experiment.add_mix(
            Mix(FC(["mix2"], "100 nM"), "mixmix2", fixed_total_volume="100 µL")
        )

    with pytest.raises(VolumeError):
        experiment["mixmix2"] = Mix(
            FC(["mix2"], "100 nM"), "mixmix2", fixed_total_volume="100 µL"
        )

    assert "mixmix2" not in experiment

    experiment.add_mix(
        Mix(FC(["mix2"], "100 nM"), "mixmix2", fixed_total_volume="100 µL"),
        check_volumes=False,
    )

    experiment.check_volumes(showall=True)
    cvstring = capsys.readouterr().out
    assert re.search(
        r"Making 10 µl of mix2 but need at least 19(\.0*)? µl", cvstring, re.UNICODE
    )
    assert len([x for x in cvstring.splitlines() if x]) == 10
    experiment.remove_mix("mixmix2")


def test_add_single_component_returns_experiment():
    exp = Experiment(volume_checks=False)
    component = Component("component")

    assert exp.add(component) is exp
    assert exp.components == {"component": component}


def test_add_multiple_components_checks_volumes_once(monkeypatch):
    checked_components = []

    def record_check_volumes(self, *, display, raise_error):
        checked_components.append(list(self.components))

    monkeypatch.setattr(Experiment, "check_volumes", record_check_volumes)
    exp = Experiment()
    components = [Component("a"), Component("b"), Component("c")]

    assert exp.add(*components) is exp
    assert list(exp.components) == ["a", "b", "c"]
    assert checked_components == [["a", "b", "c"]]


def test_add_multiple_components_volume_check_options(monkeypatch):
    checks = []

    def record_check_volumes(self, *, display, raise_error):
        checks.append(list(self.components))

    monkeypatch.setattr(Experiment, "check_volumes", record_check_volumes)
    exp = Experiment(volume_checks=False)

    exp.add(Component("a"), Component("b"))
    exp.add(Component("c"), check_volumes=False)
    assert checks == []

    exp.volume_checks = True
    exp.add(Component("d"), Component("e"), check_volumes=None)
    assert checks == [["a", "b", "c", "d", "e"]]


def test_add_multiple_components_resolves_in_order_and_applies_reference():
    reference = Reference.from_csv("tests/data/test_reference.csv")
    exp = Experiment(reference=reference, volume_checks=False)
    base = Component("base", "1 uM")
    mixes = [
        Mix(FV(["base", "comp1"], "1 uL"), name="mix1"),
        Mix(FV(["base", "comp1"], "2 uL"), name="mix2"),
    ]

    exp.add(base, *mixes)

    assert list(exp.components) == ["base", "mix1", "mix2"]
    for mix in mixes:
        assert mix.actions[0].components[0] is base
        assert mix.actions[0].components[1].concentration == Q_("1000 nM")
        assert mix.actions[0].components[1].plate == "P 1"


@pytest.mark.parametrize(
    ("check_existing", "replacement", "message"),
    [
        (True, Component("duplicate", "1 uM"), "already exists in experiment\\.$"),
        ("equal", Component("duplicate", "1 uM"), "already exists in experiment\\.$"),
        (
            "equal",
            Component("duplicate", "2 uM"),
            "already exists in experiment, and is different\\.$",
        ),
    ],
)
def test_add_multiple_components_duplicate_error_is_atomic(
    check_existing, replacement, message
):
    original = Component("duplicate", "1 uM")
    exp = Experiment({"duplicate": original}, volume_checks=False)

    with pytest.raises(ValueError, match=message):
        exp.add(
            Component("new"),
            replacement,
            check_existing=check_existing,
        )

    assert list(exp.components.items()) == [("duplicate", original)]


def test_add_multiple_components_check_existing_false_replaces():
    original = Component("duplicate", "1 uM")
    replacement = Component("duplicate", "2 uM")
    new = Component("new")
    exp = Experiment({"duplicate": original}, volume_checks=False)

    exp.add(new, replacement, check_existing=False)

    assert list(exp.components.items()) == [
        ("duplicate", replacement),
        ("new", new),
    ]


def test_add_multiple_components_unnamed_component_is_atomic():
    original = Component("original")
    exp = Experiment({"original": original}, volume_checks=False)
    registry = exp.components

    with pytest.raises(ValueError, match="must have a name"):
        exp.add(Component("new"), Component(""))

    assert exp.components is registry
    assert list(exp.components.items()) == [("original", original)]


def test_add_multiple_components_preparation_error_is_atomic():
    reference = Reference.from_csv("tests/data/test_reference.csv")
    original = Component("original")
    exp = Experiment(
        {"original": original}, reference=reference, volume_checks=False
    )
    good = Mix(FV("comp1", "1 uL"), name="good")
    bad = Mix(FV(Component("comp1", "150 nM"), "1 uL"), name="bad")

    with pytest.raises(ValueError):
        exp.add(good, bad)

    assert list(exp.components.items()) == [("original", original)]


def test_add_multiple_components_volume_error_restores_replaced_entries():
    original = Component("original", "1 uM")
    inner = Mix(FV(Component("stock"), "5 uL"), name="inner")
    exp = Experiment(
        {"original": original, "inner": inner}, volume_checks=True
    )
    registry = exp.components
    replacement = Component("original", "2 uM")
    outer = Mix(FV("inner", "10 uL"), name="outer")

    with pytest.raises(VolumeError):
        exp.add(replacement, outer, check_existing=False)

    assert exp.components is registry
    assert list(exp.components.items()) == [
        ("original", original),
        ("inner", inner),
    ]


def test_unnamed_mix(experiment):
    with pytest.raises(ValueError):
        experiment.add_mix(Mix(FC(["a"], "1 µM"), fixed_total_volume="10 µL"))
    with pytest.raises(ValueError):
        experiment.add_mix(FC(["a"], "1 µM"), fixed_total_volume="10 µL")


def test_add_mix_already_present_no_check_existing(experiment: Experiment):
    experiment.add_mix(
        Mix(
            FC(["mix1", "mix2", "c3"], "97 nM"),
            "mixmix",
            fixed_total_volume="10 µL",
        ),
        check_existing=False,
    )
    m = cast(Mix, experiment["mixmix"])
    assert m.actions[0].fixed_concentration == Q_("97 nM")
    # with pytest


def test_add_mix_already_present_no_check_existing_weird_reference(
    experiment: Experiment,
):
    # c1 = experiment['c1']  # A direct reference to something already in the experiment
    # c4 will be a string reference to the experiment
    c5 = Component("c5", "2 µM")  # Something new!

    # Was 1 µM in the original experiment
    new_mix2 = Mix(FC(["c1", "c4", c5], "900 nM"), fixed_total_volume="10 µL")

    experiment.add_mix(
        Mix(
            FC(["mix1", new_mix2, "c3"], "97 nM"),
            "mixmix",
            fixed_total_volume="10 µL",
        ),
        check_existing=False,
    )
    m = cast(Mix, experiment["mixmix"])

    assert m.actions[0].fixed_concentration == Q_("97 nM")
    # FIXME: add more tests here


def test_add_mix_already_present(experiment):
    with pytest.raises(ValueError):
        experiment.add_mix(
            Mix(
                FC(["mix1", "mix2", "c3"], "100 nM"),
                "mixmix",
                fixed_total_volume="10 µL",
            )
        )
    # with pytest.raises(ValueError):
    #    experiment['mixmix'] = Mix(FC(["mix1", "mix2", "c3"], "100 nM"), "mixmix", fixed_total_volume="10 µL" )


def test_add_wrong_name(experiment):
    with pytest.raises(ValueError):
        experiment["mixA"] = Mix(
            [FC("mix1", "100 nM")], "mixB", fixed_total_volume="10 µL"
        )


def test_save_load(experiment, tmp_path):
    experiment.save(tmp_path / "test.json")

    e2 = Exp.load(tmp_path / "test.json")

    assert e2._unstructure() == experiment._unstructure()


def test_save_load_on_stream(experiment, tmp_path):
    with open(tmp_path / "test.json", "w") as f:
        experiment.save(f)

    with open(tmp_path / "test.json") as f:
        e2 = Exp.load(f)

    assert e2._unstructure() == experiment._unstructure()


def test_save_load_no_suffix(experiment, tmp_path):
    experiment.save(tmp_path / "test")

    assert (tmp_path / "test.json").exists()

    e2 = Exp.load(tmp_path / "test")

    assert e2._unstructure() == experiment._unstructure()


def test_load_invalid_json(experiment, tmp_path):
    with open(tmp_path / "test.json", "w") as f:
        f.write("{}")

    with pytest.raises(ValueError):
        Exp.load(tmp_path / "test.json")

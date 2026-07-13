import pytest

from riverine import Component, Experiment, Mix


def test_echo_experiment():
    pytest.importorskip('kithairon')
    from riverine import EchoTargetConcentration, EchoFixedVolume, EchoFillToVolume
    exp = Experiment()

    # We'll make some components:
    c1 = Component("c1", "10 µM", plate="plate1", well="A1")
    c2 = Component("c2", "10 µM", plate="plate1", well="A2")
    c3 = Component("c3", "5 µM", plate="plate1", well="A3")
    c4 = Component("c4", "5 µM", plate="plate2", well="B3")


    buffer = Component("Buffer", plate="bufferplate", well="A1")
    m = Mix(
        [
            EchoTargetConcentration([c1, c2, c3, c4], "1 nM"),
            EchoFillToVolume(buffer, "100 uL"),
        ],
        "testmix", plate="destplate", well="A1"
    )

    mstr = str(m)

    exp.add(m)

    p = exp.generate_picklist()


def test_echo_fill_to_volume_requires_buffer_location():
    pytest.importorskip('kithairon')
    from riverine import EchoTargetConcentration, EchoFillToVolume
    exp = Experiment()

    c1 = Component("c1", "10 µM", plate="plate1", well="A1")
    c2 = Component("c2", "10 µM", plate="plate1", well="A2")

    # A location-less (bare-string) buffer is not a valid Echo source.
    m = Mix(
        [
            EchoTargetConcentration([c1, c2], "1 nM"),
            EchoFillToVolume("Buffer", "100 uL"),
        ],
        "testmix", plate="destplate", well="A1"
    )
    exp.add(m)
    with pytest.raises(ValueError, match="no source location"):
        exp.generate_picklist()


@pytest.mark.parametrize("plate", ["", "   ", float("nan")])
def test_echo_fill_to_volume_rejects_invalid_buffer_plate(plate):
    pytest.importorskip('kithairon')
    from riverine import EchoTargetConcentration, EchoFillToVolume
    exp = Experiment()

    c1 = Component("c1", "10 µM", plate="plate1", well="A1")
    buffer = Component("Buffer", plate=plate, well="A2")
    m = Mix(
        [
            EchoTargetConcentration(c1, "1 nM"),
            EchoFillToVolume(buffer, "100 uL"),
        ],
        "testmix", plate="destplate", well="A1"
    )
    exp.add(m)

    with pytest.raises(ValueError, match="no source location"):
        exp.generate_picklist()


def test_echo_experiment_with_hand_fixed_volume():
    pytest.importorskip('kithairon')
    from riverine import EchoTargetConcentration, FillToVolume
    exp = Experiment()

    # We'll make some components:
    c1 = Component("c1", "10 µM", plate="plate1", well="A1")
    c2 = Component("c2", "10 µM", plate="plate1", well="A2")
    c3 = Component("c3", "5 µM", plate="plate1", well="A3")
    c4 = Component("c4", "5 µM", plate="plate2", well="B3")


    m = Mix(
        [
            EchoTargetConcentration([c1, c2, c3, c4], "1 nM"),
            FillToVolume("Buffer", "100 uL"),
        ],
        "testmix", plate="destplate", well="A1"
    )

    mstr = str(m)

    exp.add(m)

    p = exp.generate_picklist()

def test_echo_fixed_volume():
    pytest.importorskip('kithairon')
    from riverine import EchoFixedVolume

    # We'll make some components:
    c1 = Component("c1", "10 µM", plate="plate1", well="A1")
    c2 = Component("c2", "10 µM", plate="plate1", well="A2")
    c3 = Component("c3", "5 µM", plate="plate1", well="A3")
    c4 = Component("c4", "5 µM", plate="plate2", well="B3")

    m = Mix(
        [
            EchoFixedVolume([c1, c2, c3, c4], "1 uL")
        ],
        "testmix", plate="destplate", well="A1"
    )

    mstr = str(m)

    exp = Experiment()
    exp.add(m)

    p = exp.generate_picklist()

    # All transfer volumes should be 1000
    assert all(p.data["Transfer Volume"] == 1000)

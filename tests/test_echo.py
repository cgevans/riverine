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
            EchoTargetConcentration([c1, c2, c3, c4], "2.5 nM"),
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
            EchoTargetConcentration([c1, c2], "2.5 nM"),
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
            EchoTargetConcentration(c1, "2.5 nM"),
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
            EchoTargetConcentration([c1, c2, c3, c4], "2.5 nM"),
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


def test_echo_transfers_ignore_manual_mix_min_volume():
    pytest.importorskip("kithairon")
    from riverine import EchoFixedVolume, FixedVolume

    components = [
        Component(f"c{i}", "200 uM", plate="source", well=f"A{i}")
        for i in range(1, 12)
    ]
    manual_component = Component("manual", plate="tube")

    # This reproduces a compact row containing 11 acoustic transfers: each is
    # one 25 nL Echo droplet and the grouped row totals 275 nL. Neither volume
    # should be compared with Mix.min_volume, which is a manual-pipette limit.
    echo_mix = Mix(
        [
            FixedVolume(manual_component, "1 uL"),
            EchoFixedVolume(components, "25 nL"),
        ],
        "echo_below_manual_min",
        min_volume="500 nL",
    )

    echo_messages = [str(error) for error in echo_mix.validate(tablefmt="pipe")]
    assert not any("lower transfer volume" in message for message in echo_messages)
    assert "lower transfer volume" not in echo_mix.table()

    # Preserve the same warning for a genuinely manual sub-minimum transfer.
    manual_mix = Mix(
        FixedVolume(manual_component, "25 nL"),
        "manual_below_min",
        min_volume="500 nL",
    )
    manual_messages = [
        str(error) for error in manual_mix.validate(tablefmt="pipe")
    ]
    assert any("lower transfer volume" in message for message in manual_messages)


def test_echo_zero_fill_is_omitted_from_picklist():
    pytest.importorskip("kithairon")
    from riverine import EchoFillToVolume, EchoFixedVolume, FixedVolume

    reagent = Component("reagent", "100 uM", plate="source", well="A1")
    manual = Component("manual")
    buffer = Component("buffer", plate="reservoir", well="A1")
    mix = Mix(
        [
            FixedVolume(manual, "19 uL"),
            EchoFixedVolume(reagent, "1 uL"),
            EchoFillToVolume(buffer, "20 uL"),
        ],
        "already-full",
        plate="destination",
        well="A1",
    )
    experiment = Experiment()
    experiment.add(mix)

    picklist = experiment.generate_picklist()

    assert picklist.data.height == 1
    assert picklist.data["Sample Name"].to_list() == ["reagent"]
    assert picklist.data["Transfer Volume"].to_list() == [1000.0]


def test_all_zero_echo_transfers_return_typed_empty_picklist():
    pytest.importorskip("kithairon")
    import polars as pl
    from riverine import EchoFillToVolume

    # A zero transfer is a no-op and therefore needs no usable source location.
    mix = Mix(
        EchoFillToVolume("buffer", "0 uL"),
        "empty",
        plate="destination",
        well="A1",
    )
    experiment = Experiment()
    experiment.add(mix)

    picklist = experiment.generate_picklist()

    assert picklist.data.is_empty()
    assert picklist.data.schema["Transfer Volume"].is_float()
    assert picklist.data.schema["Destination Plate Name"] == pl.String


def test_echo_fill_tolerance_uses_final_target_volume():
    pytest.importorskip("kithairon")
    from riverine import EchoFillToVolume, FixedVolume

    manual = Component("manual")
    buffer = Component("buffer", plate="reservoir", well="A1")

    default_mix = Mix(
        [
            FixedVolume(manual, "19.99 uL"),
            EchoFillToVolume(buffer, "20 uL"),
        ],
        "default-fill-tolerance",
    )
    assert not any(
        "quantization tolerance" in str(error)
        for error in default_mix.validate(tablefmt="pipe")
    )

    strict_mix = Mix(
        [
            FixedVolume(manual, "19.99 uL"),
            EchoFillToVolume(buffer, "20 uL", rtol=0, atol="5 nL"),
        ],
        "strict-fill-tolerance",
        plate="destination",
        well="A1",
    )
    errors = strict_mix.validate(tablefmt="pipe")
    assert any(
        "error 0.010 µl, allowed 0.005 µl" in str(error)
        for error in errors
    )

    boundary_mix = Mix(
        [
            FixedVolume(manual, "19.99 uL"),
            EchoFillToVolume(buffer, "20 uL", rtol=0, atol="10 nL"),
        ],
        "boundary-fill-tolerance",
    )
    assert not any(
        "quantization tolerance" in str(error)
        for error in boundary_mix.validate(tablefmt="pipe")
    )


def test_echo_target_concentration_default_and_absolute_tolerances():
    pytest.importorskip("kithairon")
    from riverine import EchoTargetConcentration, PipetteFillToVolume

    component = Component("component", "1 uM", plate="source", well="A1")

    within_default = Mix(
        [
            EchoTargetConcentration(component, "1 nM"),
            PipetteFillToVolume("buffer", "25.25 uL"),
        ],
        "within-default",
    )
    assert not any(
        "quantization tolerance" in str(error)
        for error in within_default.validate(tablefmt="pipe")
    )

    outside_default = Mix(
        [
            EchoTargetConcentration(component, "1 nM"),
            PipetteFillToVolume("buffer", "25.26 uL"),
        ],
        "outside-default",
    )
    assert any(
        "quantization tolerance" in str(error)
        for error in outside_default.validate(tablefmt="pipe")
    )
    with pytest.raises(ValueError, match="quantization tolerance"):
        outside_default.generate_picklist(None)

    absolute = Mix(
        [
            EchoTargetConcentration(
                component, "1 nM", rtol=0, atol="0.01 nM"
            ),
            PipetteFillToVolume("buffer", "25.25 uL"),
        ],
        "absolute-tolerance",
    )
    assert not any(
        "quantization tolerance" in str(error)
        for error in absolute.validate(tablefmt="pipe")
    )


def test_echo_concentration_uses_realized_mix_volume():
    pytest.importorskip("kithairon")
    from riverine import EchoFillToVolume, EchoFixedVolume

    component = Component("component", "1 uM", plate="source", well="A1")
    buffer = Component("buffer", plate="reservoir", well="A1")
    fixed = EchoFixedVolume(component, "25 nL")
    mix = Mix(
        [fixed, EchoFillToVolume(buffer, "1.01 uL")],
        "realized-volume",
    )

    realized = fixed.dest_concentrations(mix.total_volume, mix.actions)[0]

    assert realized.m_as("nM") == 25
    assert not any(
        "quantization tolerance" in str(error)
        for error in mix.validate(tablefmt="pipe")
    )


def test_echo_equal_target_concentration_tolerance():
    pytest.importorskip("kithairon")
    from riverine import EchoEqualTargetConcentration

    c1 = Component("c1", "100 uM", plate="source", well="A1")
    c2 = Component("c2", "80 uM", plate="source", well="A2")
    strict = Mix(
        EchoEqualTargetConcentration([c1, c2], "25 nL"),
        "strict-equal",
    )
    assert any(
        "EchoEqualTargetConcentration for c2" in str(error)
        for error in strict.validate(tablefmt="pipe")
    )

    allowed = Mix(
        EchoEqualTargetConcentration([c1, c2], "25 nL", rtol="20%"),
        "allowed-equal",
    )
    assert not any(
        "quantization tolerance" in str(error)
        for error in allowed.validate(tablefmt="pipe")
    )

    checked = Mix(
        EchoEqualTargetConcentration(
            [c1, Component("c3", "100 uM", plate="source", well="A3")],
            "20 nL",
            method="check",
        ),
        "checked-equal",
    )
    assert any(
        "quantization tolerance" in str(error)
        for error in checked.validate(tablefmt="pipe")
    )


def test_echo_2_5_nl_droplets_avoid_zero_quantization():
    pytest.importorskip("kithairon")
    from riverine import EchoTargetConcentration, PipetteFillToVolume

    component = Component("component", "100 nM", plate="source", well="A1")
    default = Mix(
        [
            EchoTargetConcentration(component, "1 nM"),
            PipetteFillToVolume("buffer", "1 uL"),
        ],
        "25-nL-drops",
    )
    assert any(
        "quantization tolerance" in str(error)
        for error in default.validate(tablefmt="pipe")
    )

    fine = Mix(
        [
            EchoTargetConcentration(
                component, "1 nM", droplet_volume="2.5 nL"
            ),
            PipetteFillToVolume("buffer", "1 uL"),
        ],
        "2.5-nL-drops",
    )
    assert not any(
        "quantization tolerance" in str(error)
        for error in fine.validate(tablefmt="pipe")
    )


def test_echo_rejects_negative_and_non_multiple_transfers():
    pytest.importorskip("kithairon")
    from riverine import EchoFillToVolume, EchoFixedVolume, FixedVolume

    manual = Component("manual")
    buffer = Component("buffer", plate="reservoir", well="A1")
    overfilled = Mix(
        [
            FixedVolume(manual, "1.025 uL"),
            EchoFillToVolume(buffer, "1 uL"),
        ],
        "overfilled",
    )
    assert any(
        "negative Echo transfer" in str(error)
        for error in overfilled.validate(tablefmt="pipe")
    )

    component = Component("component", plate="source", well="A1")
    non_multiple = Mix(
        EchoFixedVolume(component, "10 nL"),
        "non-multiple",
        plate="destination",
        well="A1",
    )
    errors = non_multiple.validate(tablefmt="pipe")
    assert any("not an integer multiple" in str(error) for error in errors)
    with pytest.raises(ValueError, match="not an integer multiple"):
        non_multiple.generate_picklist(None)


def test_echo_rejects_invalid_quantization_settings():
    pytest.importorskip("kithairon")
    from riverine import EchoTargetConcentration

    component = Component("component", "100 nM")
    with pytest.raises(ValueError, match="rtol must be finite and nonnegative"):
        EchoTargetConcentration(component, "1 nM", rtol=-0.01)
    with pytest.raises(ValueError, match="atol must be finite and nonnegative"):
        EchoTargetConcentration(component, "1 nM", atol="-1 nM")
    with pytest.raises(ValueError, match="droplet_volume must be finite"):
        EchoTargetConcentration(component, "1 nM", droplet_volume="0 nL")

import json
import os
import subprocess
import sys

import pytest

from riverine import (
    Component,
    EchoStep,
    Experiment,
    ExperimentCompileError,
    FixedVolume,
    ManualStep,
    Mix,
    StoredMix,
)

pytest.importorskip("kithairon")

from riverine import EchoFixedVolume


def echo_stock(name: str, plate: str, well: str) -> Component:
    return Component(name, "100 uM", plate=plate, well=well)


def experiment_with(*mixes: Mix, **kwargs) -> Experiment:
    experiment = Experiment(volume_checks=False, **kwargs)
    experiment.add(*mixes, check_volumes=False)
    return experiment


def test_dependency_order_groups_manual_work_before_one_echo_run():
    first = echo_stock("first", "source", "A1")
    second = echo_stock("second", "source", "A2")
    mix = Mix(
        [
            EchoFixedVolume(first, "1 uL"),
            FixedVolume(Component("buffer"), "1 uL"),
            EchoFixedVolume(second, "1 uL"),
        ],
        "dependency-hybrid",
        plate="destination",
        well="A1",
    )

    plan = experiment_with(mix).compile()

    assert [type(step) for step in plan.steps] == [ManualStep, EchoStep]
    assert len(plan.echo_steps) == 1
    assert plan.echo_steps[0].actions == (mix.actions[0], mix.actions[2])


def test_listed_hybrid_preserves_manual_echo_manual_timeline():
    buffer = Component("buffer")
    reagent = echo_stock("reagent", "source", "A1")
    fluorophore = Component("fluorophore")
    mix = Mix(
        [
            FixedVolume(buffer, "1 uL"),
            EchoFixedVolume(reagent, "1 uL"),
            FixedVolume(fluorophore, "1 uL"),
        ],
        "listed-hybrid",
        plate="destination",
        well="A1",
        execution_order="listed",
    )

    plan = experiment_with(mix).compile()

    assert [type(step) for step in plan.steps] == [
        ManualStep,
        EchoStep,
        ManualStep,
    ]
    assert "buffer" in plan.manual_steps[0].instructions
    assert "fluorophore" not in plan.manual_steps[0].instructions
    assert "fluorophore" in plan.manual_steps[1].instructions
    assert "buffer" not in plan.manual_steps[1].instructions
    assert [step.id for step in plan.steps] == ["step-1", "step-2", "step-3"]


def test_echo_manual_echo_chain_compiles_to_two_runs():
    source = echo_stock("source", "source-plate", "A1")
    echo_intermediate = Mix(
        EchoFixedVolume(source, "1 uL"),
        "echo-intermediate",
        plate="intermediate-1",
        well="A1",
    )
    manual_intermediate = Mix(
        FixedVolume(echo_intermediate, "1 uL"),
        "manual-intermediate",
        plate="intermediate-2",
        well="A1",
    )
    product = Mix(
        EchoFixedVolume(manual_intermediate, "1 uL"),
        "product",
        plate="product-plate",
        well="A1",
    )
    experiment = experiment_with(echo_intermediate, manual_intermediate, product)

    plan = experiment.compile()

    assert [type(step) for step in plan.steps] == [EchoStep, ManualStep, EchoStep]
    assert [mix.name for mix in plan.steps[0].target_mixes] == ["echo-intermediate"]
    assert [mix.name for mix in plan.steps[1].target_mixes] == ["manual-intermediate"]
    assert [mix.name for mix in plan.steps[2].target_mixes] == ["product"]
    assert all(
        actual.data.equals(expected.data)
        for actual, expected in zip(
            experiment.generate_picklists(), plan.echo_picklists, strict=True
        )
    )
    with pytest.raises(ValueError, match="manual-intermediate"):
        experiment.generate_picklist()


def test_consecutive_manual_dependency_levels_do_not_create_empty_echo_runs():
    source = echo_stock("source", "source-plate", "A1")
    echo_intermediate = Mix(
        EchoFixedVolume(source, "1 uL"),
        "echo-intermediate",
        plate="intermediate-1",
        well="A1",
    )
    manual_one = Mix(
        FixedVolume(echo_intermediate, "1 uL"),
        "manual-one",
        plate="intermediate-2",
        well="A1",
    )
    manual_two = Mix(
        FixedVolume(manual_one, "1 uL"),
        "manual-two",
        plate="intermediate-3",
        well="A1",
    )
    product = Mix(
        EchoFixedVolume(manual_two, "1 uL"),
        "product",
        plate="product-plate",
        well="A1",
    )

    plan = experiment_with(
        echo_intermediate, manual_one, manual_two, product
    ).compile()

    assert [type(step) for step in plan.steps] == [
        EchoStep,
        ManualStep,
        ManualStep,
        EchoStep,
    ]
    assert len(plan.echo_steps) == 2


def test_ready_manual_actions_group_by_dependency_frontier_deterministically():
    a = Mix(FixedVolume(Component("a-stock"), "1 uL"), "a")
    x = Mix(FixedVolume(Component("x-stock"), "1 uL"), "x")
    b = Mix(FixedVolume(a, "1 uL"), "b")
    y = Mix(FixedVolume(x, "1 uL"), "y")

    plan = experiment_with(a, x, b, y).compile()

    assert [[mix.name for mix in step.target_mixes] for step in plan.manual_steps] == [
        ["a", "x"],
        ["b", "y"],
    ]


def test_stored_mix_is_available_stock_and_is_not_scheduled():
    stored = StoredMix(
        "frozen-stock",
        {"oligo": "100 uM"},
        plate="freezer-plate",
        well="A1",
    )
    product = Mix(FixedVolume(stored, "1 uL"), "product")
    experiment = Experiment(volume_checks=False)
    experiment.add(stored, product, check_volumes=False)

    plan = experiment.compile()

    assert len(plan.steps) == 1
    assert plan.manual_steps[0].target_mixes == (product,)


def test_explicit_echo_barrier_adds_run_in_listed_mix():
    first = echo_stock("first", "source-1", "A1")
    second = echo_stock("second", "source-2", "A1")
    mix = Mix(
        [
            EchoFixedVolume(first, "1 uL"),
            EchoFixedVolume(second, "1 uL", new_echo_run=True),
        ],
        "barrier",
        plate="destination",
        well="A1",
        execution_order="listed",
    )

    plan = experiment_with(mix).compile()

    assert len(plan.steps) == 2
    assert all(isinstance(step, EchoStep) for step in plan.steps)
    assert [step.actions for step in plan.echo_steps] == [
        (mix.actions[0],),
        (mix.actions[1],),
    ]


def test_echo_stages_order_a_same_run_and_emit_pass_metadata():
    stock = echo_stock("stock", "source", "A1")
    intermediate = Mix(
        EchoFixedVolume(stock, "1 uL", stage=1),
        "intermediate",
        plate="intermediate",
        well="A1",
    )
    product = Mix(
        EchoFixedVolume(intermediate, "1 uL", stage=2),
        "product",
        plate="product",
        well="A1",
    )

    plan = experiment_with(intermediate, product).compile()
    data = plan.echo_picklists[0].data

    assert len(plan.echo_steps) == 1
    assert data["Transfer Stage"].to_list() == [1, 2]
    assert data["Pass Index"].to_list() == [1, 2]
    assert data["segment_index"].to_list() == [0, 1]


def test_kithairon_optimization_stays_within_compiler_passes():
    class Plate:
        center_spacing_x = 450
        center_spacing_y = 450

    class Labware:
        def __getitem__(self, key):
            return Plate()

    first = [
        echo_stock("first-1", "source-1", "A1"),
        echo_stock("first-2", "source-1", "A2"),
    ]
    second = [
        echo_stock("second-1", "source-2", "B1"),
        echo_stock("second-2", "source-2", "B2"),
    ]
    mix = Mix(
        [
            EchoFixedVolume(first, "1 uL", stage=1),
            EchoFixedVolume(second, "1 uL", stage=2),
        ],
        "product",
        plate="destination",
        well="A1",
    )
    experiment = experiment_with(
        mix,
        locations={
            "source-1": {"echo_source_type": "SRC"},
            "source-2": {"echo_source_type": "SRC"},
            "destination": {"echo_dest_type": "DEST"},
        },
    )

    optimized = experiment.generate_picklist().optimize_well_transfer_order(Labware())
    groups = optimized.data.group_by("segment_index").agg(
        "Source Plate Name", "Destination Plate Name", "Transfer Stage", "Pass Index"
    )

    assert groups.height == 2
    for row in groups.iter_rows(named=True):
        assert len(set(row["Source Plate Name"])) == 1
        assert len(set(row["Destination Plate Name"])) == 1
        assert len(set(row["Transfer Stage"])) == 1
        assert len(set(row["Pass Index"])) == 1


def test_contradictory_echo_stages_report_dependency():
    stock = echo_stock("stock", "source", "A1")
    intermediate = Mix(
        EchoFixedVolume(stock, "1 uL", stage=2),
        "intermediate",
        plate="intermediate",
        well="A1",
    )
    product = Mix(
        EchoFixedVolume(intermediate, "1 uL", stage=1),
        "product",
        plate="product",
        well="A1",
    )

    with pytest.raises(ExperimentCompileError, match="contradicts.*dependencies"):
        experiment_with(intermediate, product).compile()


def test_unresolved_intermediate_reports_resolution_hint():
    product = Mix(FixedVolume("intermediate", "1 uL"), "product")
    intermediate = Mix(FixedVolume(Component("stock"), "1 uL"), "intermediate")
    experiment = Experiment(volume_checks=False)
    # This intentional forward reference remains a plain Component until resolved.
    experiment.add(product, intermediate, check_volumes=False)

    with pytest.raises(ExperimentCompileError, match="resolve_components"):
        experiment.compile()


def test_dependency_cycle_reports_action_path():
    a = Mix(FixedVolume(Component("stock"), "1 uL"), "a")
    b = Mix(FixedVolume(a, "1 uL"), "b")
    a.actions[0].components = [b]
    experiment = Experiment({"a": a, "b": b}, volume_checks=False)

    with pytest.raises(ExperimentCompileError, match="Dependency cycle detected") as error:
        experiment.compile()

    assert 'mix "a"' in str(error.value)
    assert 'mix "b"' in str(error.value)


def test_zero_volume_echo_actions_and_empty_steps_are_removed():
    mix = Mix(
        EchoFixedVolume(echo_stock("stock", "source", "A1"), "0 uL"),
        "empty",
        plate="destination",
        well="A1",
    )
    experiment = experiment_with(mix)

    plan = experiment.compile()
    picklist = experiment.generate_picklist()

    assert plan.steps == ()
    assert picklist.data.is_empty()
    assert {
        "Transfer Stage",
        "Pass Index",
        "segment_index",
    }.issubset(picklist.data.columns)


def test_plan_and_markdown_are_repeatable_and_echo_options_roundtrip():
    action = EchoFixedVolume(
        echo_stock("stock", "source", "A1"),
        "1 uL",
        stage=3,
        new_echo_run=True,
    )
    mix = Mix(
        action,
        "product",
        plate="destination",
        well="A1",
        execution_order="listed",
    )
    experiment = experiment_with(mix)

    first = experiment.compile()
    second = experiment.compile()
    assert first.to_markdown() == second.to_markdown()
    assert first.echo_picklists[0].data.equals(second.echo_picklists[0].data)

    serialized = experiment._unstructure()
    json.dumps(serialized)
    rebuilt = Experiment._structure(serialized)
    rebuilt_mix = rebuilt["product"]
    assert isinstance(rebuilt_mix, Mix)
    assert rebuilt_mix.execution_order == "listed"
    assert rebuilt_mix.actions[0].stage == 3
    assert rebuilt_mix.actions[0].new_echo_run is True


def test_compilation_is_identical_across_python_hash_seeds():
    script = r'''
from riverine import Component, EchoFixedVolume, Experiment, FixedVolume, Mix

source = Component("source", "100 uM", plate="source", well="A1")
manual = Mix(
    FixedVolume(Component("stock"), "1 uL"),
    "manual",
    plate="intermediate",
    well="A1",
)
echo = Mix(
    EchoFixedVolume([source, manual], "1 uL"),
    "echo",
    plate="destination",
    well="A1",
)
experiment = Experiment(volume_checks=False)
experiment.add(manual, echo, check_volumes=False)
print(experiment.compile().to_markdown())
'''
    outputs = []
    for seed in ("1", "937"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=os.getcwd(),
                env=environment,
                text=True,
            )
        )

    assert outputs[0] == outputs[1]

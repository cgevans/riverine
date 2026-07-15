"""Compilation of experiment recipes into executable manual and Echo steps."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import attrs
import polars as pl
from tabulate import tabulate

from .echo import AbstractEchoAction
from .mixes import MIXHEAD_EA, MIXHEAD_NO_EA, Mix
from .util import _get_picklist_class

__all__ = (
    "EchoStep",
    "ExperimentCompileError",
    "ExperimentPlan",
    "ExperimentStep",
    "ManualStep",
)

if TYPE_CHECKING:  # pragma: no cover
    from kithairon import PickList

    from .actions import AbstractAction
    from .experiments import Experiment


class ExperimentCompileError(ValueError):
    """An experiment cannot be compiled into a valid execution protocol."""


@attrs.frozen
class ManualStep:
    """A dependency-level group of manual actions."""

    id: str
    target_mixes: tuple[Mix, ...]
    actions: tuple[AbstractAction, ...]
    instructions: str
    dependency_reasons: tuple[str, ...] = ()

    @property
    def step_id(self) -> str:
        return self.id

    @property
    def identifier(self) -> str:
        return self.id

    @property
    def mixes(self) -> tuple[Mix, ...]:
        return self.target_mixes

    @property
    def targets(self) -> tuple[Mix, ...]:
        return self.target_mixes

    @property
    def source_actions(self) -> tuple[AbstractAction, ...]:
        return self.actions


@attrs.frozen
class EchoStep:
    """One uninterrupted Echo run."""

    id: str
    target_mixes: tuple[Mix, ...]
    actions: tuple[AbstractAction, ...]
    picklist: PickList
    dependency_reasons: tuple[str, ...] = ()

    @property
    def step_id(self) -> str:
        return self.id

    @property
    def identifier(self) -> str:
        return self.id

    @property
    def mixes(self) -> tuple[Mix, ...]:
        return self.target_mixes

    @property
    def targets(self) -> tuple[Mix, ...]:
        return self.target_mixes

    @property
    def source_actions(self) -> tuple[AbstractAction, ...]:
        return self.actions


ExperimentStep = ManualStep | EchoStep


@attrs.frozen
class ExperimentPlan:
    """Structured, ordered execution protocol for an experiment."""

    steps: tuple[ExperimentStep, ...]

    @property
    def manual_steps(self) -> tuple[ManualStep, ...]:
        return tuple(step for step in self.steps if isinstance(step, ManualStep))

    @property
    def echo_steps(self) -> tuple[EchoStep, ...]:
        return tuple(step for step in self.steps if isinstance(step, EchoStep))

    @property
    def echo_picklists(self) -> tuple[PickList, ...]:
        return tuple(step.picklist for step in self.echo_steps)

    def to_markdown(self) -> str:
        """Render the structured plan as a human-readable Markdown protocol."""
        if not self.steps:
            return "# Experiment protocol\n\nNo preparation steps are required."

        blocks = ["# Experiment protocol"]
        for ordinal, step in enumerate(self.steps, 1):
            if isinstance(step, ManualStep):
                step_blocks = [f"## Step {ordinal} — Manual ({step.id})"]
            else:
                step_blocks = [f"## Step {ordinal} — Echo run ({step.id})"]

            if step.dependency_reasons:
                step_blocks.append(
                    "Dependency reasons:\n"
                    + "\n".join(f"- {reason}" for reason in step.dependency_reasons)
                )

            if isinstance(step, ManualStep):
                step_blocks.append(step.instructions)
            else:
                count = step.picklist.data.height
                step_blocks.append(
                    f"Run the following Echo picklist ({count} transfers):\n\n"
                    + tabulate(
                        step.picklist.data.rows(),
                        headers=step.picklist.data.columns,
                        tablefmt="pipe",
                    )
                )
            blocks.append("\n\n".join(step_blocks))
        return "\n\n".join(blocks)


@dataclass(frozen=True)
class _Node:
    id: int
    kind: str
    mix_index: int
    mix: Mix
    action_index: int | None = None
    action: AbstractAction | None = None


_BASE_PICKLIST_SCHEMA: dict[str, pl.DataType] = {
    "Sample Name": pl.String,
    "Source Concentration": pl.Float64,
    "Destination Concentration": pl.Float64,
    "Concentration Units": pl.String,
    "Transfer Volume": pl.Float64,
    "Source Plate Name": pl.String,
    "Source Plate Type": pl.String,
    "Source Well": pl.String,
    "Destination Plate Name": pl.String,
    "Destination Plate Type": pl.String,
    "Destination Well": pl.String,
    "Destination Sample Name": pl.String,
    "Transfer Stage": pl.Int64,
    "Pass Index": pl.Int64,
    "segment_index": pl.Int64,
}


def empty_echo_picklist() -> PickList:
    """Return a typed empty picklist using the compiler's public schema."""
    PickList = _get_picklist_class()
    return PickList(pl.DataFrame(schema=_BASE_PICKLIST_SCHEMA))


class _Compiler:
    def __init__(self, experiment: Experiment):
        self.experiment = experiment
        self.nodes: dict[int, _Node] = {}
        self.successors: dict[int, set[int]] = {}
        self.predecessors: dict[int, set[int]] = {}
        self.edge_reasons: dict[tuple[int, int], str] = {}
        self.action_nodes: list[int] = []
        self.completion_by_mix: dict[int, int] = {}
        self.action_node_by_occurrence: dict[tuple[int, int], int] = {}
        self.barrier_predecessor: dict[int, int] = {}
        self._noop_cache: dict[int, bool] = {}
        self._build_graph()

    def compile(self) -> ExperimentPlan:
        self._raise_for_cycle()
        done: set[int] = set()
        raw_steps: list[tuple[str, list[int], dict[int, int] | None]] = []

        while len(done) < len(self.nodes):
            self._propagate_automatic(done)
            if len(done) == len(self.nodes):
                break

            ready = self._ready_actions(done)
            manual = [node_id for node_id in ready if not self._is_echo(node_id)]
            if manual:
                manual.sort(key=self._node_sort_key)
                physical = [node_id for node_id in manual if not self._is_noop(node_id)]
                done.update(manual)
                if physical:
                    raw_steps.append(("manual", physical, None))
                continue

            closure = self._echo_closure(done)
            if closure:
                ordered, generations = self._schedule_echo_closure(done, closure)
                done.update(ordered)
                if ordered:
                    raw_steps.append(("echo", ordered, generations))
                continue

            # No action can advance even though cycle validation succeeded. This
            # should only be reachable for a malformed graph; keep the diagnostic
            # actionable if a future node kind is added incorrectly.
            waiting = sorted(
                (node_id for node_id in self.action_nodes if node_id not in done),
                key=self._node_sort_key,
            )
            raise ExperimentCompileError(
                "Experiment compilation stalled while waiting for "
                + ", ".join(self._node_label(node_id) for node_id in waiting)
                + "."
            )

        steps: list[ExperimentStep] = []
        for kind, node_ids, generations in raw_steps:
            step_id = f"step-{len(steps) + 1}"
            reasons = self._dependency_reasons(node_ids)
            mixes = self._target_mixes(node_ids)
            actions = tuple(self.nodes[node_id].action for node_id in node_ids)
            if kind == "manual":
                steps.append(
                    ManualStep(
                        step_id,
                        mixes,
                        actions,  # type: ignore[arg-type]
                        self._render_manual_instructions(node_ids),
                        reasons,
                    )
                )
            else:
                assert generations is not None
                picklist, nonempty_nodes = self._build_echo_picklist(
                    node_ids, generations
                )
                if picklist.data.is_empty():
                    continue
                if len(nonempty_nodes) != len(node_ids):
                    mixes = self._target_mixes(nonempty_nodes)
                    actions = tuple(
                        self.nodes[node_id].action for node_id in nonempty_nodes
                    )
                    reasons = self._dependency_reasons(nonempty_nodes)
                steps.append(
                    EchoStep(
                        step_id,
                        mixes,
                        actions,  # type: ignore[arg-type]
                        picklist,
                        reasons,
                    )
                )

        # Empty Echo runs can only be discovered after action-level validation.
        # Renumber after removing them so identifiers remain sequential.
        renumbered: list[ExperimentStep] = []
        for index, step in enumerate(steps, 1):
            renumbered.append(attrs.evolve(step, id=f"step-{index}"))
        return ExperimentPlan(tuple(renumbered))

    def _build_graph(self) -> None:
        registered_mixes: list[tuple[int, str, Mix]] = []
        for registration_index, (registered_name, component) in enumerate(
            self.experiment.components.items()
        ):
            if not isinstance(component, Mix):
                continue
            if component.name != registered_name:
                raise ExperimentCompileError(
                    f'Prepared mix registry key "{registered_name}" does not match '
                    f'its mix name "{component.name}".'
                )
            registered_mixes.append((registration_index, registered_name, component))

        registry_by_name = {name: mix for _, name, mix in registered_mixes}
        next_id = 0
        for mix_index, (_, _, mix) in enumerate(registered_mixes):
            for action_index, action in enumerate(mix.actions):
                node = _Node(
                    next_id, "action", mix_index, mix, action_index, action
                )
                self._add_node(node)
                self.action_nodes.append(next_id)
                self.action_node_by_occurrence[(mix_index, action_index)] = next_id
                next_id += 1
            completion = _Node(next_id, "completion", mix_index, mix)
            self._add_node(completion)
            self.completion_by_mix[id(mix)] = next_id
            next_id += 1

        for mix_index, (_, _, mix) in enumerate(registered_mixes):
            completion_id = self.completion_by_mix[id(mix)]
            action_ids = [
                self.action_node_by_occurrence[(mix_index, action_index)]
                for action_index in range(len(mix.actions))
            ]
            for action_id in action_ids:
                self._add_edge(
                    action_id,
                    completion_id,
                    f'Mix "{mix.name}" is complete only after all of its actions.',
                )

            if mix.execution_order == "listed":
                for previous, current in zip(action_ids, action_ids[1:]):
                    previous_node = self.nodes[previous]
                    current_node = self.nodes[current]
                    self._add_edge(
                        previous,
                        current,
                        f'Mix "{mix.name}" uses execution_order="listed", so '
                        f"action {previous_node.action_index + 1} must precede "
                        f"action {current_node.action_index + 1}.",
                    )

                previous_echo: int | None = None
                for action_id in action_ids:
                    node = self.nodes[action_id]
                    if not isinstance(node.action, AbstractEchoAction):
                        continue
                    if node.action.new_echo_run and previous_echo is not None:
                        self.barrier_predecessor[action_id] = previous_echo
                    previous_echo = action_id

            for action_index, action in enumerate(mix.actions):
                consumer_id = self.action_node_by_occurrence[(mix_index, action_index)]
                for component_position, component in enumerate(action.components):
                    producer: Mix | None = None
                    if isinstance(component, Mix):
                        registered = registry_by_name.get(component.name)
                        if registered is None:
                            raise ExperimentCompileError(
                                f'Unresolved prepared mix "{component.name}" is consumed '
                                f"by action {action_index + 1} of mix \"{mix.name}\". "
                                "Add the prepared mix to the Experiment (or use StoredMix "
                                "for material that is already available)."
                            )
                        if registered is not component:
                            raise ExperimentCompileError(
                                f'Action {action_index + 1} of mix "{mix.name}" uses a '
                                f'different object named prepared mix "{component.name}". '
                                "Resolve the experiment components before compiling."
                            )
                        producer = component
                    elif component.name in registry_by_name:
                        raise ExperimentCompileError(
                            f'Unresolved intermediate "{component.name}" at component '
                            f"position {component_position + 1} of action "
                            f'{action_index + 1} in mix "{mix.name}". Call '
                            "Experiment.resolve_components() before compiling."
                        )

                    if producer is not None:
                        producer_completion = self.completion_by_mix[id(producer)]
                        self._add_edge(
                            producer_completion,
                            consumer_id,
                            f'Mix "{producer.name}" must be prepared before action '
                            f'{action_index + 1} of mix "{mix.name}" consumes it.',
                        )

    def _add_node(self, node: _Node) -> None:
        self.nodes[node.id] = node
        self.successors[node.id] = set()
        self.predecessors[node.id] = set()

    def _add_edge(self, source: int, destination: int, reason: str) -> None:
        self.successors[source].add(destination)
        self.predecessors[destination].add(source)
        self.edge_reasons[(source, destination)] = reason

    def _raise_for_cycle(self) -> None:
        state: dict[int, int] = {node_id: 0 for node_id in self.nodes}
        stack: list[int] = []

        def visit(node_id: int) -> list[int] | None:
            state[node_id] = 1
            stack.append(node_id)
            for successor in sorted(
                self.successors[node_id], key=self._node_sort_key
            ):
                if state[successor] == 0:
                    cycle = visit(successor)
                    if cycle is not None:
                        return cycle
                elif state[successor] == 1:
                    start = stack.index(successor)
                    return stack[start:] + [successor]
            stack.pop()
            state[node_id] = 2
            return None

        for node_id in sorted(self.nodes, key=self._node_sort_key):
            if state[node_id] != 0:
                continue
            cycle = visit(node_id)
            if cycle is None:
                continue
            details = []
            for source, destination in zip(cycle, cycle[1:]):
                details.append(
                    f"{self._node_label(source)} -> {self._node_label(destination)}: "
                    f"{self.edge_reasons[(source, destination)]}"
                )
            raise ExperimentCompileError(
                "Dependency cycle detected:\n" + "\n".join(details)
            )

    def _propagate_automatic(self, done: set[int]) -> None:
        changed = True
        while changed:
            changed = False
            for node_id in sorted(self.nodes, key=self._node_sort_key):
                if node_id in done:
                    continue
                if not self.predecessors[node_id].issubset(done):
                    continue
                node = self.nodes[node_id]
                if node.kind == "completion" or self._is_noop(node_id):
                    done.add(node_id)
                    changed = True

    def _ready_actions(self, done: set[int]) -> list[int]:
        return [
            node_id
            for node_id in self.action_nodes
            if node_id not in done and self.predecessors[node_id].issubset(done)
        ]

    def _is_echo(self, node_id: int) -> bool:
        return isinstance(self.nodes[node_id].action, AbstractEchoAction)

    def _is_noop(self, node_id: int) -> bool:
        if node_id in self._noop_cache:
            return self._noop_cache[node_id]
        node = self.nodes[node_id]
        if node.kind != "action" or node.action is None:
            self._noop_cache[node_id] = False
            return False
        mix_volume = node.mix._get_total_volume()
        volumes = node.action.each_volumes(mix_volume, node.mix.actions)
        result = bool(volumes) and all(
            not math.isnan(volume.m) and volume.m == 0 for volume in volumes
        )
        if not volumes:
            result = True
        self._noop_cache[node_id] = result
        return result

    def _echo_closure(self, done: set[int]) -> set[int]:
        local_done = set(done)
        closure: set[int] = set()
        while True:
            self._propagate_automatic(local_done)
            ready_echo = [
                node_id
                for node_id in self._ready_actions(local_done)
                if self._is_echo(node_id)
            ]
            candidates = []
            for node_id in ready_echo:
                barrier = self.barrier_predecessor.get(node_id)
                if (
                    barrier is not None
                    and barrier in closure
                    and not self._is_noop(barrier)
                ):
                    continue
                candidates.append(node_id)
            if not candidates:
                return closure
            candidates.sort(key=self._node_sort_key)
            closure.update(candidates)
            local_done.update(candidates)

    def _schedule_echo_closure(
        self, done: set[int], closure: set[int]
    ) -> tuple[list[int], dict[int, int]]:
        local_done = set(done)
        remaining = set(closure)
        ordered: list[int] = []
        generations: dict[int, int] = {}
        generation = 0

        while remaining:
            self._propagate_automatic(local_done)
            minimum_stage = min(self._stage_value(node_id) for node_id in remaining)
            ready = [
                node_id
                for node_id in remaining
                if self.predecessors[node_id].issubset(local_done)
                and self._stage_value(node_id) == minimum_stage
            ]
            if not ready:
                blocked = min(
                    (
                        node_id
                        for node_id in remaining
                        if self._stage_value(node_id) == minimum_stage
                    ),
                    key=self._node_sort_key,
                )
                blockers = sorted(
                    (
                        predecessor
                        for predecessor in self.predecessors[blocked]
                        if predecessor not in local_done
                    ),
                    key=self._node_sort_key,
                )
                blocker = blockers[0] if blockers else None
                if blocker is not None:
                    blocker = self._unfinished_action_ancestor(blocker, local_done)
                path = (
                    self._dependency_path(blocker, blocked)
                    if blocker is not None
                    else [blocked]
                )
                stage = self.nodes[blocked].action.stage  # type: ignore[union-attr]
                raise ExperimentCompileError(
                    f"Echo stage {stage!r} for {self._node_label(blocked)} "
                    "contradicts the action dependencies; it cannot run before "
                    f"{self._format_path(path)}."
                )
            ready.sort(key=self._node_sort_key)
            for node_id in ready:
                generations[node_id] = generation
            ordered.extend(ready)
            local_done.update(ready)
            remaining.difference_update(ready)
            generation += 1

        return ordered, generations

    def _stage_value(self, node_id: int) -> int:
        action = self.nodes[node_id].action
        assert isinstance(action, AbstractEchoAction)
        return 0 if action.stage is None else action.stage

    def _unfinished_action_ancestor(self, node_id: int, done: set[int]) -> int:
        """Find the stable unfinished action responsible for a blocked node."""
        queue: deque[int] = deque([node_id])
        seen = {node_id}
        while queue:
            current = queue.popleft()
            if self.nodes[current].kind == "action" and current not in done:
                return current
            for predecessor in sorted(
                self.predecessors[current], key=self._node_sort_key
            ):
                if predecessor in done or predecessor in seen:
                    continue
                seen.add(predecessor)
                queue.append(predecessor)
        return node_id

    def _dependency_path(self, source: int, destination: int) -> list[int]:
        queue: deque[int] = deque([source])
        parent: dict[int, int | None] = {source: None}
        while queue:
            current = queue.popleft()
            if current == destination:
                break
            for successor in sorted(
                self.successors[current], key=self._node_sort_key
            ):
                if successor in parent:
                    continue
                parent[successor] = current
                queue.append(successor)
        if destination not in parent:
            return [source, destination]
        path = []
        current: int | None = destination
        while current is not None:
            path.append(current)
            current = parent[current]
        return list(reversed(path))

    def _format_path(self, path: Sequence[int]) -> str:
        return " -> ".join(self._node_label(node_id) for node_id in path)

    def _build_echo_picklist(
        self, node_ids: Sequence[int], generations: dict[int, int]
    ) -> tuple[PickList, list[int]]:
        PickList = _get_picklist_class()
        frames: list[pl.DataFrame] = []
        nonempty_nodes: list[int] = []
        for node_id in node_ids:
            node = self.nodes[node_id]
            action = node.action
            assert isinstance(action, AbstractEchoAction)
            picklist = action.to_picklist(node.mix, self.experiment)
            if picklist.data.is_empty():
                continue
            nonempty_nodes.append(node_id)
            positions = self._transferred_component_positions(node_id)
            if len(positions) != picklist.data.height:
                positions = list(range(picklist.data.height))
            frames.append(
                picklist.data.with_columns(
                    pl.Series("__component_position", positions, dtype=pl.Int64),
                    pl.lit(generations[node_id]).alias("__dependency_generation"),
                    pl.lit(self._stage_value(node_id)).alias("__stage_sort"),
                    pl.lit(node.mix_index).alias("__mix_registration"),
                    pl.lit(node.action_index).alias("__action_position"),
                    pl.lit(self._stage_value(node_id), dtype=pl.Int64).alias(
                        "Transfer Stage"
                    ),
                )
            )

        if not frames:
            return empty_echo_picklist(), []

        data = pl.concat(frames, how="vertical").sort(
            [
                "__dependency_generation",
                "__stage_sort",
                "Source Plate Name",
                "Destination Plate Name",
                "__mix_registration",
                "__action_position",
                "__component_position",
            ],
            nulls_last=True,
        )

        pass_indexes: list[int] = []
        segment_indexes: list[int] = []
        previous_key: tuple[Any, ...] | None = None
        pass_index = 0
        for row in data.select(
            "__dependency_generation",
            "__stage_sort",
            "Source Plate Name",
            "Destination Plate Name",
        ).iter_rows():
            if previous_key is not None and row != previous_key:
                pass_index += 1
            previous_key = row
            pass_indexes.append(pass_index + 1)
            segment_indexes.append(pass_index)

        data = data.with_columns(
            pl.Series("Pass Index", pass_indexes, dtype=pl.Int64),
            pl.Series("segment_index", segment_indexes, dtype=pl.Int64),
        ).drop(
            "__dependency_generation",
            "__stage_sort",
            "__mix_registration",
            "__action_position",
            "__component_position",
        )
        return PickList(data), nonempty_nodes

    def _transferred_component_positions(self, node_id: int) -> list[int]:
        node = self.nodes[node_id]
        assert node.action is not None
        volumes = node.action.each_volumes(
            node.mix._get_total_volume(), node.mix.actions
        )
        return [
            index
            for index, volume in enumerate(volumes)
            if math.isnan(volume.m) or volume.m != 0
        ]

    def _render_manual_instructions(self, node_ids: Sequence[int]) -> str:
        sections: list[str] = []
        for mix in self._target_mixes(node_ids):
            mix_node_ids = [
                node_id for node_id in node_ids if self.nodes[node_id].mix is mix
            ]
            mixlines = []
            for node_id in mix_node_ids:
                action = self.nodes[node_id].action
                assert action is not None
                mixlines.extend(
                    action._mixlines(
                        tablefmt="pipe",
                        mix_vol=mix._get_total_volume(),
                        actions=mix.actions,
                    )
                )
            if not mixlines:
                continue
            include_numbers = any(line.number != 1 for line in mixlines)
            table = tabulate(
                [line.toline(include_numbers, tablefmt="pipe") for line in mixlines],
                MIXHEAD_EA if include_numbers else MIXHEAD_NO_EA,
                tablefmt="pipe",
            )
            sections.append(f'### Partial preparation of mix "{mix.name}"\n\n{table}')
        return "\n\n".join(sections)

    def _target_mixes(self, node_ids: Iterable[int]) -> tuple[Mix, ...]:
        found: dict[int, Mix] = {}
        for node_id in sorted(node_ids, key=self._node_sort_key):
            mix = self.nodes[node_id].mix
            found.setdefault(id(mix), mix)
        return tuple(found.values())

    def _dependency_reasons(self, node_ids: Sequence[int]) -> tuple[str, ...]:
        reasons: list[str] = []
        for node_id in sorted(node_ids, key=self._node_sort_key):
            predecessors = sorted(
                self.predecessors[node_id], key=self._node_sort_key
            )
            if not predecessors:
                node = self.nodes[node_id]
                reason = (
                    f'All inputs for action {node.action_index + 1} of mix '
                    f'"{node.mix.name}" are already available stock.'
                )
                if reason not in reasons:
                    reasons.append(reason)
            for predecessor in predecessors:
                reason = self.edge_reasons[(predecessor, node_id)]
                if reason not in reasons:
                    reasons.append(reason)
        return tuple(reasons)

    def _node_sort_key(self, node_id: int) -> tuple[int, int, int]:
        node = self.nodes[node_id]
        return (
            node.mix_index,
            len(node.mix.actions) if node.action_index is None else node.action_index,
            1 if node.kind == "completion" else 0,
        )

    def _node_label(self, node_id: int) -> str:
        node = self.nodes[node_id]
        if node.kind == "completion":
            return f'completion of mix "{node.mix.name}"'
        assert node.action is not None and node.action_index is not None
        return (
            f'action {node.action_index + 1} ({type(node.action).__name__}) '
            f'of mix "{node.mix.name}"'
        )


def compile_experiment(experiment: Experiment) -> ExperimentPlan:
    """Compile an experiment into a deterministic execution plan."""
    return _Compiler(experiment).compile()

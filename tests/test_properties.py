"""Property-based tests for riverine's solver and serialization.

These complement the example-based tests in `tests/test_solver_behavior.py`
and `tests/test_serialization.py` by generating diverse inputs via Hypothesis.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from riverine import (
    Component,
    FixedConcentration,
    FixedVolume,
    Mix,
    Q_,
)
from riverine.dictstructure import _structure, _unstructure
from riverine.solver import (
    compute_dest_concentrations,
    compute_fill_volume,
    compute_fixed_concentration_each,
)
from riverine.units import nM, uL

from strategies import (
    assert_decimal_close,
    component_names,
    components,
    concentrations,
    concentrations_list,
    decimal_values,
    volumes,
)


# Mix construction runs through pint's unit registry and attrs converters;
# the first few examples per process can exceed Hypothesis's default deadline.
proptest = settings(deadline=None, max_examples=100)


@proptest
@given(
    mix_vol=volumes(min_uL="10", max_uL="1000"),
    fixed_conc=concentrations(min_nM="1", max_nM="100"),
    ratios=st.lists(
        decimal_values(min_value="2", max_value="1000"),
        min_size=1,
        max_size=6,
    ),
)
def test_solver_fixed_concentration_round_trip(mix_vol, fixed_conc, ratios):
    """Feeding `compute_fixed_concentration_each` output into
    `compute_dest_concentrations` recovers the target concentration.

    Source concs are constructed as `fixed_conc * ratio` with ratio >= 2,
    so every transfer volume is well below `mix_vol`.
    """
    source_concs = [fixed_conc * r for r in ratios]

    each_vols = compute_fixed_concentration_each(mix_vol, fixed_conc, source_concs)
    dest_concs = compute_dest_concentrations(source_concs, each_vols, mix_vol)

    for dc in dest_concs:
        assert_decimal_close(dc, fixed_conc)


@proptest
@given(
    mix_vol_uL=decimal_values(min_value="10", max_value="1000"),
    fixed_conc_nM=decimal_values(min_value="1", max_value="100"),
    names=st.lists(component_names(), min_size=1, max_size=5, unique=True),
    ratios=st.lists(
        decimal_values(min_value="2", max_value="1000"),
        min_size=1,
        max_size=5,
    ),
)
def test_fixed_concentration_achieves_target_through_mix(
    mix_vol_uL, fixed_conc_nM, names, ratios
):
    """`FixedConcentration` acting inside a real `Mix` yields destination
    concentrations equal to `fixed_concentration` for every component.

    Uses the `Mix`/action wiring, not just the pure solver; catches bugs
    in how `each_volumes` and `dest_concentrations` thread through.
    """
    n = min(len(names), len(ratios))
    names = names[:n]
    ratios = ratios[:n]
    mix_vol = Q_(mix_vol_uL, uL)
    fixed_conc = Q_(fixed_conc_nM, nM)
    comps = [Component(nm, Q_(fixed_conc_nM * r, nM)) for nm, r in zip(names, ratios)]

    action = FixedConcentration(comps, fixed_conc)
    mix = Mix(action, name="fc_prop", fixed_total_volume=mix_vol)

    each_vols = action.each_volumes(mix.total_volume, mix.actions)
    dest_concs = compute_dest_concentrations(
        [c.concentration for c in comps], each_vols, mix.total_volume
    )
    for dc in dest_concs:
        assert_decimal_close(dc, fixed_conc)


@proptest
@given(
    total_uL=decimal_values(min_value="100", max_value="1000"),
    fv_uL=decimal_values(min_value="1", max_value="10"),
    n_components=st.integers(min_value=1, max_value=5),
    names=st.lists(component_names(), min_size=1, max_size=5, unique=True),
    concs=concentrations_list(min_size=1, max_size=5, min_nM="10", max_nM="10000"),
)
def test_mix_total_and_buffer_fill(total_uL, fv_uL, n_components, names, concs):
    """For a Mix with `fixed_total_volume = V` and one `FixedVolume` action
    pipetting N components at V_fv μL each, the total volume equals V and
    the buffer volume equals V - N*V_fv.

    Exercises `compute_fill_volume` + the Mix aggregation path.
    """
    n = min(n_components, len(names), len(concs))
    names = names[:n]
    concs = concs[:n]
    # Keep total of transfers well under fixed_total_volume.
    assert Decimal(n) * fv_uL < total_uL

    comps = [Component(nm, c) for nm, c in zip(names, concs)]
    mix = Mix(
        FixedVolume(comps, Q_(fv_uL, uL)),
        name="fill_prop",
        fixed_total_volume=Q_(total_uL, uL),
    )

    assert_decimal_close(mix.total_volume, Q_(total_uL, uL))
    expected_buffer = Q_(total_uL - Decimal(n) * fv_uL, uL)
    assert_decimal_close(mix.buffer_volume, expected_buffer)


@proptest
@given(comp=components())
def test_component_round_trip(comp):
    """`_unstructure` → `_structure` → `_unstructure` is idempotent on
    randomly generated `Component` instances."""
    d1 = comp._unstructure()
    rebuilt = _structure(dict(d1))
    assert type(rebuilt) is type(comp)
    assert rebuilt.name == comp.name
    d2 = rebuilt._unstructure()
    assert d1 == d2

"""Pure solver functions for mix volume/concentration computation.

These functions take numeric inputs and return numeric outputs, with no
dependency on Mix/Action objects. They will be replaced by Rust in Phase 1.
"""

from __future__ import annotations

import math
from typing import Literal, Sequence, cast

from .units import (
    ZERO_VOL,
    DecimalQuantity,
    NAN_VOL,
    Q_,
    VolumeError,
    _ratio,
    uL,
)

from .actions import MixVolumeDep


def compute_total_volume(
    action_effects: Sequence[tuple[MixVolumeDep, DecimalQuantity]],
) -> DecimalQuantity:
    """Determine total mix volume from action effects.

    Parameters
    ----------
    action_effects
        List of (MixVolumeDep, volume) tuples from each action.

    Returns
    -------
    DecimalQuantity
        The total volume of the mix.
    """
    indep_vol = Q_("0.0", uL)
    for effect, vol in action_effects:
        if effect == MixVolumeDep.DETERMINES:
            return vol
        elif effect == MixVolumeDep.INDEPENDENT:
            indep_vol += vol
        else:
            indep_vol = NAN_VOL
    return indep_vol


def compute_fixed_volume_each(
    fixed_volume: DecimalQuantity, n: int
) -> list[DecimalQuantity]:
    """FixedVolume: each component gets the same fixed volume.

    Parameters
    ----------
    fixed_volume
        Volume per component.
    n
        Number of components.
    """
    return [cast(DecimalQuantity, fixed_volume.to(uL))] * n


def compute_equal_concentration_each(
    fixed_volume: DecimalQuantity,
    source_concs: list[DecimalQuantity],
    method: Literal["min_volume", "max_volume", "check"] | tuple[Literal["max_fill"], str],
) -> list[DecimalQuantity]:
    """EqualConcentration: adjust volumes so all dest concentrations are equal.

    Parameters
    ----------
    fixed_volume
        The reference volume (min or max depending on method).
    source_concs
        Source concentration of each component.
    method
        "min_volume", "max_volume", "check", or ("max_fill", buffer_name).
    """
    if method == "min_volume":
        scmax = max(source_concs)
        return [fixed_volume * x for x in _ratio(scmax, source_concs)]
    elif method == "max_volume" or (
        isinstance(method, Sequence) and not isinstance(method, str) and method[0] == "max_fill"
    ):
        scmin = min(source_concs)
        return [fixed_volume * x for x in _ratio(scmin, source_concs)]
    elif method == "check":
        if any(x != source_concs[0] for x in source_concs):
            raise ValueError("Concentrations are not all equal.")
        return [cast(DecimalQuantity, fixed_volume.to(uL))] * len(source_concs)
    raise ValueError(f"method={method!r} not understood")


def compute_fixed_concentration_each(
    mix_vol: DecimalQuantity,
    fixed_conc: DecimalQuantity,
    source_concs: list[DecimalQuantity],
) -> list[DecimalQuantity]:
    """FixedConcentration: vol = mix_vol * (fixed_conc / src_conc).

    Parameters
    ----------
    mix_vol
        Total mix volume.
    fixed_conc
        Target destination concentration.
    source_concs
        Source concentration of each component.
    """
    return [mix_vol * r for r in _ratio(fixed_conc, source_concs)]


def compute_toconcentration_dest_concs(
    target_conc: DecimalQuantity,
    other_concs: list[DecimalQuantity],
) -> list[DecimalQuantity]:
    """ToConcentration: dest = target - already contributed.

    Parameters
    ----------
    target_conc
        Target total concentration for each component.
    other_concs
        Concentration already contributed by other actions, per component.
    """
    return [target_conc - other for other in other_concs]


def compute_fill_volume(
    target_vol: DecimalQuantity,
    other_vols_sum: DecimalQuantity,
) -> DecimalQuantity:
    """FillToVolume: buffer volume = target - sum(others).

    Parameters
    ----------
    target_vol
        Target total volume.
    other_vols_sum
        Sum of volumes from all other actions.
    """
    result = target_vol - other_vols_sum
    if math.isnan(result.m):
        return NAN_VOL
    return result


def compute_dest_concentrations(
    source_concs: list[DecimalQuantity],
    each_vols: list[DecimalQuantity],
    mix_vol: DecimalQuantity,
) -> list[DecimalQuantity]:
    """General dest concentration: dest_conc = src_conc * (transfer_vol / mix_vol).

    Parameters
    ----------
    source_concs
        Source concentration of each component.
    each_vols
        Transfer volume of each component.
    mix_vol
        Total mix volume.
    """
    return [sc * r for sc, r in zip(source_concs, _ratio(each_vols, mix_vol))]


def validate_mix(
    mixline_names_vols: list[tuple[list[str], DecimalQuantity | None]],
    total_vol: DecimalQuantity,
    min_volume: DecimalQuantity,
    has_fixed_concentration_action: bool,
    has_fixed_total_volume: bool,
    buffer_name: str,
    intermediate_mixes: list[tuple[str, DecimalQuantity, DecimalQuantity]],
) -> list[VolumeError]:
    """All validation checks on a solved mix.

    Parameters
    ----------
    mixline_names_vols
        List of (names, total_tx_vol) from each mixline.
    total_vol
        Total mix volume.
    min_volume
        Minimum acceptable transfer volume.
    has_fixed_concentration_action
        Whether any action is FixedConcentration.
    has_fixed_total_volume
        Whether the mix has a fixed total volume.
    buffer_name
        Name of the buffer component.
    intermediate_mixes
        List of (mix_name, mix_fixed_total_vol, needed_vol) for intermediate mix checks.
    """
    ntx = [(n, v) for n, v in mixline_names_vols if v is not None]
    error_list: list[VolumeError] = []

    if not has_fixed_total_volume and has_fixed_concentration_action:
        error_list.append(
            VolumeError(
                "If a FixedConcentration action is used, "
                "then Mix.fixed_total_volume must be specified."
            )
        )

    nan_vols = [", ".join(n) for n, x in ntx if math.isnan(x.m)]
    if nan_vols:
        error_list.append(
            VolumeError(
                "Some volumes aren't defined (mix probably isn't fully specified): "
                + "; ".join(x or "" for x in nan_vols)
                + "."
            )
        )

    high_vols = [(n, x) for n, x in ntx if not math.isnan(x.m) and x > total_vol]
    if high_vols:
        error_list.append(
            VolumeError(
                "Some items have higher transfer volume than total mix volume of "
                f"{total_vol} "
                "(target concentration probably too high for source): "
                + "; ".join(f"{', '.join(n)} at {x}" for n, x in high_vols)
                + "."
            )
        )

    for names, vol in [(n, v) for n, v in ntx if v is not None]:
        if math.isnan(vol.m) or vol == ZERO_VOL:
            continue
        if vol < min_volume:
            if names == [buffer_name]:
                msg = (
                    f"Negative buffer volume; "
                    f"this is typically caused by requesting too large a target concentration in a "
                    f"FixedConcentration action, "
                    f"since the source concentrations are too low. "
                    f"Try lowering the target concentration."
                )
            else:
                msg = (
                    f"Some items have lower transfer volume than {min_volume}\n"
                    f"attempting to pipette {vol} of these components:\n"
                    f"{names}"
                )
            error_list.append(VolumeError(msg))

    if ntx and not math.isnan(ntx[-1][1].m) and ntx[-1][1] < ZERO_VOL:
        error_list.append(
            VolumeError(
                f"Last mix component ({ntx[-1][0]}) has volume {ntx[-1][1]} < 0 µL. "
                "Component target concentrations probably too high."
            )
        )

    neg_vols = [(n, x) for n, x in ntx if not math.isnan(x.m) and x < ZERO_VOL]
    if neg_vols:
        error_list.append(
            VolumeError(
                "Some volumes are negative: "
                + "; ".join(f"{', '.join(n)} at {x}" for n, x in neg_vols)
                + "."
            )
        )

    for mix_name, mix_ftv, needed_vol in intermediate_mixes:
        if mix_ftv < needed_vol:
            error_list.append(
                VolumeError(
                    f'intermediate Mix "{mix_name}" needs {needed_vol}, '
                    f'but contains only {mix_ftv}.'
                )
            )

    return error_list

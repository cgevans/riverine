from __future__ import annotations

import math
from abc import ABCMeta
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, Literal, Sequence, cast

import attrs
import polars as pl
from tabulate import TableFormat

from riverine.util import gen_random_hash, maybe_cache_once

from .actions import (
    AbstractAction,
    AbstractFillToVolume,
    ActionWithComponents,
    MixVolumeDep,
    _STRUCTURE_CLASSES,
)
from .printing import MixLine

if TYPE_CHECKING:
    from kithairon.picklists import PickList
    from .mixes import Mix
    from .experiments import Experiment


from .units import (
    NAN_VOL,
    Q_,
    DecimalQuantity,
    VolumeError,
    _parse_conc_required,
    _parse_vol_optional,
    _parse_vol_required,
    _ratio,
    canonical_concentration_unit,
    uL,
)

try:
    from kithairon.picklists import PickList  # type: ignore
except ImportError as err:
    if err.name != "kithairon":
        raise err
    raise ImportError(
        "kithairon is required for Echo support, but it is not installed.",
        name="kithairon",
    )


DEFAULT_DROPLET_VOL = Q_(25, "nL")
DEFAULT_RTOL = Decimal("0.01")


def _parse_rtol(value: Decimal | float | int | str | DecimalQuantity) -> Decimal:
    """Parse a nonnegative, dimensionless relative tolerance."""
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (float, int)) and not isinstance(value, bool):
        result = Decimal(str(value))
    elif isinstance(value, (str, DecimalQuantity)):
        quantity = Q_(value) if isinstance(value, str) else value
        if not quantity.dimensionless:
            raise ValueError("rtol must be dimensionless (a fraction or percentage).")
        result = Decimal(quantity.to("").m)
    else:
        raise ValueError("rtol must be a fraction or percentage.")

    if not result.is_finite() or result < 0:
        raise ValueError("rtol must be finite and nonnegative.")
    return result


def _parse_atol(
    value: str | DecimalQuantity | int | None,
) -> DecimalQuantity | None:
    """Parse an absolute tolerance, leaving its units target-dependent."""
    if value is None:
        return None
    if value == 0:
        return Q_(0)
    if isinstance(value, str):
        result = Q_(value)
    elif isinstance(value, DecimalQuantity):
        result = value
    else:
        raise ValueError("atol must be a quantity with units (or zero).")
    if not Decimal(result.m).is_finite() or result.m < 0:
        raise ValueError("atol must be finite and nonnegative.")
    return result


def _parse_droplet_volume(value: str | DecimalQuantity) -> DecimalQuantity:
    result = _parse_vol_required(value)
    if not Decimal(result.m).is_finite() or result.m <= 0:
        raise ValueError("droplet_volume must be finite and greater than zero.")
    if result == DEFAULT_DROPLET_VOL:
        return DEFAULT_DROPLET_VOL
    return result


@attrs.define(eq=False)
class AbstractEchoAction(ActionWithComponents, metaclass=ABCMeta):
    """Abstract base class for Echo actions.

    ``rtol`` is a dimensionless relative tolerance and defaults to 1%.  It may
    be supplied as a fraction or percentage string.  ``atol`` defaults to zero
    and must use units appropriate to the concrete action's target: volume for
    a fill and concentration for a concentration-targeting action. ``stage``
    gives an optional global ordering stage within a compiled Echo run.
    ``new_echo_run=True`` starts a new run before the action when it follows an
    Echo action in a mix whose ``execution_order`` is ``"listed"``.
    """

    rtol: ClassVar[Decimal]
    atol: ClassVar[DecimalQuantity | None]
    stage: int | None = attrs.field(
        default=None,
        kw_only=True,
        validator=attrs.validators.optional(attrs.validators.instance_of(int)),
    )
    new_echo_run: bool = attrs.field(
        default=False,
        kw_only=True,
        validator=attrs.validators.instance_of(bool),
    )

    def _realized_mix_volume(
        self,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction],
        _cache_key=None,
    ) -> DecimalQuantity:
        """Return the volume physically delivered after Echo quantization."""
        if not actions:
            return mix_vol
        return sum(
            (
                action.tx_volume(
                    mix_vol, actions, _cache_key=_cache_key
                )
                for action in actions
            ),
            Q_(0, "uL"),
        )

    def _absolute_tolerance(
        self, target: DecimalQuantity
    ) -> DecimalQuantity:
        if self.atol is None or (self.atol.dimensionless and self.atol.m == 0):
            return Q_(0, target.units)
        try:
            return self.atol.to(target.units)
        except Exception as error:
            raise ValueError(
                f"atol {self.atol} is incompatible with target {target}."
            ) from error

    def _target_error(
        self,
        *,
        label: str,
        actual: DecimalQuantity,
        target: DecimalQuantity,
    ) -> VolumeError | None:
        if math.isnan(actual.m) or math.isnan(target.m):
            return None
        try:
            difference = abs(actual - target)
            allowed = self._absolute_tolerance(target) + abs(target) * self.rtol
        except ValueError as error:
            return VolumeError(f"{type(self).__name__} {error}")
        if difference <= allowed:
            return None
        return VolumeError(
            f"{type(self).__name__} for {label} is outside its Echo "
            f"quantization tolerance: target {target}, realized {actual}, "
            f"error {difference}, allowed {allowed}, droplet volume "
            f"{self.droplet_volume}."
        )

    def quantization_errors(
        self,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction],
        _cache_key=None,
    ) -> list[VolumeError]:
        """Return validation errors caused by invalid quantized transfers."""
        errors: list[VolumeError] = []
        for component, volume in zip(
            self.components,
            self.each_volumes(
                mix_vol, actions, _cache_key=_cache_key
            ),
        ):
            if not math.isnan(volume.m) and volume.m < 0:
                errors.append(
                    VolumeError(
                        f"{type(self).__name__} for {component.name} produced "
                        f"a negative Echo transfer of {volume}."
                    )
                )
        return errors

    @maybe_cache_once
    def to_picklist(self, mix: Mix, experiment: Experiment | None = None, _cache_key=None) -> PickList:
        def el_get(key):
            if experiment is None:
                return None
            return experiment.locations.get(key, None)

        mix_vol = mix._get_total_volume(_cache_key=_cache_key)
        quantization_errors = self.quantization_errors(
            mix_vol, mix.actions, _cache_key=_cache_key
        )
        if quantization_errors:
            raise VolumeError("\n".join(str(error) for error in quantization_errors))
        dconcs = self.dest_concentrations(mix_vol, mix.actions, _cache_key=_cache_key)
        eavols = self.each_volumes(mix_vol, mix.actions, _cache_key=_cache_key)

        # An Echo fill needs a source location; a buffer given as a bare string
        # (or otherwise unresolved) has none, which would silently produce a
        # picklist with a null source plate/well.  Flag it clearly instead.
        if isinstance(self, AbstractFillToVolume):
            for c, v in zip(self.components, eavols):
                # Only a positive transfer needs a source; a zero or negative
                # (over-filled) volume transfers nothing from this buffer.
                if math.isnan(v.m) or v.m <= 0:
                    continue
                if (
                    not isinstance(c.plate, str)
                    or not c.plate.strip()
                    or c.well is None
                ):
                    raise ValueError(
                        f"EchoFillToVolume buffer '{c.name}' has no source "
                        "location (plate/well); an Echo transfer needs one.  "
                        "Provide a located Component (or resolve it via a "
                        "Reference) rather than a bare name for an Echo buffer."
                    )

        sconcs = self._get_source_concentrations(_cache_key=_cache_key)
        # Report each component's concentration in its own kind of unit (molarity,
        # mass/volume, or fold), rather than forcing molarity.  Source and
        # destination share a component's unit.
        conc_units = [str(canonical_concentration_unit(c)) for c in sconcs]

        locdf = PickList(
            pl.DataFrame(
                {
                    "Sample Name": [
                        c.printed_name(tablefmt="plain") for c in self.components
                    ],
                    "Source Concentration": [
                        float(c.m_as(u)) for c, u in zip(sconcs, conc_units)
                    ],
                    "Destination Concentration": [
                        float(c.m_as(u)) for c, u in zip(dconcs, conc_units)
                    ],
                    "Concentration Units": conc_units,
                    "Transfer Volume": [float(v.m_as("nL")) for v in eavols],
                    "Source Plate Name": [c.plate for c in self.components],
                    "Source Plate Type": [
                        getattr(
                            el_get(c.plate),
                            "echo_source_type",
                            None,
                        )
                        for c in self.components
                    ],
                    "Source Well": [str(c.well) for c in self.components],
                    "Destination Plate Name": mix.plate,
                    "Destination Plate Type": getattr(
                        el_get(mix.plate),
                        "echo_dest_type",
                        None,
                    ),
                    "Destination Well": str(mix.well),
                    "Destination Sample Name": mix.name,
                },
                schema_overrides={
                    "Sample Name": pl.String,
                    "Source Concentration": pl.Float64,
                    "Destination Concentration": pl.Float64,
                    "Concentration Units": pl.String,
                    "Transfer Volume": pl.Float64,
                    "Source Plate Name": pl.String,
                    "Source Well": pl.String,
                    "Destination Plate Name": pl.String,
                    "Destination Well": pl.String,
                    "Destination Sample Name": pl.String,
                    "Destination Plate Type": pl.String,
                    "Source Plate Type": pl.String,
                },
                # , schema_overrides={"Source Concentration": pl.Decimal(scale=6), "Destination Concentration": pl.Decimal(scale=6), "Transfer Volume": pl.Decimal(scale=6)} # FIXME: when new polars is released
            ).filter(pl.col("Transfer Volume") != 0)
        )
        return locdf


@attrs.define(eq=False)
class EchoFixedVolume(AbstractEchoAction):
    """Transfer a fixed volume of liquid to a target mix."""

    fixed_volume: DecimalQuantity = attrs.field(converter=_parse_vol_required)
    set_name: str | None = None
    droplet_volume: DecimalQuantity = attrs.field(
        default=DEFAULT_DROPLET_VOL, converter=_parse_droplet_volume
    )
    compact_display: bool = True

    def _check_volume(self) -> None:
        fv = self.fixed_volume.m_as("nL")
        dv = self.droplet_volume.m_as("nL")
        # ensure that fv is an integer multiple of dv
        if fv % dv != 0:
            raise ValueError(
                f"Fixed volume {fv} is not an integer multiple of droplet volume {dv}."
            )

    def quantization_errors(
        self,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction],
        _cache_key=None,
    ) -> list[VolumeError]:
        errors = super().quantization_errors(
            mix_vol, actions, _cache_key=_cache_key
        )
        try:
            self._check_volume()
        except ValueError as error:
            errors.append(VolumeError(f"EchoFixedVolume: {error}"))
        return errors

    @maybe_cache_once
    def dest_concentrations(
        self,
        mix_vol: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        _cache_key = gen_random_hash() if _cache_key is None else _cache_key
        realized_mix_vol = self._realized_mix_volume(
            mix_vol, actions, _cache_key=_cache_key
        )
        return [
            x * y
            for x, y in zip(
                self._get_source_concentrations(_cache_key=_cache_key),
                _ratio(
                    self.each_volumes(
                        mix_vol, actions, _cache_key=_cache_key
                    ),
                    realized_mix_vol,
                ),
            )
        ]

    def each_volumes(
        self,
        mix_volume: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        return [cast(DecimalQuantity, self.fixed_volume.to(uL))] * len(self.components)

    @property
    def name(self) -> str:
        if self.set_name is None:
            return super().name
        else:
            return self.set_name

    @maybe_cache_once
    def _mixlines(
        self,
        tablefmt: str | TableFormat,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[MixLine]:
        _cache_key = gen_random_hash() if _cache_key is None else _cache_key
        dconcs = self.dest_concentrations(mix_vol, actions, _cache_key=_cache_key)
        eavols = self.each_volumes(mix_vol, actions, _cache_key=_cache_key)

        locdf = pl.DataFrame(
            {
                "name": [c.printed_name(tablefmt=tablefmt) for c in self.components],
                "source_conc": list(
                    self._get_source_concentrations(_cache_key=_cache_key)
                ),
                "dest_conc": list(dconcs),
                "ea_vols": list(eavols),
                "plate": [c.plate for c in self.components],
                "well": [c.well for c in self.components],
            },
            schema_overrides={
                "source_conc": pl.Object,
                "dest_conc": pl.Object,
                "ea_vols": pl.Object,
            },
        )

        vs = locdf.group_by(
            ("source_conc", "dest_conc", "ea_vols"), maintain_order=True
        ).agg(pl.col("name"), pl.col("plate").unique())

        ml = [
            MixLine(
                [f"{len(q['name'])} comps: {q['name'][0]}, ..."]
                if len(q["name"]) > 5
                else [", ".join(q["name"])],
                q["source_conc"],
                q["dest_conc"],
                len(q["name"]) * self.fixed_volume,
                number=self.number,
                each_tx_vol=self.fixed_volume,
                plate=(", ".join(x for x in q["plate"] if x) if q["plate"] else "?"),
                wells=[],
                note="ECHO",
            )
            for q in vs.iter_rows(named=True)
        ]

        return ml

    def mix_volume_effect(self, _cache_key=None) -> (MixVolumeDep, DecimalQuantity):
        return (MixVolumeDep.INDEPENDENT, self.tx_volume(_cache_key=_cache_key))



@attrs.define(eq=False)
class EchoEqualTargetConcentration(AbstractEchoAction):
    """Transfer a fixed volume of liquid to a target mix."""

    fixed_volume: DecimalQuantity = attrs.field(converter=_parse_vol_required)
    set_name: str | None = None
    droplet_volume: DecimalQuantity = attrs.field(
        default=DEFAULT_DROPLET_VOL, converter=_parse_droplet_volume
    )
    compact_display: bool = False
    method: (
        Literal["max_volume", "min_volume", "check"] | tuple[Literal["max_fill"], str]
    ) = "min_volume"
    rtol: Decimal = attrs.field(
        default=DEFAULT_RTOL, converter=_parse_rtol, kw_only=True
    )
    atol: DecimalQuantity | None = attrs.field(
        default=None, converter=_parse_atol, kw_only=True
    )

    def _check_volume(self) -> None:
        fv = self.fixed_volume.m_as("nL")
        dv = self.droplet_volume.m_as("nL")
        # ensure that fv is an integer multiple of dv
        if fv % dv != 0:
            raise ValueError(
                f"Fixed volume {fv} is not an integer multiple of droplet volume {dv}."
            )

    @maybe_cache_once
    def dest_concentrations(
        self,
        mix_vol: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        realized_mix_vol = self._realized_mix_volume(
            mix_vol, actions, _cache_key=_cache_key
        )
        return [
            x * y
            for x, y in zip(
                self._get_source_concentrations(_cache_key=_cache_key),
                _ratio(
                    self.each_volumes(
                        mix_vol, actions, _cache_key=_cache_key
                    ),
                    realized_mix_vol,
                ),
            )
        ]

    def quantization_errors(
        self,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction],
        _cache_key=None,
    ) -> list[VolumeError]:
        errors = super().quantization_errors(
            mix_vol, actions, _cache_key=_cache_key
        )
        source_concs = self._get_source_concentrations(_cache_key=_cache_key)
        if not source_concs:
            return errors
        if self.method == "min_volume":
            reference_conc = max(source_concs)
        elif self.method == "max_volume" or (
            isinstance(self.method, Sequence)
            and not isinstance(self.method, str)
            and self.method[0] == "max_fill"
        ):
            reference_conc = min(source_concs)
        elif self.method == "check":
            reference_conc = source_concs[0]
        else:
            return errors

        realized_mix_vol = self._realized_mix_volume(
            mix_vol, actions, _cache_key=_cache_key
        )
        if math.isnan(realized_mix_vol.m) or realized_mix_vol.m == 0:
            return errors
        target = reference_conc * self.fixed_volume / realized_mix_vol
        actuals = self.dest_concentrations(
            mix_vol, actions, _cache_key=_cache_key
        )
        for component, actual in zip(self.components, actuals):
            error = self._target_error(
                label=component.name, actual=actual, target=target
            )
            if error is not None:
                errors.append(error)
        return errors

    @maybe_cache_once
    def each_volumes(
        self,
        mix_volume: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        if self.method == "min_volume":
            sc = self._get_source_concentrations(_cache_key=_cache_key)
            scmax = max(sc)
            return [
                round((self.fixed_volume * x / self.droplet_volume).m_as(""))
                * self.droplet_volume
                for x in _ratio(scmax, sc)
            ]
        elif (self.method == "max_volume") | (
            isinstance(self.method, Sequence) and self.method[0] == "max_fill"
        ):
            sc = self._get_source_concentrations(_cache_key=_cache_key)
            scmin = min(sc)
            return [
                round((self.fixed_volume * x / self.droplet_volume).m_as(""))
                * self.droplet_volume
                for x in _ratio(scmin, sc)
            ]
        elif self.method == "check":
            sc = self._get_source_concentrations(_cache_key=_cache_key)
            if any(x != sc[0] for x in sc):
                raise ValueError("Concentrations")
            quantized = (
                round((self.fixed_volume / self.droplet_volume).m_as(""))
                * self.droplet_volume
            )
            return [cast(DecimalQuantity, quantized.to(uL))] * len(self.components)
        raise ValueError(f"equal_conc={self.method!r} not understood")

    @property
    def name(self) -> str:
        if self.set_name is None:
            return super().name
        else:
            return self.set_name

    @maybe_cache_once
    def _mixlines(
        self,
        tablefmt: str | TableFormat,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[MixLine]:
        dconcs = self.dest_concentrations(mix_vol, actions, _cache_key=_cache_key)
        eavols = self.each_volumes(mix_vol, actions, _cache_key=_cache_key)

        locdf = pl.DataFrame(
            {
                "name": [c.printed_name(tablefmt=tablefmt) for c in self.components],
                "source_conc": list(self._get_source_concentrations(_cache_key=_cache_key)),
                "dest_conc": list(dconcs),
                "ea_vols": list(eavols),
                "plate": [c.plate for c in self.components],
                "well": [c.well for c in self.components],
            },
            schema_overrides={
                "source_conc": pl.Object,
                "dest_conc": pl.Object,
                "ea_vols": pl.Object,
            },
        )

        vs = locdf.group_by(
            ("source_conc", "dest_conc", "ea_vols"), maintain_order=True
        ).agg(pl.col("name"), pl.col("plate").unique())

        ml = [
            MixLine(
                [f"{len(q['name'])} comps: {q['name'][0]}, ..."]
                if len(q["name"]) > 5
                else [", ".join(q["name"])],
                q["source_conc"],
                q["dest_conc"],
                len(q["name"]) * q["ea_vols"],
                number=self.number,
                each_tx_vol=q["ea_vols"],
                plate=(", ".join(x for x in q["plate"] if x) if q["plate"] else "?"),
                wells=[],
                note="ECHO",
            )
            for q in vs.iter_rows(named=True)
        ]

        return ml

    def mix_volume_effect(self, _cache_key=None) -> (MixVolumeDep, DecimalQuantity):
        return (MixVolumeDep.INDEPENDENT, self.tx_volume(_cache_key=_cache_key))



@attrs.define(eq=False)
class EchoTargetConcentration(AbstractEchoAction):
    """Get as close as possible (using direct transfers) to a target concentration, possibly varying mix volume."""

    target_concentration: DecimalQuantity = attrs.field(
        converter=_parse_conc_required, on_setattr=attrs.setters.convert
    )
    set_name: str | None = None
    droplet_volume: DecimalQuantity = attrs.field(
        default=DEFAULT_DROPLET_VOL, converter=_parse_droplet_volume
    )
    compact_display: bool = True
    rtol: Decimal = attrs.field(
        default=DEFAULT_RTOL, converter=_parse_rtol, kw_only=True
    )
    atol: DecimalQuantity | None = attrs.field(
        default=None, converter=_parse_atol, kw_only=True
    )

    @maybe_cache_once
    def dest_concentrations(
        self,
        mix_vol: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        realized_mix_vol = self._realized_mix_volume(
            mix_vol, actions, _cache_key=_cache_key
        )
        return [
            x * y
            for x, y in zip(
                self._get_source_concentrations(_cache_key=_cache_key),
                _ratio(
                    self.each_volumes(mix_vol, actions, _cache_key=_cache_key),
                    realized_mix_vol,
                ),
            )
        ]

    def quantization_errors(
        self,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction],
        _cache_key=None,
    ) -> list[VolumeError]:
        errors = super().quantization_errors(
            mix_vol, actions, _cache_key=_cache_key
        )
        actuals = self.dest_concentrations(
            mix_vol, actions, _cache_key=_cache_key
        )
        for component, actual in zip(self.components, actuals):
            error = self._target_error(
                label=component.name,
                actual=actual,
                target=self.target_concentration,
            )
            if error is not None:
                errors.append(error)
        return errors

    @maybe_cache_once
    def each_volumes(
        self,
        mix_volume: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        _cache_key = gen_random_hash() if _cache_key is None else _cache_key
        ea_vols = [
            (
                round((mix_volume * r / self.droplet_volume).m_as(""))
                * self.droplet_volume
            )
            if not math.isnan(mix_volume.m) and not math.isnan(r)
            else NAN_VOL
            for r in _ratio(
                self.target_concentration,
                self._get_source_concentrations(_cache_key=_cache_key),
            )
        ]
        return ea_vols

    @maybe_cache_once
    def _mixlines(
        self,
        tablefmt: str | TableFormat,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[MixLine]:
        dconcs = self.dest_concentrations(mix_vol, actions, _cache_key=_cache_key)
        eavols = self.each_volumes(mix_vol, actions, _cache_key=_cache_key)

        locdf = pl.DataFrame(
            {
                "name": [c.printed_name(tablefmt=tablefmt) for c in self.components],
                "source_conc": list(self._get_source_concentrations(_cache_key=_cache_key)),
                "dest_conc": list(dconcs),
                "ea_vols": list(eavols),
                "plate": [c.plate for c in self.components],
                "well": [c.well for c in self.components],
            },
            schema_overrides={
                "source_conc": pl.Object,
                "dest_conc": pl.Object,
                "ea_vols": pl.Object,
            },
        )

        vs = locdf.group_by(
            ("source_conc", "dest_conc", "ea_vols"), maintain_order=True
        ).agg(pl.col("name"), pl.col("plate").unique())

        ml = [
            MixLine(
                [f"{len(q['name'])} comps: {q['name'][0]}, ..."]
                if len(q["name"]) > 5
                else [", ".join(q["name"])],
                q["source_conc"],
                q["dest_conc"],
                len(q["name"]) * q["ea_vols"],
                number=self.number,
                each_tx_vol=q["ea_vols"],
                plate=(", ".join(x for x in q["plate"] if x) if q["plate"] else "?"),
                wells=[],
                note=f"ECHO, target {self.target_concentration}",
            )
            for q in vs.iter_rows(named=True)
        ]

        return ml

    @property
    def name(self) -> str:
        if self.set_name is None:
            return super().name
        else:
            return self.set_name

    def mix_volume_effect(self, _cache_key=None) -> (MixVolumeDep, DecimalQuantity):
        return (MixVolumeDep.DEPENDS, NAN_VOL)


@attrs.define(eq=False)
class EchoFillToVolume(AbstractEchoAction, AbstractFillToVolume):
    target_total_volume: DecimalQuantity = attrs.field(
        converter=_parse_vol_optional, default=None
    )
    droplet_volume: DecimalQuantity = attrs.field(
        default=DEFAULT_DROPLET_VOL, converter=_parse_droplet_volume
    )
    rtol: Decimal = attrs.field(
        default=DEFAULT_RTOL, converter=_parse_rtol, kw_only=True
    )
    atol: DecimalQuantity | None = attrs.field(
        default=None, converter=_parse_atol, kw_only=True
    )

    @maybe_cache_once
    def dest_concentrations(
        self,
        mix_vol: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        realized_mix_vol = self._realized_mix_volume(
            mix_vol, actions, _cache_key=_cache_key
        )
        return [
            x * y
            for x, y in zip(
                self._get_source_concentrations(_cache_key=_cache_key),
                _ratio(
                    self.each_volumes(mix_vol, actions, _cache_key=_cache_key),
                    realized_mix_vol,
                ),
            )
        ]

    def quantization_errors(
        self,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction],
        _cache_key=None,
    ) -> list[VolumeError]:
        errors = super().quantization_errors(
            mix_vol, actions, _cache_key=_cache_key
        )
        target = (
            mix_vol
            if math.isnan(self.target_total_volume.m)
            else self.target_total_volume
        )
        actual = self._realized_mix_volume(
            mix_vol, actions, _cache_key=_cache_key
        )
        error = self._target_error(
            label=self.components[0].name, actual=actual, target=target
        )
        if error is not None:
            errors.append(error)
        return errors

    @maybe_cache_once
    def each_volumes(
        self,
        mix_volume: DecimalQuantity = NAN_VOL,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[DecimalQuantity]:
        _cache_key = gen_random_hash() if _cache_key is None else _cache_key
        self._raise_if_other_determiner(actions)
        othervol = sum(
            [
                a.tx_volume(mix_volume, actions, _cache_key=_cache_key)
                for a in actions
                if a is not self
            ]
        )

        if len(self.components) > 1:
            raise NotImplementedError(
                "EchoFillToVolume with multiple components is not implemented."
            )

        if math.isnan(self.target_total_volume.m):
            tvol = mix_volume
        else:
            tvol = self.target_total_volume

        maybe_vol = ((tvol - othervol) / self.droplet_volume).m_as("")
        if math.isnan(maybe_vol):
            return [NAN_VOL] * len(self.components)

        return [
            round(maybe_vol)
            * self.droplet_volume
        ]

    @maybe_cache_once
    def _mixlines(
        self,
        tablefmt: str | TableFormat,
        mix_vol: DecimalQuantity,
        actions: Sequence[AbstractAction] = (),
        _cache_key=None,
    ) -> list[MixLine]:
        dconcs = self.dest_concentrations(mix_vol, actions, _cache_key=_cache_key)
        eavols = self.each_volumes(mix_vol, actions, _cache_key=_cache_key)
        return [
            MixLine(
                [comp.printed_name(tablefmt=tablefmt)],
                comp.concentration
                if not math.isnan(comp.concentration.m)
                else None,  # FIXME: should be better handled
                dc if not math.isnan(dc.m) else None,
                ev,
                number=self.number,
                plate=comp.plate if comp.plate else "?",
                wells=comp._well_list,
                note="ECHO",
            )
            for dc, ev, comp in zip(
                dconcs,
                eavols,
                self.components,
            )
        ]

# class EchoTwoStepConcentration(ActionWithComponents):
#     """Use an intermediate mix to obtain a target concentration."""

#     ...

for c in [EchoFixedVolume, EchoEqualTargetConcentration, EchoTargetConcentration, EchoFillToVolume]:
    _STRUCTURE_CLASSES[c.__name__] = c

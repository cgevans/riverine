from __future__ import annotations

from abc import ABC, abstractmethod
from math import isnan
from typing import TYPE_CHECKING, Any, Mapping, Sequence, Tuple, TypeVar, cast

import attrs
import pandas as pd

from .dictstructure import _STRUCTURE_CLASSES, _structure, _unstructure
from .locations import WellPos, _parse_wellpos_optional
from .logging import log
from .printing import TableFormat
from .units import (
    NAN_VOL,
    Q_,
    ZERO_VOL,
    DecimalQuantity,
    _parse_conc_optional,
    _parse_vol_optional,
    nM,
    ureg,
    NAN_CONC
)
import polars as pl

if TYPE_CHECKING:  # pragma: no cover
    from attrs import Attribute

    from .experiments import Experiment
    from .references import Reference


T = TypeVar("T")

__all__ = ["AbstractComponent", "Component", "Strand", "StoredMix"]


class AbstractComponent(ABC):
    """Abstract class for a component in a mix.  Custom components that don't inherit from
    a concrete class should inherit from this class and implement the methods here.
    """

    @property
    @abstractmethod
    def name(self) -> str:  # pragma: no cover
        "Name of the component."
        ...

    @property
    def location(self) -> tuple[str, WellPos | None]:
        return ("", None)

    @property
    def plate(self) -> str | None:
        return None

    @property
    def is_mix(self) -> bool:
        return False

    @property
    def well(self) -> WellPos | None:
        return None

    @property
    def _well_list(self) -> list[WellPos]:
        if self.well is not None:
            return [self.well]
        return []

    @property
    def volume(self) -> DecimalQuantity:
        return NAN_VOL

    @property
    @abstractmethod
    def concentration(self) -> DecimalQuantity:  # pragma: no cover
        "(Source) concentration of the component as a pint Quantity.  NaN if undefined."
        ...

    @abstractmethod
    def all_components(self) -> pd.DataFrame:  # pragma: no cover
        "A dataframe of all components."
        ...

    @abstractmethod
    def with_reference(
        self: T, reference: Reference, *, inplace: bool = False
    ) -> T:  # pragma: no cover
        ...

    @abstractmethod
    def with_experiment(
        self, experiment: Experiment, *, inplace: bool = True
    ) -> AbstractComponent:  # pragma: no cover
        ...

    @classmethod
    @abstractmethod
    def _structure(
        cls, d: dict[str, Any], experiment: Experiment | None = None
    ) -> AbstractComponent:  # pragma: no cover
        ...

    @abstractmethod
    def _unstructure(self, experiment: Experiment | None = None) -> dict[str, Any]:
        ...

    def printed_name(self, tablefmt: str | TableFormat) -> str:
        return self.name

    def _update_volumes(
        self,
        consumed_volumes: dict[str, DecimalQuantity] | None = None,
        made_volumes: dict[str, DecimalQuantity] | None = None,
        _cache_key=None,
    ) -> Tuple[dict[str, DecimalQuantity], dict[str, DecimalQuantity]]:
        """
        Given a
        """
        if consumed_volumes is None:
            consumed_volumes = {}
        if made_volumes is None:
            made_volumes = {}
        if self.name in made_volumes:
            # We've already been seen.  Ignore our components.
            return consumed_volumes, made_volumes

        made_volumes[self.name] = ZERO_VOL

        return consumed_volumes, made_volumes


def norm_nan_for_eq(v1: DecimalQuantity) -> DecimalQuantity:
    if isnan(v1.m):
        return Q_(-1, v1.u)
    return v1


@attrs.define()
class Component(AbstractComponent):
    """A single named component, potentially with a concentration and location.

    Location is stored as a `plate` and `well` property. `plate` is

    """

    name: str # type: ignore
    def _get_name(self, _cache_key=None) -> str:
        return self.name
    concentration: DecimalQuantity = attrs.field(
        converter=_parse_conc_optional,
        default=NAN_CONC,
        on_setattr=attrs.setters.convert,
        eq=norm_nan_for_eq,
    )
    def _get_concentration(self, _cache_key=None) -> DecimalQuantity:
        return self.concentration
    plate: str | None = attrs.field(
        default=None,
        kw_only=True
    )
    well: WellPos | None = attrs.field(
        converter=_parse_wellpos_optional,
        default=None,
        kw_only=True,
        on_setattr=attrs.setters.convert,
    )
    volume: DecimalQuantity = attrs.field( # type: ignore
        converter=_parse_vol_optional,
        default=NAN_VOL,
        on_setattr=attrs.setters.convert,
        eq=norm_nan_for_eq,
    )

    @property
    def location(self) -> tuple[str | None, WellPos | None]: # type: ignore
        return (self.plate, self.well)

    def all_components_polars(self, _cache_key=None) -> pl.DataFrame:
        c = self.concentration.to(nM).magnitude
        if isnan(c):
            c = None
        comp_df = pl.DataFrame(
            {
                'name': [self.name],
                'concentration_nM': [c],
                'component': [self]
            },
            schema={
                'name': pl.String,
                'concentration_nM': pl.Decimal(scale=6),
                'component': pl.Object
            }
        )
        return comp_df

    def all_components(self) -> pd.DataFrame:
        df = self.all_components_polars().to_pandas()
        df.set_index('name', inplace=True)
        return df

    def _unstructure(self, experiment: Experiment | None = None) -> dict[str, Any]:
        d = {}
        d["class"] = self.__class__.__name__
        for att in cast("Sequence[Attribute]", self.__attrs_attrs__): # type: ignore
            if att.name in ["reference"]:
                continue
            val = getattr(self, att.name)
            if val is att.default:
                continue
            if isinstance(val, ureg.Quantity) and isnan(val.m):
                continue
            d[att.name] = _unstructure(val)
        return d

    @classmethod
    def _structure(
        cls, d: dict[str, Any], experiment: Experiment | None = None
    ) -> Component:
        for k, v in d.items():
            d[k] = _structure(v, experiment)
        return cls(**d)

    def with_experiment(
        self: Component, experiment: Experiment, inplace: bool = True
    ) -> AbstractComponent:
        if self.name in experiment.components:
            return experiment.components[self.name]
            # FIXME: add checks
        else:
            return self

    def with_reference(
        self: Component, reference: Reference, inplace: bool = False
    ) -> Component:
        if reference.df.index.name == "Name":
            ref_by_name = reference.df
        else:
            ref_by_name = reference.df.set_index("Name")
        try:
            ref_comps = ref_by_name.loc[
                [self.name], :
            ]  # using this format to force a dataframe result
        except KeyError:
            return self

        mismatches = []
        matches = []
        for _, ref_comp in ref_comps.iterrows():
            ref_conc = Q_(ref_comp["Concentration (nM)"], nM)
            if not isnan(self.concentration.m) and ref_conc != self.concentration:
                mismatches.append(("Concentration (nM)", ref_comp))
                continue

            ref_plate = ref_comp["Plate"]
            if self.plate and ref_plate != self.plate:
                mismatches.append(("Plate", ref_comp))
                continue

            ref_well = _parse_wellpos_optional(ref_comp["Well"])
            if self.well and self.well != ref_well:
                mismatches.append(("Well", ref_well))
                continue

            matches.append(ref_comp)

        if len(matches) > 1:
            log.warning(
                "Component %s has more than one location: %s.  Choosing first.",
                self.name,
                [(x["Plate"], x["Well"]) for x in matches],
            )
        elif (len(matches) == 0) and len(mismatches) > 0:
            raise ValueError(
                f"Component has only mismatched references: {self}, {mismatches}"
            )

        match = matches[0]
        ref_conc = ureg.Quantity(match["Concentration (nM)"], nM)
        ref_plate = match["Plate"]
        ref_well = _parse_wellpos_optional(match["Well"])

        if inplace:
            self.concentration = ref_conc
            self.plate = ref_plate
            self.well = ref_well
            return self
        else:
            return attrs.evolve(
                self,
                name=self.name,
                concentration=ref_conc,
                plate=ref_plate,
                well=ref_well,
            )


@attrs.define()
class Strand(Component):
    """A single named strand, potentially with a concentration, location and sequence."""

    sequence: str | None = None

    def with_reference(
        self: Strand, reference: Reference, inplace: bool = False
    ) -> Strand:
        if reference.df.index.name == "Name":
            ref_by_name = reference.df
        else:
            ref_by_name = reference.df.set_index("Name")
        try:
            ref_comps = ref_by_name.loc[
                [self.name], :
            ]  # using this format to force a dataframe result
        except KeyError:
            return self

        mismatches = []
        matches = []
        for _, ref_comp in ref_comps.iterrows():
            ref_conc = ureg.Quantity(ref_comp["Concentration (nM)"], nM)
            if not isnan(self.concentration.m) and ref_conc != self.concentration:
                mismatches.append(("Concentration (nM)", ref_comp))
                continue

            ref_plate = ref_comp["Plate"]
            if self.plate and ref_plate != self.plate:
                mismatches.append(("Plate", ref_comp))
                continue

            ref_well = _parse_wellpos_optional(ref_comp["Well"])
            if self.well and self.well != ref_well:
                mismatches.append(("Well", ref_well))
                continue

            if isinstance(self.sequence, str) and isinstance(ref_comp["Sequence"], str):
                y = ref_comp["Sequence"]
                self.sequence = self.sequence.replace(" ", "").replace("-", "")
                y = y.replace(" ", "").replace("-", "")
                if self.sequence != y:
                    mismatches.append(("Sequence", ref_comp["Sequence"]))
                    continue

            matches.append(ref_comp)

        del ref_comp  # Ensure we never use this again

        if len(matches) > 1:
            log.warning(
                "Strand %s has more than one location: %s.  Choosing first.",
                self.name,
                [(x["Plate"], x["Well"]) for x in matches],
            )
        elif (len(matches) == 0) and len(mismatches) > 0:
            raise ValueError(
                f"Strand has only mismatched references: {self}, {mismatches}"
            )

        m = matches[0]
        ref_conc = Q_(m["Concentration (nM)"], nM)
        ref_plate = m["Plate"]
        ref_well = _parse_wellpos_optional(m["Well"])
        ss, ms = self.sequence, m["Sequence"]
        if (ss is None) and (ms is None):
            seq = None
        elif isinstance(ss, str) and ((ms is None) or (ms == "")):
            seq = ss
        elif isinstance(ms, str) and ((ss is None) or isinstance(ss, str)):
            seq = ms
        else:
            raise RuntimeError("should be unreachable")

        if inplace:
            self.concentration = ref_conc
            self.plate = ref_plate
            self.well = ref_well
            self.sequence = seq
            return self
        else:
            return attrs.evolve(
                self,
                name=self.name,
                concentration=ref_conc,
                plate=ref_plate,
                well=ref_well,
                sequence=seq,
            )


def _maybesequence_comps(
    object_or_sequence: Sequence[AbstractComponent | str] | AbstractComponent | str,
) -> list[AbstractComponent]:
    if isinstance(object_or_sequence, str):
        return [Component(object_or_sequence)]
    elif isinstance(object_or_sequence, Sequence):
        return [Component(x) if isinstance(x, str) else x for x in object_or_sequence]
    return [object_or_sequence]


def _parse_stored_contents(
    value: Mapping[str, Any] | Sequence[AbstractComponent | str] | AbstractComponent | str,
) -> list[AbstractComponent]:
    if isinstance(value, Mapping):
        out: list[AbstractComponent] = []
        for k, v in value.items():
            if isinstance(v, AbstractComponent):
                out.append(v)
            else:
                out.append(Component(k, v))
        return out
    return _maybesequence_comps(value)


@attrs.define()
class StoredMix(AbstractComponent):
    """A physical stock whose contents are known, used as a single source.

    Examples are a strand already in a buffer, or a mix of many strands kept in a
    freezer.  Unlike a :any:`Mix`, a StoredMix is defined by its contents rather
    than by a recipe for making it.  When it is used as a source in a mix, each of
    its contents is added to that mix, but the volume drawn is consumed from the
    stock itself, not from the contents.

    A buffer or solvent the stock is in is given as one of the contents, the same
    as any other component; if it has a concentration it is tracked in mixes the
    stock is used in.

    Parameters
    ----------

    name:
        Name of the stock (for example, a tube label).

    contents:
        The components in the stock, each with a concentration.  May be given as a
        mapping of name to concentration, or as a sequence of components.

    fixed_concentration:
        Sets the effective source concentration.  A quantity gives it directly.  A
        string names one of the contents, whose concentration is used.  If not
        given, the concentration of the first content is used.
    """

    name: str  # type: ignore
    contents: list[AbstractComponent] = attrs.field(
        converter=_parse_stored_contents,
        on_setattr=attrs.setters.convert,
    )
    fixed_concentration: str | DecimalQuantity | None = attrs.field(
        default=None, kw_only=True
    )
    plate: str | None = attrs.field(default=None, kw_only=True)
    well: WellPos | None = attrs.field(
        converter=_parse_wellpos_optional,
        default=None,
        kw_only=True,
        on_setattr=attrs.setters.convert,
    )
    volume: DecimalQuantity = attrs.field(  # type: ignore
        converter=_parse_vol_optional,
        default=NAN_VOL,
        kw_only=True,
        on_setattr=attrs.setters.convert,
        eq=norm_nan_for_eq,
    )

    @property
    def location(self) -> tuple[str | None, WellPos | None]:  # type: ignore
        return (self.plate, self.well)

    @property
    def concentration(self) -> DecimalQuantity:
        return self._get_concentration()

    def _get_concentration(self, _cache_key=None) -> DecimalQuantity:
        fc = self.fixed_concentration
        if isinstance(fc, ureg.Quantity):
            return fc
        if isinstance(fc, str):
            for c in self.contents:
                if c.name == fc:
                    return c.concentration
            raise ValueError(
                f"fixed_concentration {fc!r} is not the name of a content of {self.name}."
            )
        if self.contents:
            return self.contents[0].concentration
        return NAN_CONC

    def _get_name(self, _cache_key=None) -> str:
        return self.name

    def all_components_polars(self, _cache_key=None) -> pl.DataFrame:
        frames = [c.all_components_polars(_cache_key=_cache_key) for c in self.contents]
        if not frames:
            return pl.DataFrame(
                schema={
                    "name": pl.String,
                    "concentration_nM": pl.Decimal(scale=6),
                    "component": pl.Object,
                }
            )
        return pl.concat(frames)

    def all_components(self) -> pd.DataFrame:
        df = self.all_components_polars().to_pandas()
        df.set_index("name", inplace=True)
        return df

    def _update_volumes(
        self,
        consumed_volumes: dict[str, DecimalQuantity] | None = None,
        made_volumes: dict[str, DecimalQuantity] | None = None,
        _cache_key=None,
    ) -> Tuple[dict[str, DecimalQuantity], dict[str, DecimalQuantity]]:
        if consumed_volumes is None:
            consumed_volumes = {}
        if made_volumes is None:
            made_volumes = {}
        if self.name in made_volumes:
            return consumed_volumes, made_volumes
        made_volumes[self.name] = (
            self.volume if not isnan(self.volume.m) else ZERO_VOL
        )
        consumed_volumes.setdefault(self.name, ZERO_VOL)
        return consumed_volumes, made_volumes

    def with_experiment(
        self: StoredMix, experiment: Experiment, inplace: bool = True
    ) -> AbstractComponent:
        if self.name in experiment.components:
            return experiment.components[self.name]
        return self

    def with_reference(
        self: StoredMix, reference: Reference, inplace: bool = False
    ) -> StoredMix:
        new_contents = [
            c.with_reference(reference, inplace=inplace) for c in self.contents
        ]
        if inplace:
            self.contents = new_contents
            return self
        return attrs.evolve(self, contents=new_contents)

    @classmethod
    def from_mix(
        cls,
        mix: Any,
        *,
        name: str | None = None,
        volume: DecimalQuantity | str | None = None,
        plate: str | None = None,
        well: str | WellPos | None = None,
    ) -> StoredMix:
        """Build a StoredMix from an existing :any:`Mix`, capturing its final
        components and their concentrations as the stock contents."""
        contents: list[AbstractComponent] = []
        for nm, row in mix.all_components().iterrows():
            conc_nM = row["concentration_nM"]
            conc = NAN_CONC if conc_nM is None else Q_(conc_nM, nM)
            base = row["component"]
            if isinstance(base, Strand):
                contents.append(
                    Strand(nm, concentration=conc, sequence=base.sequence)
                )
            else:
                contents.append(Component(nm, concentration=conc))
        return cls(
            name if name is not None else mix.name,
            contents,
            plate=plate,
            well=well,
            volume=volume if volume is not None else NAN_VOL,
        )

    def _unstructure(self, experiment: Experiment | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {"class": self.__class__.__name__, "name": self.name}
        d["contents"] = [c._unstructure(experiment) for c in self.contents]
        if self.fixed_concentration is not None:
            d["fixed_concentration"] = _unstructure(self.fixed_concentration)
        if self.plate is not None:
            d["plate"] = self.plate
        if self.well is not None:
            d["well"] = _unstructure(self.well)
        if not isnan(self.volume.m):
            d["volume"] = _unstructure(self.volume)
        return d

    @classmethod
    def _structure(
        cls, d: dict[str, Any], experiment: Experiment | None = None
    ) -> StoredMix:
        d = dict(d)
        d.pop("class", None)
        d["contents"] = [_structure(c, experiment) for c in d.get("contents", [])]
        for k in list(d):
            if k in ("contents", "name"):
                continue
            d[k] = _structure(d[k], experiment)
        return cls(**d)


def _empty_components() -> pd.DataFrame:
    cps = pd.DataFrame(
        index=pd.Index([], name="name"),
    )
    cps["concentration_nM"] = pd.Series([], dtype=object)
    cps["component"] = pd.Series([], dtype=object)
    return cps


for c in [Component, Strand, StoredMix]:
    _STRUCTURE_CLASSES[c.__name__] = c

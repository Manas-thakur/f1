"""Vendor field -> canonical channel mapping tables.

A vendor packet is never guessed at. Every field an adapter claims to
understand appears in an explicit :class:`FieldMapping`; every field it does not
understand is preserved verbatim in a ``RawSourcePacket`` so it can be re-mapped
later without re-acquiring the session.

Two rules are enforced at construction time rather than at ingestion time, so a
bad table fails when it is defined and not in the middle of a race:

* the target channel must exist in ``afterlap_contracts.registry`` and the
  declared vendor unit must have a registered conversion to that channel's SI
  unit;
* a field listed as *forbidden* (a historical DRS flag, say) cannot also be
  mapped, and asking for its mapping raises rather than returning something
  plausible.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from afterlap_contracts import channel as channel_spec, is_registered

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

UNIT_CONVERSIONS: Final[dict[tuple[str, str], tuple[float, float]]] = {
    ("m/s", "m/s"): (1.0, 0.0),
    ("km/h", "m/s"): (1.0 / 3.6, 0.0),
    ("kph", "m/s"): (1.0 / 3.6, 0.0),
    ("mph", "m/s"): (0.44704, 0.0),
    ("m", "m"): (1.0, 0.0),
    ("km", "m"): (1000.0, 0.0),
    ("m/s^2", "m/s^2"): (1.0, 0.0),
    ("g", "m/s^2"): (9.80665, 0.0),
    ("J", "J"): (1.0, 0.0),
    ("kJ", "J"): (1e3, 0.0),
    ("MJ", "J"): (1e6, 0.0),
    ("Wh", "J"): (3600.0, 0.0),
    ("W", "W"): (1.0, 0.0),
    ("kW", "W"): (1e3, 0.0),
    ("MW", "W"): (1e6, 0.0),
    ("K", "K"): (1.0, 0.0),
    ("degC", "K"): (1.0, 273.15),
    ("C", "K"): (1.0, 273.15),
    ("s", "s"): (1.0, 0.0),
    ("ms", "s"): (1e-3, 0.0),
}

HIDDEN_TRUTH_PREFIXES: Final[tuple[str, ...]] = ("truth_", "hidden_", "world_", "gt_", "oracle_")
HIDDEN_TRUTH_FIELDS: Final[frozenset[str]] = frozenset(
    {"world_state", "rival_battery_energy_j", "rival_energy_j", "opponent_policy", "rng_state"}
)

SECRET_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization|auth[_-]?header"
    r"|cookie|credential|bearer|private[_-]?key|signature)",
    re.IGNORECASE,
)


class MappingError(ValueError):
    """A mapping table is inconsistent, or a forbidden field was requested."""


def conversion_for(vendor_unit: str, si_unit: str) -> tuple[float, float]:
    """Return ``(scale, offset)`` converting ``vendor_unit`` into ``si_unit``."""
    try:
        return UNIT_CONVERSIONS[(vendor_unit, si_unit)]
    except KeyError as exc:
        raise MappingError(
            f"no registered conversion from {vendor_unit!r} to {si_unit!r}; "
            "add it to UNIT_CONVERSIONS after review rather than scaling inline"
        ) from exc


@dataclass(frozen=True, slots=True)
class FieldMapping:
    """One vendor field mapped onto one canonical channel."""

    vendor_field: str
    channel: str
    vendor_unit: str
    missing_values: tuple[Any, ...] = ()
    note: str | None = None
    scale: float = field(init=False, default=1.0)
    offset: float = field(init=False, default=0.0)
    si_unit: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if not is_registered(self.channel):
            raise MappingError(
                f"{self.vendor_field!r} maps to unregistered channel {self.channel!r}; "
                "register it in afterlap_contracts.registry first"
            )
        spec = channel_spec(self.channel)
        scale, offset = conversion_for(self.vendor_unit, spec.unit)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "offset", offset)
        object.__setattr__(self, "si_unit", spec.unit)

    def is_missing(self, raw: Any) -> bool:
        if raw is None:
            return True
        for sentinel in self.missing_values:
            if raw == sentinel:
                return True
        return isinstance(raw, float) and math.isnan(raw)

    def to_si(self, raw: Any) -> float | None:
        """Convert one vendor value to SI, or ``None`` when it means 'missing'.

        A non-numeric value is a structural fault, not a zero.
        """
        if self.is_missing(raw):
            return None
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise MappingError(
                f"field {self.vendor_field!r} carried non-numeric value {raw!r}; "
                "a non-numeric sample is never coerced to a number"
            )
        return float(raw) * self.scale + self.offset


@dataclass(frozen=True, slots=True)
class MappingTable:
    """The complete, versioned field map for one source."""

    mapping_revision: str
    source_id: str
    entries: tuple[FieldMapping, ...]
    forbidden_fields: Mapping[str, str] = field(default_factory=dict)
    passthrough_fields: tuple[str, ...] = ()
    _by_vendor: dict[str, FieldMapping] = field(init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        by_vendor: dict[str, FieldMapping] = {}
        for entry in self.entries:
            if entry.vendor_field in by_vendor:
                raise MappingError(f"duplicate mapping for vendor field {entry.vendor_field!r}")
            if entry.vendor_field in self.forbidden_fields:
                raise MappingError(
                    f"vendor field {entry.vendor_field!r} is both mapped and forbidden: "
                    f"{self.forbidden_fields[entry.vendor_field]}"
                )
            by_vendor[entry.vendor_field] = entry
        if not self.mapping_revision:
            raise MappingError("a mapping table must carry a mapping_revision")
        object.__setattr__(self, "_by_vendor", by_vendor)

    def mapped_fields(self) -> tuple[str, ...]:
        return tuple(self._by_vendor)

    def channels(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for entry in self.entries:
            seen.setdefault(entry.channel, None)
        return tuple(seen)

    def is_mapped(self, vendor_field: str) -> bool:
        return vendor_field in self._by_vendor

    def is_forbidden(self, vendor_field: str) -> bool:
        return vendor_field in self.forbidden_fields

    def get(self, vendor_field: str) -> FieldMapping | None:
        """Return the mapping, ``None`` if unmapped, raising if explicitly forbidden."""
        if vendor_field in self.forbidden_fields:
            raise MappingError(
                f"vendor field {vendor_field!r} is forbidden for this source: "
                f"{self.forbidden_fields[vendor_field]}"
            )
        return self._by_vendor.get(vendor_field)

    def with_revision(self, mapping_revision: str) -> MappingTable:
        return MappingTable(
            mapping_revision=mapping_revision,
            source_id=self.source_id,
            entries=self.entries,
            forbidden_fields=dict(self.forbidden_fields),
            passthrough_fields=self.passthrough_fields,
        )


def find_truth_leaks(field_names: Iterable[str]) -> tuple[str, ...]:
    """Names in ``field_names`` that look like hidden simulator truth."""
    leaks = []
    for name in field_names:
        lowered = name.lower()
        if lowered in HIDDEN_TRUTH_FIELDS or lowered.startswith(HIDDEN_TRUTH_PREFIXES):
            leaks.append(name)
    return tuple(sorted(leaks))


__all__ = [
    "HIDDEN_TRUTH_FIELDS",
    "HIDDEN_TRUTH_PREFIXES",
    "SECRET_NAME_PATTERN",
    "UNIT_CONVERSIONS",
    "FieldMapping",
    "MappingError",
    "MappingTable",
    "conversion_for",
    "find_truth_leaks",
]

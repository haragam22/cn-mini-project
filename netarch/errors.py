"""Typed error hierarchy (technical.md §13).

Every error carries ``field``, ``value``, ``rule_id``, ``message`` and ``hint`` so the CLI and
TUI can point at the exact bad input and say how to fix it.
"""

from __future__ import annotations

from typing import Any


class NetArchError(Exception):
    """Base for every error the tool raises on purpose."""

    def __init__(
        self,
        *,
        field: str,
        value: Any = None,
        rule_id: str,
        message: str,
        hint: str,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.value = value
        self.rule_id = rule_id
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"{type(self).__name__}(field={self.field!r}, rule_id={self.rule_id!r})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": type(self).__name__,
            "field": self.field,
            "value": self.value,
            "rule_id": self.rule_id,
            "message": self.message,
            "hint": self.hint,
        }


class InputValidationError(NetArchError):
    """Bad input. When several problems are found at once, ``errors`` lists every one."""

    def __init__(self, *, errors: list[NetArchError] | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.errors: list[NetArchError] = list(errors) if errors else [self]

    @classmethod
    def aggregate(cls, errors: list[NetArchError]) -> InputValidationError:
        fields = ", ".join(e.field for e in errors)
        lines = "\n".join(f"- {e.field}: {e.message}" for e in errors)
        return cls(
            errors=errors,
            field=fields,
            value=None,
            rule_id="INPUT.MULTIPLE",
            message=f"{len(errors)} input problems found:\n{lines}",
            hint="Fix every listed field, then validate again.",
        )


class PhysicalDistanceViolationError(NetArchError):
    """Copper requested beyond the 100 m channel (spec name, exact)."""

    @classmethod
    def for_link(
        cls, a: str, b: str, distance_m: float, *, field: str
    ) -> PhysicalDistanceViolationError:
        dist = f"{distance_m:g}"
        return cls(
            field=field,
            value=distance_m,
            rule_id="MEDIA.E1",
            message=(
                f"Copper requested for link {a} ↔ {b} at {dist} m. Category 6a / 10GBASE-T is "
                "limited to a 100 m channel (IEEE 802.3an); beyond this, insertion loss and "
                "crosstalk exceed receiver tolerance. Use OM4 multimode fibre "
                "(10GBASE-SR, ≤ 400 m)."
            ),
            hint="Set requested_media to null (let the engine choose) or to om4/os2.",
        )


class OpticalBudgetExceededError(NetArchError):
    """No optic fits the link loss (+ margin); the message states the shortfall in dB."""


class AddressSpaceExhaustedError(NetArchError):
    """Requested vs available addresses, shortfall, smallest fitting root."""


class AddressOverlapError(NetArchError):
    """Reserved, VPC or custom ranges collide (or leave RFC 1918)."""


class TopologyConstraintError(NetArchError):
    """The topology cannot satisfy a stated constraint, e.g. dual_homed with a single path."""


class CapacityError(NetArchError):
    """Ports or PoE budget exceeded."""


class VerificationError(NetArchError):
    """Self-check or Batfish failures (CLI exit 1)."""

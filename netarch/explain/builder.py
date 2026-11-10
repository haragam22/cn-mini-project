"""Helpers engines use to build Decision records (technical.md §4.2)."""

from __future__ import annotations

from typing import Any

from netarch.explain.render import render_rationale
from netarch.models.decisions import ID_PREFIXES, Decision, Rejected


def decision_id(prefix: str, n: int) -> str:
    """'L1', 3 → 'L1-03'. Prefix must be one of the §4.2 domain prefixes."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unknown decision prefix {prefix!r}; expected one of {ID_PREFIXES}")
    return f"{prefix}-{n:02d}"


def rejected(option: str, reason: str) -> Rejected:
    return Rejected(option=option, reason=reason)


def make_decision(**fields: Any) -> Decision:
    """Build a Decision and fill ``rationale`` from its fields (engines never write prose)."""
    fields.pop("rationale", None)
    d = Decision(**fields)
    return d.model_copy(update={"rationale": render_rationale(d)})

"""Packet Tracer capability matrix lookups (technical.md §12, decisions.md 2026-10-23).

Rows still ``untested`` count as unsupported, so engines fall back to the conservative choice.
"""

from __future__ import annotations

from netarch.engines.optics import load_data


def pt_result(feature_id: str) -> str:
    """The matrix ``result`` for one row: untested | accepted | rejected | alternative."""
    for row in load_data("pt_capabilities.yaml")["features"]:
        if row["id"] == feature_id:
            return str(row["result"])
    raise KeyError(f"unknown PT capability row {feature_id!r}")


def pt_accepts(*feature_ids: str) -> bool:
    """True only if every named row was tested and accepted in Packet Tracer."""
    return all(pt_result(f) == "accepted" for f in feature_ids)

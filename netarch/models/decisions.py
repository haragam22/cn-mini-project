"""Decision record, the explainability core (technical.md §4.2).

Engines fill these fields; ``explain/render.py`` turns them into prose.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Domain = Literal[
    "media", "transceiver", "topology", "switching",
    "addressing", "routing", "vpn", "qos", "security",
]

# Decision id prefixes named in §4.2.
ID_PREFIXES: tuple[str, ...] = ("L1", "L2", "L3", "RT", "VPN", "QOS", "SEC", "TOP")


class Rejected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option: str
    reason: str


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    domain: Domain
    subject: str
    choice: str
    rule_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    math: list[str] = Field(default_factory=list)
    rationale: str = ""
    standards: list[str] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    counterfactual: str | None = None
    warnings: list[str] = Field(default_factory=list)
    spec_note: str | None = None

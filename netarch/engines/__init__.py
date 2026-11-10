"""Design engines. Each stage is a pure function: NetworkPlan in, NetworkPlan out."""

from __future__ import annotations

from netarch.models.plan import NetworkPlan
from netarch.models.requirements import Requirements


def design_l1_l2(
    req: Requirements, *, min_margin_db: float | None = None, poe_budget_w: float | None = None
) -> NetworkPlan:
    """Pipeline stages built so far (technical.md §3): L1 media → topology tier → L2."""
    from netarch.engines import l1_media, l2_switching, topology

    plan = NetworkPlan(requirements=req)
    plan = l1_media.run(plan, min_margin_db=min_margin_db)
    plan = topology.run(plan)
    return l2_switching.run(plan, poe_budget_w=poe_budget_w)


def design(
    req: Requirements, *, min_margin_db: float | None = None, poe_budget_w: float | None = None
) -> NetworkPlan:
    """Full design pipeline (technical.md §3): L1 → topology → L2 → VLSM → lab mapping → VPN →
    routing → QoS → ACLs."""
    from netarch.configgen import interface_map
    from netarch.engines import qos, routing, security, vlsm, vpn

    plan = design_l1_l2(req, min_margin_db=min_margin_db, poe_budget_w=poe_budget_w)
    plan = vlsm.run(plan)
    plan = interface_map.build(plan)
    plan = vpn.run(plan)
    plan = routing.run(plan)
    plan = qos.run(plan)
    return security.run(plan)

"""Topology tier TOP.R1–R3 with link-count math (technical.md §6.1). Pure: plan in, plan out."""

from __future__ import annotations

from netarch.engines.optics import load_data, value
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import Requirements


def full_mesh_links(n: int) -> int:
    return n * (n - 1) // 2


def hub_links(n: int) -> int:
    return max(0, n - 1)


def core_uplinks(n: int) -> int:
    return n


def _limits() -> dict[str, int]:
    t = load_data("topology.yaml")
    return {k: value(t, k) for k in t}


def select_tier(blocks: int, endpoints: int) -> str:
    lim = _limits()
    if blocks > lim["two_tier_max_blocks"] or endpoints > lim["two_tier_max_endpoints"]:
        return "TOP.R3"
    if blocks == 1 and endpoints <= lim["collapsed_single_block_max_endpoints"]:
        return "TOP.R1"
    return "TOP.R2"


def _hub(req: Requirements) -> str:
    return next((s.id for s in req.sites if s.kind == "hq"), req.sites[0].id)


def run(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    lim = _limits()
    n = len(req.sites)
    endpoints = sum(seg.hosts for s in req.sites for seg in s.segments)
    k = len(req.links)
    rule = select_tier(n, endpoints)
    fm, hub, core = full_mesh_links(n), hub_links(n), core_uplinks(n)
    max_mesh = lim["full_mesh_max_blocks"]
    max_blocks, max_ep = lim["two_tier_max_blocks"], lim["two_tier_max_endpoints"]
    max_r1 = lim["collapsed_single_block_max_endpoints"]

    math = [
        f"endpoints = sum of segment hosts = {endpoints}",
        f"full mesh: n(n−1)/2 = {n}·{n - 1}/2 = {fm} links",
        f"hub: n − 1 = {hub} links",
        f"dedicated core: n = {core} uplinks (plus the core switches)",
    ]
    if k == 0 and n > 1:
        math.append("no physical inter-site links in the input; inter-site paths come from the "
                    "WAN/VPN design (technical.md §8.3)")
    else:
        math.append(f"input defines {k} physical inter-site links")

    r1 = rejected("TOP.R1 collapsed core in one block",
                  f"needs 1 building and ≤ {max_r1} endpoints; have {n} blocks, "
                  f"{endpoints} endpoints")
    r3 = rejected("TOP.R3 three-tier dedicated core",
                  f"needs > {max_blocks} blocks or > {max_ep} endpoints; have {n} blocks, "
                  f"{endpoints} endpoints")
    warnings: list[str] = []
    if rule == "TOP.R1":
        choice = "Two-tier, collapsed core in one switch block"
        rej = [rejected("TOP.R2 one distribution switch per building",
                        "only one block; a separate distribution layer adds switches with "
                        "nothing to join"), r3]
        cf = (f"Would move to TOP.R2 with a second building or more than {max_r1} endpoints.")
    elif rule == "TOP.R3":
        choice = f"Three-tier with dedicated core, {core} distribution uplinks"
        rej = [r1, rejected("TOP.R2 collapsed core",
                            f"a full mesh of {n} blocks needs {fm} links vs {core} core uplinks")]
        cf = (f"Would collapse to two-tier (TOP.R2) at ≤ {max_blocks} blocks and ≤ {max_ep} "
              "endpoints.")
    else:
        if n == 1:
            choice = "Two-tier collapsed core, single distribution block"
            pattern_rej = []
            needed = 0
        elif n <= max_mesh:
            choice = f"Two-tier collapsed core, full mesh of {n} distribution blocks"
            pattern_rej = [rejected("Hub-and-spoke",
                                    f"saves only {fm - hub} link(s) ({hub} vs {fm}) but sends "
                                    "every inter-building path through one hub")]
            needed = fm
        else:
            h = _hub(req)
            choice = f"Two-tier collapsed core, hub at {h} with {n} distribution blocks"
            pattern_rej = [rejected("Full mesh",
                                    f"{fm} links for {n} blocks vs {hub} hub links")]
            needed = hub
        rej = [r1, r3, *pattern_rej]
        if 0 < k < needed:
            warnings.append(f"input defines {k} link(s); the chosen pattern needs {needed}.")
        cf = (f"Would move to a three-tier dedicated core (TOP.R3) above {max_blocks} blocks or "
              f"{max_ep} endpoints; {max_blocks + 1} blocks would need "
              f"{full_mesh_links(max_blocks + 1)} full-mesh links.")
    std = load_data("standards.yaml")
    n_top = 1 + sum(d.id.startswith("TOP-") for d in plan.decisions)
    d = make_decision(
        id=decision_id("TOP", n_top), domain="topology", subject="Network topology tier",
        choice=choice, rule_id=rule,
        inputs={"distribution_blocks": n, "endpoints": endpoints, "input_links": k},
        math=math, standards=[std["ieee_802_1w"]], rejected=rej, counterfactual=cf,
        warnings=warnings,
    )
    return plan.model_copy(update={
        "decisions": [*plan.decisions, d],
        "warnings": [*plan.warnings, *(f"{d.id}: {w}" for w in warnings)],
    })

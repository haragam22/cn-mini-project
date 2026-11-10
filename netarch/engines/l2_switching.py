"""Layer 2 switching design (technical.md §6.2–6.3). Pure: plan in, plan out.

Per site: VLAN set + native VLAN, trunk allowed list, RSTP root placement, and the
port / PoE / AP-density checks that size the access layer (``CapacityError`` on overflow).
Wired endpoints include growth (ceil, as §7.2 without the gateway). PoE: the physical
recommendation is 802.3at switching sized to APs × 30 W; the lab mapping limitation (§6.4) is
stated from devices.yaml.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from netarch.engines.optics import fmt_num, load_data, value
from netarch.errors import CapacityError
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.decisions import Decision
from netarch.models.plan import NetworkPlan, PlanSegment
from netarch.models.requirements import Site

# Roles whose hosts need a wired access port. Wireless clients use APs; MGMT addresses belong
# to the network devices themselves (decisions.md, 2026-10-23 P2).
WIRED_ROLES = frozenset({"users", "servers", "labs", "trading", "iot"})


@dataclass(frozen=True)
class SwitchConsts:
    model: str
    dist_model: str
    ports_per_switch: int  # access + uplink ports
    uplinks_per_switch: int
    per_ap_w: float
    lab_poe_standard: str  # distribution switch (3560-24PS)
    lab_poe_per_port_w: float
    lab_access_poe_per_port_w: float  # access switch (2960-24TT)
    max_clients_per_ap: float
    native_vlan: int


def load_consts() -> SwitchConsts:
    dev = load_data("devices.yaml")
    access = value(dev, "access_switch.access_ports")
    uplinks = value(dev, "access_switch.uplink_ports")
    return SwitchConsts(
        model=dev["access_switch"]["model"],
        dist_model=dev["distribution_switch"]["model"],
        ports_per_switch=access + uplinks,
        uplinks_per_switch=uplinks,
        per_ap_w=value(dev, "poe.per_ap_w"),
        lab_poe_standard=value(dev, "distribution_switch.poe_standard"),
        lab_poe_per_port_w=value(dev, "distribution_switch.poe_per_port_w"),
        lab_access_poe_per_port_w=value(dev, "access_switch.poe_per_port_w"),
        max_clients_per_ap=value(dev, "wireless.max_clients_per_ap"),
        native_vlan=value(load_data("topology.yaml"), "native_vlan"),
    )


# --- capacity math -------------------------------------------------------------------


def wired_with_growth(hosts: int, growth_pct: float) -> int:
    """ceil(hosts × (1 + growth_pct/100)) in exact decimal arithmetic (§7.2 rounding, no +1)."""
    return math.ceil(Decimal(hosts) * (1 + Decimal(repr(growth_pct)) / 100))


def access_switches_needed(
    wired: int, aps: int, *, ports_per_switch: int, uplinks_per_switch: int
) -> int:
    """Smallest n with wired + aps + uplinks·n ≤ ports·n."""
    return math.ceil((wired + aps) / (ports_per_switch - uplinks_per_switch))


def check_access_ports(
    wired: int, aps: int, switches: int, *, ports_per_switch: int, uplinks_per_switch: int,
    field: str,
) -> None:
    need = wired + aps + uplinks_per_switch * switches
    have = ports_per_switch * switches
    if need > have:
        n = access_switches_needed(
            wired, aps, ports_per_switch=ports_per_switch, uplinks_per_switch=uplinks_per_switch
        )
        raise CapacityError(
            field=field, value=switches, rule_id="L2.CAP.PORTS",
            message=(
                f"Access ports exceeded: {wired} wired endpoints + {aps} APs + "
                f"{uplinks_per_switch * switches} uplinks = {need} ports needed > "
                f"{switches} × {ports_per_switch} = {have} available; {n} switches needed."
            ),
            hint=f"Use {n} access switches.",
        )


def poe_demand_w(aps: int, *, per_ap_w: float) -> float:
    return aps * per_ap_w


def check_poe(aps: int, budget_w: float, *, per_ap_w: float, field: str) -> None:
    need = poe_demand_w(aps, per_ap_w=per_ap_w)
    if need > budget_w:
        raise CapacityError(
            field=field, value=aps, rule_id="L2.CAP.POE",
            message=(
                f"PoE budget exceeded: {aps} APs × {fmt_num(per_ap_w)} W = {fmt_num(need)} W > "
                f"{fmt_num(budget_w)} W available (IEEE 802.3at Class 4 at the PSE)."
            ),
            hint="Add PoE switches or a larger PoE budget for the access points.",
        )


def ap_density_warning(clients: int, aps: int, *, max_per_ap: float) -> str | None:
    if clients <= 0:
        return None
    if aps == 0:
        return f"{clients} wireless clients but no access points at this site."
    per = clients / aps
    if per > max_per_ap:
        return (f"{fmt_num(round(per, 1))} wireless clients per AP ({clients} / {aps}) exceeds "
                f"the {fmt_num(max_per_ap)} per-AP design constant; add APs.")
    return None


# --- engine --------------------------------------------------------------------------


def run(plan: NetworkPlan, *, poe_budget_w: float | None = None) -> NetworkPlan:
    """``poe_budget_w``: PoE budget per site to check against; None = report demand only."""
    c = load_consts()
    std = load_data("standards.yaml")
    decisions: list[Decision] = []
    segments: list[PlanSegment] = []
    n0 = sum(d.id.startswith("L2-") for d in plan.decisions)

    def add(**fields) -> None:
        decisions.append(make_decision(id=decision_id("L2", n0 + len(decisions) + 1), **fields))

    for i, site in enumerate(plan.requirements.sites):
        segments += [PlanSegment(site=site.id, name=s.name, vlan=s.vlan) for s in site.segments]
        n_access = _access_count(c, site)
        _vlans(add, c, std, site)
        _trunks(add, c, std, site, n_access)
        _rstp(add, std, site, n_access)
        _capacity(add, c, std, i, site, poe_budget_w)
    warnings = [f"{d.id}: {w}" for d in decisions for w in d.warnings]
    return plan.model_copy(update={
        "segments": [*plan.segments, *segments],
        "decisions": [*plan.decisions, *decisions],
        "warnings": [*plan.warnings, *warnings],
    })


def _vlan_list(site: Site) -> list[int]:
    return sorted(s.vlan for s in site.segments)


def _csv(vlans: list[int]) -> str:
    return ",".join(str(v) for v in vlans)


def _vlans(add, c: SwitchConsts, std, site: Site) -> None:
    vlans = _vlan_list(site)
    hosts = sum(s.hosts for s in site.segments)
    add(
        domain="switching", subject=f"VLANs at {site.id}",
        choice=f"VLANs {_csv(vlans)}; native VLAN {c.native_vlan} (unused, no SVI)",
        rule_id="L2.VLAN",
        inputs={"vlans": vlans, "native_vlan": c.native_vlan, "hosts": hosts},
        math=[f"{len(vlans)} segments → {len(vlans)} VLANs: "
              + ", ".join(f"{s.name}={s.vlan}"
                          for s in sorted(site.segments, key=lambda s: s.vlan))],
        standards=[std["ieee_802_1q"]],
        rejected=[
            rejected("VLAN 1 for data", "default VLAN on every port and the usual target of "
                                        "VLAN-hopping; it carries control-plane traffic"),
            rejected("A data VLAN as native", "untagged frames would land in a user VLAN and "
                                              "double-tagged frames could reach it"),
            rejected("One flat VLAN", f"a single broadcast domain for {hosts} hosts with no "
                                      "zone boundary for ACLs"),
        ],
        counterfactual="A new segment at this site would add one VLAN and one trunk entry.",
    )


def _trunks(add, c: SwitchConsts, std, site: Site, n_access: int) -> None:
    vlans = _vlan_list(site)
    add(
        domain="switching", subject=f"Trunks at {site.id} (distribution ↔ access)",
        choice=(f"switchport trunk allowed vlan {_csv(vlans)}; switchport trunk native vlan "
                f"{c.native_vlan}; switchport nonegotiate"),
        rule_id="L2.TRUNK",
        inputs={"allowed_vlans": vlans, "native_vlan": c.native_vlan,
                "access_switches": n_access, "uplinks_per_switch": c.uplinks_per_switch},
        math=[
            f"allowed = VLANs present at {site.id} = {_csv(vlans)} ({len(vlans)} VLANs)",
            f"native {c.native_vlan} carries no data and is not in the allowed list",
            f"{n_access} access switch(es) × {c.uplinks_per_switch} trunk uplinks",
        ],
        standards=[std["ieee_802_1q"]],
        rejected=[
            rejected("switchport trunk allowed vlan all",
                     f"floods every VLAN and runs spanning-tree instances for VLANs absent at "
                     f"{site.id}"),
            rejected("switchport trunk native vlan 1",
                     "VLAN 1 is the default VLAN; untagged and double-tagged frames land in it"),
            rejected("DTP (dynamic auto/desirable)",
                     "negotiation lets an attached device form a trunk"),
        ],
        counterfactual="A VLAN joins the allowed list only when a segment for it exists here.",
    )


def _rstp(add, std, site: Site, n_access: int) -> None:
    vlans = _vlan_list(site)
    add(
        domain="switching", subject=f"Spanning tree at {site.id}",
        choice=(f"spanning-tree mode rapid-pvst; {site.id} distribution switch is root primary "
                f"for VLANs {_csv(vlans)}"),
        rule_id="L2.RSTP",
        inputs={"vlans": vlans, "access_switches": n_access},
        math=[
            f"root bridge for VLANs {_csv(vlans)} = {site.id} L3 distribution switch = SVI "
            "gateway location",
            f"inter-site links are routed (no switchport): the spanning-tree domain stays inside "
            f"{site.id}",
        ],
        standards=[std["ieee_802_1w"], std["ieee_802_1q"]],
        rejected=[
            rejected("IEEE 802.1D STP / PVST+",
                     "timer-based convergence (listening, learning) instead of RSTP's "
                     "proposal/agreement handshake"),
            rejected("Default root election",
                     "the lowest bridge ID wins, which can put the root on an access switch so "
                     "traffic detours away from the gateway"),
        ],
        counterfactual=("A second distribution switch would be root secondary for the same "
                        "VLANs."),
    )


def _wired_segments(site: Site) -> list[tuple[str, int, float, int]]:
    """(name, hosts, growth_pct, wired ports) for every segment that needs wired access ports."""
    return [(s.name, s.hosts, s.growth_pct, wired_with_growth(s.hosts, s.growth_pct))
            for s in site.segments if s.role in WIRED_ROLES]


def _wired(site: Site) -> int:
    return sum(w for *_, w in _wired_segments(site))


def _access_count(c: SwitchConsts, site: Site) -> int:
    return access_switches_needed(_wired(site), site.access_points,
                                  ports_per_switch=c.ports_per_switch,
                                  uplinks_per_switch=c.uplinks_per_switch)


def _capacity(add, c: SwitchConsts, std, i: int, site: Site,
              poe_budget_w: float | None) -> None:
    wired = _wired(site)
    clients = sum(s.hosts for s in site.segments if s.role == "wireless")
    aps = site.access_points
    P, u = c.ports_per_switch, c.uplinks_per_switch
    n = _access_count(c, site)
    check_access_ports(wired, aps, n, ports_per_switch=P, uplinks_per_switch=u,
                       field=f"sites[{i}]")
    math_lines = []
    if segs := _wired_segments(site):
        math_lines.append(
            "wired = " + " + ".join(f"{name} ceil({h} × (1 + {fmt_num(g)}/100)) = {w}"
                                    for name, h, g, w in segs)
            + f" → {wired} (wireless and MGMT excluded)"
        )
    math_lines += [
        f"ports needed = {wired} wired + {aps} APs + {u}·n uplinks ≤ {P}·n → "
        f"n = ceil({wired + aps} / ({P} − {u})) = {n}",
    ]
    warnings: list[str] = []
    standards = [std["ieee_802_1q"]]
    choice = f"{n} × {P}-port access switches ({c.model} in the lab)"
    inputs = {"wired_endpoints": wired, "access_points": aps, "wireless_clients": clients,
              "access_switches": n, "ports_per_switch": P, "uplinks_per_switch": u}
    if aps:
        demand = poe_demand_w(aps, per_ap_w=c.per_ap_w)
        math_lines.append(f"PoE = {aps} APs × {fmt_num(c.per_ap_w)} W = {fmt_num(demand)} W")
        standards.insert(0, std["ieee_802_3at"])
        inputs["poe_required_w"] = demand
        choice += (f"; physical: 802.3at (PoE+) access switching with PoE budget ≥ "
                   f"{fmt_num(demand)} W for {aps} APs")
        lab_access = ("has no PoE" if c.lab_access_poe_per_port_w == 0 else
                      f"gives {fmt_num(c.lab_access_poe_per_port_w)} W per port")
        math_lines.append(
            f"lab mapping: {c.dist_model} PoE is {c.lab_poe_standard} "
            f"({fmt_num(c.lab_poe_per_port_w)} W per port) < {fmt_num(c.per_ap_w)} W per AP and "
            f"{c.model} {lab_access}, so the lab cannot power {fmt_num(c.per_ap_w)} W APs "
            "(logical config identical)"
        )
        if poe_budget_w is not None:
            check_poe(aps, poe_budget_w, per_ap_w=c.per_ap_w,
                      field=f"sites[{i}].access_points")
            math_lines.append(f"PoE {fmt_num(demand)} W ≤ {fmt_num(poe_budget_w)} W budget")
        if clients:
            math_lines.append(f"clients per AP = {clients} / {aps} = "
                              f"{fmt_num(round(clients / aps, 1))} (limit "
                              f"{fmt_num(c.max_clients_per_ap)})")
    if w := ap_density_warning(clients, aps, max_per_ap=c.max_clients_per_ap):
        warnings.append(w)
    rej = []
    if n > 1:
        rej.append(rejected(
            f"{n - 1} access switch(es)",
            f"{(n - 1) * (P - u)} endpoint ports < {wired + aps} needed",
        ))
    add(
        domain="switching", subject=f"Access capacity at {site.id}",
        choice=choice,
        rule_id="L2.CAP",
        inputs=inputs,
        math=math_lines, standards=standards, rejected=rej,
        counterfactual=(f"Each further {P - u} wired endpoints or APs would add one access "
                        "switch."),
        warnings=warnings,
    )

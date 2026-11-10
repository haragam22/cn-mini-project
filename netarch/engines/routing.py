"""Routing design RT.R1–R4, OSPF details, Metro failover, eBGP to cloud (technical.md §8.1–8.3).

Pure: plan in, plan out. Runs after the lab mapping and the VPN stage, so every interface the
routing protocols use already exists.
"""

from __future__ import annotations

from netarch.configgen.interface_map import hub_site
from netarch.engines.optics import load_data, value
from netarch.engines.vlsm import dotted, first_host, last_host, mask, wildcard
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.decisions import Decision
from netarch.models.plan import (
    BgpNeighbor,
    BgpProcess,
    Device,
    Interface,
    NetworkPlan,
    OspfIf,
    OspfNetwork,
    OspfProcess,
)
from netarch.models.requirements import Requirements, parse_cidr


def is_multi_area(req: Requirements, subnets: int) -> bool:
    """RT.R2: multi-site WAN over the Internet (global) or ≥ threshold subnets."""
    return req.profile_type == "global" or subnets >= value(load_data("design.yaml"),
                                                             "ospf_subnet_threshold")


def site_areas(req: Requirements, multi: bool) -> dict[str, int]:
    if not multi:
        return {s.id: 0 for s in req.sites}
    hub = hub_site(req) if any(s.kind == "hq" for s in req.sites) or \
        req.profile_type == "global" else None
    out, n = {}, 1
    for s in req.sites:
        if s.id == hub:
            out[s.id] = 0
        else:
            out[s.id], n = n, n + 1
    return out


def _net(i: Interface) -> OspfNetwork:
    net, p, _ = parse_cidr(i.subnet or "")
    return OspfNetwork(network=dotted(net), wildcard=dotted(wildcard(p)), area=0)


def _transit(i: Interface) -> bool:
    return (i.kind in ("physical", "sub") and i.ip is not None and i.vlan is None) or \
        (i.kind == "sub" and i.description.startswith("EVPL")) or i.kind == "tunnel"


def run(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    ap = plan.addressing
    design = load_data("design.yaml")
    ref = value(design, "ospf_reference_bandwidth_mbps")
    n_subnets = len(ap.subnets) if ap else 0
    multi = is_multi_area(req, n_subnets)
    areas = site_areas(req, multi)
    hub = hub_site(req)
    dual = req.resiliency == "dual_homed"
    hello, dead = value(design, "metro_hello_s"), value(design, "metro_dead_s")
    cost_p, cost_b = value(design, "primary_cost"), value(design, "backup_cost")
    bgp_tunnels = {t.a: t for t in plan.vpn_tunnels if t.routing == "bgp"}
    site_blocks = {b.site: b.block for b in ap.site_blocks} if ap else {}
    hub_host = next((d.hostname for d in plan.devices
                     if d.site == hub and d.role in ("router", "l3switch")), "")
    devices: list[Device] = []
    adjacencies = 0
    for d in plan.devices:
        if d.role not in ("router", "l3switch") or d.hostname == "cloud-vgw":
            devices.append(d)
            continue
        area = areas[d.site]
        ifs: list[Interface] = []
        nets: list[OspfNetwork] = []
        active: list[str] = []
        for i in d.interfaces:
            if i.ip is None or i.description == "Internet (public)" or i.subnet is None:
                ifs.append(i)
                continue
            tunnel_bgp = i.kind == "tunnel" and i.peer and i.peer.startswith("cloud-vgw:")
            if tunnel_bgp:
                ifs.append(i)
                continue
            transit = _transit(i)
            a = 0 if transit or i.kind == "loopback" else area
            o = OspfIf(area=a, point_to_point=transit)
            if transit and dual and i.kind == "sub":
                touches_hub = d.hostname == hub_host or (i.peer or "").startswith(hub_host) or \
                    i.description.endswith(f"to {hub_host}")
                o = o.model_copy(update={"hello": hello, "dead": dead,
                                         "cost": cost_p if touches_hub else cost_b})
            if transit:
                active.append(i.name)
                adjacencies += 1
            nets.append(_net(i).model_copy(update={"area": a}))
            ifs.append(i.model_copy(update={"ospf": o}))
        lo = next(i for i in d.interfaces if i.name == "Loopback0")
        ranges = []
        if multi and area != 0:
            bnet, bp, _ = parse_cidr(site_blocks[d.site])
            ranges.append(OspfNetwork(network=dotted(bnet), wildcard=dotted(mask(bp)), area=area))
        ospf = OspfProcess(router_id=lo.ip or "", reference_bandwidth=ref,
                           networks=_dedupe(nets), active_interfaces=active, area_ranges=ranges)
        dev = d.model_copy(update={"interfaces": ifs, "ospf": ospf})
        if d.hostname in bgp_tunnels:
            dev = _hub_bgp(dev, plan, bgp_tunnels[d.hostname], design)
        devices.append(dev)
    if "cloud-vgw" in {d.hostname for d in devices}:
        devices = [_cloud_bgp(d, plan, design) if d.hostname == "cloud-vgw" else d
                   for d in devices]
    plan = plan.model_copy(update={"devices": devices})
    plan = plan.model_copy(update={"routing": plan.routing.model_copy(update={
        "protocol": "OSPFv2 multi-area" if multi else "OSPFv2 single area 0",
        "process_ids": {d.hostname: 1 for d in devices if d.ospf},
        "areas": {s: a for s, a in areas.items()},
        "asns": {d.hostname: d.bgp.asn for d in devices if d.bgp},
        "router_ids": {d.hostname: d.ospf.router_id for d in devices if d.ospf},
    })})
    return _decisions(plan, multi, n_subnets, areas, adjacencies // 2)


def _dedupe(nets: list[OspfNetwork]) -> list[OspfNetwork]:
    seen, out = set(), []
    for n in nets:
        k = (n.network, n.wildcard, n.area)
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


def _org_summary(plan: NetworkPlan) -> tuple[str, str]:
    net, p, _ = parse_cidr(plan.addressing.org_summary)
    return dotted(net), dotted(mask(p))


def _hub_bgp(d: Device, plan: NetworkPlan, t, design) -> Device:
    req = plan.requirements
    net, p, _ = parse_cidr(t.subnet)
    cloud_ip = dotted(last_host(net, p))  # vpn.py: hub = first host, cloud = last host
    org_net, org_mask = _org_summary(plan)
    vnet, vp, _ = parse_cidr(req.cloud.vpc_cidr)
    bgp = BgpProcess(asn=value(design, "org_asn"), router_id=d.ospf.router_id,
                     neighbors=[BgpNeighbor(ip=cloud_ip, remote_as=value(design, "cloud_asn"),
                                            description="cloud-vgw")],
                     networks=[(org_net, org_mask)])
    return d.model_copy(update={
        "bgp": bgp,
        "static_routes": [*d.static_routes, (org_net, org_mask, "Null0")],
        "prefix_lists": {"VPC-ONLY": [f"seq 5 permit {dotted(vnet)}/{vp}"]},
        "route_maps": {"BGP-TO-OSPF": ["permit 10", " match ip address prefix-list VPC-ONLY"]},
        "ospf": d.ospf.model_copy(update={"redistribute_bgp": "BGP-TO-OSPF"}),
    })


def _cloud_bgp(d: Device, plan: NetworkPlan, design) -> Device:
    req = plan.requirements
    t = next(t for t in plan.vpn_tunnels if t.b == "cloud-vgw")
    net, p, _ = parse_cidr(t.subnet)
    hub_ip = dotted(first_host(net, p))
    vnet, vp, _ = parse_cidr(req.cloud.vpc_cidr)
    vpc_lo = next(i for i in d.interfaces if i.name == "Loopback1")
    bgp = BgpProcess(asn=value(design, "cloud_asn"), router_id=vpc_lo.ip or "",
                     neighbors=[BgpNeighbor(ip=hub_ip, remote_as=value(design, "org_asn"),
                                            description=t.a)],
                     networks=[(dotted(vnet), dotted(mask(vp)))])
    return d.model_copy(update={"bgp": bgp})


def _decisions(plan: NetworkPlan, multi: bool, n_subnets: int, areas: dict[str, int],
               adjacencies: int) -> NetworkPlan:
    req = plan.requirements
    std = load_data("standards.yaml")
    design = load_data("design.yaml")
    thr = value(design, "ospf_subnet_threshold")
    ref = value(design, "ospf_reference_bandwidth_mbps")
    n0 = sum(d.id.startswith("RT-") for d in plan.decisions)
    out: list[Decision] = []

    def nid() -> str:
        return decision_id("RT", n0 + len(out) + 1)

    kinds = {}
    for r in plan.addressing.subnets:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    count = (f"subnets = {kinds.get('segment', 0)} segments + {kinds.get('p2p', 0)} "
             f"point-to-point + {kinds.get('loopback', 0)} loopbacks = {n_subnets}")
    l3 = [d for d in plan.devices if d.ospf]
    if multi:
        rule, choice = "RT.R2", f"OSPFv2 multi-area ({len(set(areas.values()))} areas)"
        why_math = [count, "profile is a multi-site WAN over the Internet"
                    if req.profile_type == "global" else f"{n_subnets} ≥ {thr}"]
        rej_area = rejected("single area 0", "every site's LSAs would flood every router and "
                            "every change would rerun SPF everywhere")
    else:
        rule, choice = "RT.R1", "OSPFv2, single area 0"
        why_math = [count, f"{n_subnets} < {thr} and no Internet WAN"]
        rej_area = rejected("multi-area OSPF", f"only {n_subnets} subnets; ABRs add config with "
                            "no LSDB saving at this size")
    out.append(make_decision(
        id=nid(), domain="routing", subject="Interior routing protocol", choice=choice,
        rule_id=rule, inputs={"subnets": n_subnets, "routers": len(l3),
                              "profile": req.profile_type},
        math=why_math + [f"planned OSPF adjacencies: {adjacencies}"],
        standards=[std["rfc_2328"]],
        rejected=[rej_area,
                  rejected("EIGRP", "Cisco-specific; OSPF is an open standard and the cloud "
                           "edge cannot speak EIGRP"),
                  rejected("static routes", "no automatic failover; every new subnet needs "
                           "edits on every router")],
        counterfactual=(f"Would split into areas at ≥ {thr} subnets or with an Internet WAN."
                        if not multi else "Would collapse to area 0 below "
                        f"{thr} subnets without an Internet WAN."),
    ))
    out.append(make_decision(
        id=nid(), domain="routing", subject="OSPF tuning on every router",
        choice=f"auto-cost reference-bandwidth {ref}, passive-interface default, "
               "point-to-point transit links, router-ID = Loopback0",
        rule_id="RT.OSPF",
        inputs={"reference_bandwidth_mbps": ref, "routers": len(l3)},
        math=[f"cost = {ref} ÷ bandwidth: 10 Gbps → {ref // 10000}, 1 Gbps → {ref // 1000}, "
              f"100 Mbps → {ref // 100}",
              "default reference 100 Mbps: 1 Gbps and 10 Gbps would both cost 1",
              "router-IDs: " + ", ".join(f"{d.hostname}={d.ospf.router_id}" for d in l3)],
        standards=[std["rfc_2328"]],
        rejected=[rejected("default reference bandwidth (100 Mbps)",
                           "every link ≥ 100 Mbps gets cost 1, so OSPF cannot prefer 10G")],
    ))
    if req.resiliency == "dual_homed" and any(
            i.ospf and i.ospf.hello for d in l3 for i in d.interfaces):
        h, dd = value(design, "metro_hello_s"), value(design, "metro_dead_s")
        default = value(design, "ospf_default_dead_s")
        p, b = value(design, "primary_cost"), value(design, "backup_cost")
        out.append(make_decision(
            id=nid(), domain="routing", subject="Dual-homed failover",
            choice=f"primary EVPL cost {p}, backup cost {b}, hello {h} s / dead {dd} s",
            rule_id="RT.FAILOVER",
            inputs={"hello_s": h, "dead_s": dd, "primary_cost": p, "backup_cost": b},
            math=[f"detection ≤ dead interval: {dd} s vs default {default} s",
                  f"remote → HQ: primary path cost {p}; via Colo {b} + {p} = {b + p}"],
            standards=[std["rfc_2328"]],
            rejected=[rejected("BFD", "sub-second detection, but Packet Tracer does not run "
                               "it (documented as out of scope)"),
                      rejected("default timers", f"up to {default} s of black-holing")],
            counterfactual="Equal costs would load-share instead of primary/backup.",
        ))
    if multi:
        ranges = [f"{d.hostname}: area {r.area} range {r.network} {r.wildcard}"
                  for d in l3 for r in d.ospf.area_ranges]
        out.append(make_decision(
            id=nid(), domain="routing", subject="Areas and ABR summarisation",
            choice=f"area 0 = hub LAN + transit + loopbacks; {len(ranges)} site areas "
                   "summarised at their ABR",
            rule_id="RT.AREA", inputs={"areas": dict(areas)},
            math=ranges or ["no non-backbone areas"],
            standards=[std["rfc_2328"], std["rfc_4632"]],
            rejected=[rejected("no area range", "every site subnet would appear as its own "
                               "inter-area route at the hub")],
        ))
    hub_bgp = next((d for d in plan.devices if d.bgp and d.hostname != "cloud-vgw"), None)
    if hub_bgp:
        cloud = next(d for d in plan.devices if d.hostname == "cloud-vgw")
        out.append(make_decision(
            id=nid(), domain="routing", subject="Boundary with the cloud VPC",
            choice=f"eBGP AS {hub_bgp.bgp.asn} ↔ AS {cloud.bgp.asn} over the IPsec tunnel",
            rule_id="RT.R3",
            inputs={"org_asn": hub_bgp.bgp.asn, "cloud_asn": cloud.bgp.asn,
                    "vpc": req.cloud.vpc_cidr, "org_summary": plan.addressing.org_summary},
            math=[f"hub advertises {plan.addressing.org_summary}, anchored by a static route "
                  "to Null0 so the network statement always matches",
                  f"only {req.cloud.vpc_cidr} is redistributed into OSPF (prefix-list VPC-ONLY)"],
            standards=[std["rfc_4271"], std["rfc_6996"]],
            rejected=[rejected("OSPF to the cloud", "cloud gateways speak BGP, and an IGP "
                               "across administrative domains has no policy control"),
                      rejected("redistribute all BGP", "a cloud-side mistake could inject any "
                               "prefix into the org's OSPF")],
        ))
    if req.cloud is not None and req.profile_type != "global":
        out[-1] = out[-1].model_copy(update={"warnings": [
            *out[-1].warnings, "cloud is set but only the global profile builds a cloud "
            "boundary; ignored."]})
    warnings = [f"{d.id}: {w}" for d in out for w in d.warnings]
    return plan.model_copy(update={"decisions": [*plan.decisions, *out],
                                   "warnings": [*plan.warnings, *warnings]})

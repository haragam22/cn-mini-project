"""Lab mapping: logical design → Packet Tracer devices, ports and cables (technical.md §6.4, §9.1).

Pure: plan in, plan out. The lab is representative (§6.3): per site one L3 device
(3560 distribution switch for campus, 2911 router for metro/global) and one 2960 access switch,
plus one PC per segment. Metro EVPLs ride an `evpl-carrier` 2960 as 802.1Q EVCs (§8.3); the
Global Internet is an `inet-sw` 2960 on an RFC 5737 documentation range.
"""

from __future__ import annotations

import re

from netarch.engines.optics import load_data, value
from netarch.engines.vlsm import dotted, first_host, last_host
from netarch.errors import CapacityError
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.plan import (
    Cable,
    Device,
    EndHost,
    Interface,
    NetworkPlan,
    Subnet,
)
from netarch.models.requirements import Requirements, parse_cidr

NATIVE_NAME = "NATIVE-UNUSED"


def short(port: str) -> str:
    return port.replace("GigabitEthernet", "Gi").replace("FastEthernet", "Fa")


def safe_name(text: str) -> str:
    """IOS-safe token: letters, digits, '-' only (no spaces/newlines reach a config)."""
    s = re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-")[:40]
    return s or "x"


def hostnames(req: Requirements) -> dict[str, str]:
    """Site id → base name, unique and IOS-safe."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for s in req.sites:
        base = safe_name(s.id).lower()
        name, n = base, 2
        while name in used:
            name, n = f"{base}-{n}", n + 1
        used.add(name)
        out[s.id] = name
    return out


def is_router_profile(req: Requirements) -> bool:
    return req.profile_type in ("metro", "global")


def hub_site(req: Requirements) -> str:
    return next((s.id for s in req.sites if s.kind == "hq"), req.sites[0].id)


class _Ports:
    """Hands out PT port names per device; refuses to reuse one."""

    def __init__(self) -> None:
        dev = load_data("devices.yaml")
        self.router = list(dev["router"]["ports"])
        self.lab = dev["lab_ports"]
        self.used: dict[str, set[str]] = {}

    def _access(self, model: str) -> list[str]:
        spec = self.lab[model]
        return [f"{spec['access_prefix']}{i}" for i in range(1, value(spec, "access_count") + 1)]

    def take(self, host: str, model: str, pool: str) -> str:
        if model == "2911":
            order = self.router
        elif pool == "uplink":
            order = self.lab[model]["uplink"] + list(reversed(self._access(model)))
        else:
            order = self._access(model)
        used = self.used.setdefault(host, set())
        for p in order:
            if p not in used:
                used.add(p)
                return p
        raise CapacityError(
            field="links", value=host, rule_id="LAB.PORTS",
            message=f"{host} ({model}) has no free port left for the lab mapping.",
            hint="Reduce links/segments per site or split the site.",
        )


def _ip(subnet: Subnet, which: str) -> tuple[str, int]:
    net, p, _ = parse_cidr(subnet.cidr)
    x = {"first": first_host(net, p), "last": last_host(net, p),
         "second": first_host(net, p) + 1 if p < 30 else last_host(net, p)}[which]
    return dotted(x), p


def build(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    ap = plan.addressing
    assert ap is not None, "VLSM must run before the lab mapping"
    names = hostnames(req)
    ports = _Ports()
    native = value(load_data("topology.yaml"), "native_vlan")
    design = load_data("design.yaml")
    routers = is_router_profile(req)
    seg_rows = {(r.site, r.vlan): r for r in ap.subnets if r.kind == "segment"}
    p2p_rows = {r.name: r for r in ap.subnets if r.kind == "p2p"}
    devices: dict[str, Device] = {}
    cabling: list[Cable] = []
    hosts: list[EndHost] = []
    l3_of: dict[str, str] = {}

    def cable(a: str, ap_: str, b: str, bp: str, kind: str, physical: str = "") -> None:
        cabling.append(Cable(a=a, a_port=ap_, b=b, b_port=bp, kind=kind, physical=physical))

    for s in req.sites:
        base = names[s.id]
        vlans = {g.vlan: safe_name(g.name).upper() for g in s.segments}
        seg_vlans = sorted(vlans)
        l3_name = f"rtr-{base}" if routers else f"dist-{base}"
        l3_model = "2911" if routers else "3560-24PS"
        acc_name = f"acc-{base}"
        l3_of[s.id] = l3_name
        lo_net, _, _ = parse_cidr(ap.loopbacks[s.id])
        l3 = Device(hostname=l3_name, model=l3_model, role="router" if routers else "l3switch",
                    site=s.id, ip_routing=not routers)
        acc = Device(hostname=acc_name, model="2960-24TT", role="l2switch", site=s.id,
                     vlans={**vlans, native: NATIVE_NAME}, stp_root_vlans=[] if not routers
                     else seg_vlans)
        ifs: list[Interface] = []
        if routers:
            lan = ports.take(l3_name, l3_model, "uplink")
            up = ports.take(acc_name, "2960-24TT", "uplink")
            ifs.append(Interface(name=lan, kind="physical", mode="none",
                                 description=f"LAN trunk to {acc_name}", peer=f"{acc_name}:{up}"))
            for g in s.segments:
                r = seg_rows[(s.id, g.vlan)]
                ifs.append(Interface(name=f"{lan}.{g.vlan}", kind="sub", vlan=g.vlan,
                                     description=f"{vlans[g.vlan]} gateway", ip=r.gateway,
                                     prefix=r.prefix, subnet=r.cidr))
            acc.interfaces.append(Interface(name=up, kind="physical", mode="trunk",
                                            allowed_vlans=seg_vlans, native_vlan=native,
                                            description=f"Uplink to {l3_name}",
                                            peer=f"{l3_name}:{lan}"))
            cable(l3_name, lan, acc_name, up, "trunk")
        else:
            l3.vlans = {**vlans, native: NATIVE_NAME}
            l3.stp_root_vlans = seg_vlans
            n_up = 2 if req.resiliency == "dual_uplink" else 1
            for _ in range(n_up):
                down = ports.take(l3_name, l3_model, "access")
                up = ports.take(acc_name, "2960-24TT", "uplink")
                trunk = {"kind": "physical", "mode": "trunk", "allowed_vlans": seg_vlans,
                         "native_vlan": native}
                ifs.append(Interface(name=down, description=f"Downlink to {acc_name}",
                                     peer=f"{acc_name}:{up}", **trunk))
                acc.interfaces.append(Interface(name=up, description=f"Uplink to {l3_name}",
                                                peer=f"{l3_name}:{down}", **trunk))
                cable(l3_name, down, acc_name, up, "trunk")
            for g in s.segments:
                r = seg_rows[(s.id, g.vlan)]
                ifs.append(Interface(name=f"Vlan{g.vlan}", kind="svi", vlan=g.vlan,
                                     description=f"{vlans[g.vlan]} gateway", ip=r.gateway,
                                     prefix=r.prefix, subnet=r.cidr))
        ifs.append(Interface(name="Loopback0", kind="loopback", description="router-ID",
                             ip=dotted(lo_net), prefix=32, subnet=ap.loopbacks[s.id]))
        l3.interfaces = ifs

        for g in s.segments:  # one representative PC per segment
            r = seg_rows[(s.id, g.vlan)]
            port = ports.take(acc_name, "2960-24TT", "access")
            acc.interfaces.append(Interface(name=port, kind="physical", mode="access",
                                            vlan=g.vlan, edge_port=True,
                                            description=f"PC {vlans[g.vlan]}"))
            pc = f"pc-{base}-{vlans[g.vlan].lower()}"
            ip, p = _ip(r, "last")
            hosts.append(EndHost(name=pc, site=s.id, segment=g.name, vlan=g.vlan, ip=ip,
                                 prefix=p, gateway=r.gateway or "", switch=acc_name, port=port))
            cable(acc_name, port, pc, "FastEthernet0", "host")
            if g.role == "management":
                mip, mp = _ip(r, "second")
                acc.interfaces.append(Interface(name=f"Vlan{g.vlan}", kind="svi", vlan=g.vlan,
                                                description="switch management", ip=mip,
                                                prefix=mp, subnet=r.cidr))
                acc.default_gateway = r.gateway
        devices[l3_name] = l3
        devices[acc_name] = acc

    # physical inter-site links
    link_ports: list[dict[str, str]] = []
    phys = {lk_i: lk for lk_i, lk in enumerate(req.links)}
    if routers and phys:
        carrier = Device(hostname="evpl-carrier", model="2960-24TT", role="l2switch",
                         site="carrier", vlans={native: NATIVE_NAME})
        devices["evpl-carrier"] = carrier
        wan_if: dict[str, str] = {}
        evcs: dict[str, list[int]] = {}
        base_evc = value(design, "evc_base")
        for i, lk in phys.items():
            evc = base_evc + i
            carrier.vlans[evc] = f"EVC-{evc}"
            row = p2p_rows[f"link:{lk.a}--{lk.b}"]
            ends: dict[str, str] = {}
            for site, which in ((lk.a, "first"), (lk.b, "last")):
                host = l3_of[site]
                if host not in wan_if:
                    wan_if[host] = ports.take(host, "2911", "uplink")
                    devices[host].interfaces.insert(
                        -1, Interface(name=wan_if[host], kind="physical", mode="none",
                                      description="EVPL handoff to evpl-carrier"))
                evcs.setdefault(host, []).append(evc)
                ip, p = _ip(row, which)
                other = l3_of[lk.b if site == lk.a else lk.a]
                sub = f"{wan_if[host]}.{evc}"
                devices[host].interfaces.insert(
                    -1, Interface(name=sub, kind="sub", vlan=evc, ip=ip, prefix=p,
                                  subnet=row.cidr, description=f"EVPL EVC {evc} to {other}"))
                ends[host] = sub
            link_ports.append(ends)
        for host, wan in wan_if.items():
            cport = ports.take("evpl-carrier", "2960-24TT", "access")
            allowed = sorted(evcs[host])
            carrier.interfaces.append(Interface(
                name=cport, kind="physical", mode="trunk", allowed_vlans=allowed,
                native_vlan=native, description=f"EVPL UNI to {host}", peer=f"{host}:{wan}"))
            for d in devices[host].interfaces:
                if d.name == wan:
                    d.peer = f"evpl-carrier:{cport}"
            cable(host, wan, "evpl-carrier", cport, "trunk", "carrier EVPL handoff")
    else:
        for lk in phys.values():
            row = p2p_rows[f"link:{lk.a}--{lk.b}"]
            ha, hb = l3_of[lk.a], l3_of[lk.b]
            pa = ports.take(ha, devices[ha].model, "uplink")
            pb = ports.take(hb, devices[hb].model, "uplink")
            for host, port, which, other, oport in ((ha, pa, "first", hb, pb),
                                                    (hb, pb, "last", ha, pa)):
                ip, p = _ip(row, which)
                devices[host].interfaces.insert(-1, Interface(
                    name=port, kind="physical", mode="routed", ip=ip, prefix=p, subnet=row.cidr,
                    description=f"Routed link to {other}", peer=f"{other}:{oport}"))
            pl = next(x for x in plan.links if (x.a, x.b) == (lk.a, lk.b))
            cable(ha, pa, hb, pb, "routed", f"{pl.media} + {pl.optic}")
            link_ports.append({ha: pa, hb: pb})

    links = [pl.model_copy(update={"ports": lp}) for pl, lp in zip(plan.links, link_ports,
                                                                   strict=True)]
    if routers and req.profile_type == "global":
        _internet(req, devices, l3_of, ports, cable, design)
    plan = plan.model_copy(update={"devices": list(devices.values()), "cabling": cabling,
                                   "hosts": hosts, "links": links})
    return _decision(plan, routers)


def _internet(req, devices, l3_of, ports, cable, design) -> None:
    pub_net, pub_p, _ = parse_cidr(value(design, "public_block"))
    vlan = value(design, "internet_vlan")
    sw = Device(hostname="inet-sw", model="2960-24TT", role="l2switch", site="internet",
                vlans={vlan: "INTERNET"})
    devices["inet-sw"] = sw
    order = [hub_site(req)] + [s.id for s in req.sites if s.id != hub_site(req)]
    hosts_ = [l3_of[s] for s in order]
    if req.cloud is not None:
        devices["cloud-vgw"] = Device(hostname="cloud-vgw", model="2911", role="router",
                                      site="cloud")
        hosts_.append("cloud-vgw")
    if len(hosts_) > (1 << (32 - pub_p)) - 2:
        raise CapacityError(field="sites", value=len(hosts_), rule_id="LAB.PORTS",
                            message="Too many sites for the emulated Internet segment.",
                            hint="Use at most 24 Global sites.")
    for i, host in enumerate(hosts_, start=1):
        port = ports.take(host, "2911", "uplink")  # next free after LAN / EVPL handoff
        sport = ports.take("inet-sw", "2960-24TT", "access")
        d = devices[host]
        intf = Interface(name=port, kind="physical", mode="routed", ip=dotted(pub_net + i),
                         prefix=pub_p, subnet=f"{dotted(pub_net)}/{pub_p}",
                         description="Internet (public)", peer=f"inet-sw:{sport}")
        if d.interfaces and d.interfaces[-1].kind == "loopback":
            d.interfaces.insert(-1, intf)
        else:
            d.interfaces.append(intf)
        sw.interfaces.append(Interface(name=sport, kind="physical", mode="access", vlan=vlan,
                                       edge_port=True, description=f"Internet to {host}",
                                       peer=f"{host}:{port}"))
        cable(host, port, "inet-sw", sport, "access", "Internet access circuit")
    if req.cloud is not None:
        vnet, vp, _ = parse_cidr(req.cloud.vpc_cidr)
        devices["cloud-vgw"].interfaces.append(Interface(
            name="Loopback1", kind="loopback", ip=dotted(vnet + 1), prefix=vp,
            subnet=req.cloud.vpc_cidr, description="emulated cloud VPC"))


def _decision(plan: NetworkPlan, routers: bool) -> NetworkPlan:
    std = load_data("standards.yaml")
    n = 1 + sum(d.id.startswith("TOP-") for d in plan.decisions)
    by_model: dict[str, int] = {}
    for d in plan.devices:
        by_model[d.model] = by_model.get(d.model, 0) + 1
    math = [f"{m}: {c} device(s)" for m, c in sorted(by_model.items())]
    math += [f"{c.a} {short(c.a_port)} ↔ {c.b} {short(c.b_port)} ({c.kind}"
             + (f"; physical: {c.physical}" if c.physical else "") + ")"
             for c in plan.cabling if c.kind != "host"]
    l2 = [d for d in plan.decisions if d.rule_id == "L2.RSTP"]
    real_access = sum(int(d.inputs.get("access_switches", 0) or 0) for d in l2)
    d = make_decision(
        id=decision_id("TOP", n), domain="topology", subject="Packet Tracer lab mapping",
        choice=("one 2911 router + one 2960 access switch per site" if routers
                else "one 3560 distribution + one 2960 access switch per building")
        + f", {len(plan.hosts)} representative PCs",
        rule_id="LAB.MAP",
        inputs={"devices": len(plan.devices), "cables": len(plan.cabling)},
        math=math, standards=[std["ieee_802_1q"]],
        rejected=[rejected("one PT switch per recommended access switch",
                           f"{real_access} access switches would be built by hand for no extra "
                           "protocol coverage; one per site exercises every VLAN and trunk")],
        counterfactual="Port names would change with other PT models; logical config would not.",
    )
    return plan.model_copy(update={"decisions": [*plan.decisions, d]})

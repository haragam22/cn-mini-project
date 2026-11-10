"""ACL policy matrix → extended ACLs near the source, VTY access-class (technical.md §8.6).

Pure: plan in, plan out. Every ACL ends with an explicit deny (``log`` where the dialect allows),
so the implicit deny is visible in configs and in Batfish.
"""

from __future__ import annotations

from netarch.configgen.interface_map import hub_site
from netarch.engines.optics import load_data, value
from netarch.engines.vlsm import dotted, wildcard
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.decisions import Decision
from netarch.models.plan import AclEntry, AclPolicy, Device, NetworkPlan
from netarch.models.requirements import parse_cidr


def wc(cidr: str) -> str:
    """'10.0.8.0/23' → '10.0.8.0 0.0.1.255'; /32 → 'host a.b.c.d'."""
    net, p, _ = parse_cidr(cidr)
    return f"host {dotted(net)}" if p == 32 else f"{dotted(net)} {dotted(wildcard(p))}"


def _p(action: str, text: str, log: bool = False) -> AclEntry:
    return AclEntry(action=action, text=text, log=log)


def _deny_all() -> AclEntry:
    return _p("deny", "ip any any", log=True)


def run(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    ap = plan.addressing
    d = load_data("design.yaml")
    std = load_data("standards.yaml")
    segs = [(r, next(g for s in req.sites if s.id == r.site for g in s.segments
                     if g.vlan == r.vlan)) for r in ap.subnets if r.kind == "segment"]
    by_role: dict[str, list] = {}
    for r, g in segs:
        by_role.setdefault(g.role, []).append(r)
    gw = {d_.site: d_ for d_ in plan.devices if d_.role in ("router", "l3switch")
          and d_.site in {s.id for s in req.sites}}
    devices = {x.hostname: x for x in plan.devices}
    acls: list[AclPolicy] = []
    attach: list[tuple[str, str, str, str]] = []  # host, interface, direction, acl
    decisions: list[Decision] = []
    n0 = sum(x.id.startswith("SEC-") for x in plan.decisions)

    def add_decision(**kw) -> None:
        decisions.append(make_decision(id=decision_id("SEC", n0 + len(decisions) + 1),
                                       domain="security", standards=[std["cisco_acl"]], **kw))

    def gw_if(site: str, vlan: int) -> tuple[str, str]:
        dev = gw[site]
        i = next(i for i in dev.interfaces if i.vlan == vlan and i.kind in ("svi", "sub"))
        return dev.hostname, i.name

    mgmt, servers = by_role.get("management", []), by_role.get("servers", [])
    tcp_w, udp_w = value(d, "wifi_server_tcp_ports"), value(d, "wifi_server_udp_ports")
    for w in by_role.get("wireless", []):
        src = wc(w.cidr)
        e = [_p("deny", f"ip {src} {wc(m.cidr)}", True) for m in mgmt]
        for s in servers:
            e += [_p("permit", f"tcp {src} {wc(s.cidr)} eq {port}") for port in tcp_w]
            e += [_p("permit", f"udp {src} {wc(s.cidr)} eq {port}") for port in udp_w]
            e.append(_p("deny", f"ip {src} {wc(s.cidr)}", True))
        e += [_p("permit", f"ip {src} any"), _deny_all()]
        host, intf = gw_if(w.site, w.vlan)
        name = f"WIFI-IN-{w.vlan}"
        acls.append(AclPolicy(name=name, device=host, entries=e, purpose="wireless isolation"))
        attach.append((host, intf, "in", name))
    if by_role.get("wireless"):
        add_decision(
            subject="Wireless segment policy", rule_id="SEC.WIFI",
            choice=f"WIFI → MGMT deny; WIFI → SERVERS tcp {'/'.join(map(str, tcp_w))} + udp "
                   f"{'/'.join(map(str, udp_w))} only; rest permitted",
            inputs={"wireless_segments": len(by_role["wireless"]), "mgmt_subnets": len(mgmt),
                    "server_subnets": len(servers)},
            math=[f"inbound on each WIFI gateway: {len(mgmt)} deny + {len(servers)} × "
                  f"({len(tcp_w) + len(udp_w)} permit + 1 deny) + permit + explicit deny"],
            rejected=[rejected("ACL at the destination (MGMT/SERVERS SVIs)",
                               "denied traffic would cross the network first; filtering at the "
                               "source drops it at the first hop")],
        )

    hq_trading = [r for r, g in segs if g.role == "trading"
                  and next(s for s in req.sites if s.id == r.site).kind == "hq"]
    ports = value(d, "trading_tcp_ports")
    for r, g in segs:
        site = next(s for s in req.sites if s.id == r.site)
        if g.role != "trading" or site.kind != "colo" or not hq_trading:
            continue
        e = [_p("permit", f"tcp {wc(h.cidr)} {wc(r.cidr)} eq {port}")
             for h in hq_trading for port in ports] + [_deny_all()]
        host, intf = gw_if(r.site, r.vlan)
        acls.append(AclPolicy(name="TRADING-PROTECT", device=host, entries=e,
                              purpose="colo trading reachable from HQ trading only"))
        attach.append((host, intf, "out", "TRADING-PROTECT"))
        add_decision(
            subject=f"Colo trading segment {r.cidr}", rule_id="SEC.TRADING",
            choice=f"only HQ TRADING → tcp {'/'.join(map(str, ports))}; deny and log the rest",
            inputs={"protected": r.cidr, "allowed_sources": [h.cidr for h in hq_trading]},
            math=[f"{len(hq_trading)} source(s) × {len(ports)} port(s) permits + explicit deny"],
            rejected=[rejected("inbound ACL on every other site's segments",
                               "one rule protecting one destination would be copied to every "
                               "segment of every site; outbound at the colo gateway is the one "
                               "point all paths share")],
            spec_note="Placed outbound at the destination gateway, not near each source: "
                      "§8.6's default placement would need the rule on every segment.",
        )

    hub = hub_site(req)
    collectors = [s for s in servers if s.site == hub]
    tcp_i, udp_i = value(d, "iot_collector_tcp_ports"), value(d, "iot_infra_udp_ports")
    for r in by_role.get("iot", []):
        src = wc(r.cidr)
        e = [_p("permit", f"tcp {src} {wc(c.cidr)} eq {port}") for c in collectors
             for port in tcp_i]
        e += [_p("permit", f"udp {src} {wc(c.cidr)} eq {port}") for c in collectors
              for port in udp_i]
        e.append(_deny_all())
        host, intf = gw_if(r.site, r.vlan)
        name = f"IOT-IN-{r.vlan}"
        acls.append(AclPolicy(name=name, device=host, entries=e, purpose="IoT to collectors"))
        attach.append((host, intf, "in", name))
    if by_role.get("iot"):
        add_decision(
            subject="IoT segment policy", rule_id="SEC.IOT",
            choice=f"IoT → hub servers tcp {'/'.join(map(str, tcp_i))} and udp "
                   f"{'/'.join(map(str, udp_i))} (DNS/NTP); deny ip any any log",
            inputs={"iot_segments": len(by_role["iot"]), "collectors": len(collectors)},
            math=[f"{len(collectors)} collector subnet(s) × {len(tcp_i) + len(udp_i)} ports "
                  "+ explicit deny, inbound on each IoT gateway"],
            rejected=[rejected("permit IoT → any", "a compromised sensor could reach every "
                               "site; IoT only ever talks to its collectors")],
            warnings=[] if collectors else ["no servers segment at the hub: IoT traffic is "
                                            "denied entirely."],
        )

    cloud_t = next((t for t in plan.vpn_tunnels if t.routing == "bgp"), None)
    if cloud_t and req.cloud:
        hub_servers = collectors
        e = [_p("permit", f"ip {wc(s.cidr)} {wc(req.cloud.vpc_cidr)}") for s in hub_servers]
        e.append(_deny_all())
        acls.append(AclPolicy(name="CLOUD-OUT", device=cloud_t.a, entries=e,
                              purpose="VPC reachable from HQ servers only"))
        attach.append((cloud_t.a, cloud_t.a_if, "out", "CLOUD-OUT"))
        add_decision(
            subject=f"Cloud VPC {req.cloud.vpc_cidr}", rule_id="SEC.CLOUD",
            choice="only HQ SERVERS → VPC; outbound on the hub's cloud tunnel",
            inputs={"vpc": req.cloud.vpc_cidr, "hq_server_subnets": len(hub_servers)},
            math=[f"{len(hub_servers)} permit + explicit deny"],
            rejected=[rejected("security groups in the cloud only",
                               "the org edge would still send every site's traffic into the "
                               "tunnel")],
        )

    vty_entries = [_p("permit", wc(m.cidr)) for m in mgmt] + [_p("deny", "any", True)]
    for x in list(devices.values()):
        if not mgmt:
            break
        acls.append(AclPolicy(name="VTY-MGMT", device=x.hostname, kind="standard",
                              entries=vty_entries, purpose="SSH from MGMT only"))
        devices[x.hostname] = x.model_copy(update={"vty_acl": "VTY-MGMT"})
    add_decision(
        subject="Device management access", rule_id="SEC.VTY",
        choice="SSH only (transport input ssh), local login, access-class VTY-MGMT"
               if mgmt else "SSH only, no access-class (no management segment)",
        inputs={"mgmt_subnets": [m.cidr for m in mgmt], "devices": len(devices)},
        math=[f"VTY-MGMT: {len(mgmt)} permit + deny any log"],
        rejected=[rejected("telnet", "credentials cross the network in clear text")],
        warnings=[] if mgmt else ["no management segment: VTY lines are not source-filtered."],
    )

    for host, intf, direction, name in attach:
        dev = devices[host]
        key = "acl_in" if direction == "in" else "acl_out"
        devices[host] = dev.model_copy(update={
            "interfaces": [i.model_copy(update={key: name}) if i.name == intf else i
                           for i in dev.interfaces]})
    for a in acls:
        dev: Device = devices[a.device]
        if a.name not in dev.acls:
            devices[a.device] = dev.model_copy(update={"acls": [*dev.acls, a.name]})
    warnings = [f"{x.id}: {w}" for x in decisions for w in x.warnings]
    return plan.model_copy(update={
        "devices": list(devices.values()), "acl_policies": [*plan.acl_policies, *acls],
        "decisions": [*plan.decisions, *decisions], "warnings": [*plan.warnings, *warnings],
    })

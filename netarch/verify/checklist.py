"""Packet Tracer checklist (technical.md §11.3): devices, cabling, load steps, commands."""

from __future__ import annotations

from netarch.configgen.interface_map import short
from netarch.models.plan import NetworkPlan


def build_checklist(plan: NetworkPlan) -> str:
    req = plan.requirements
    out = [f"# Packet Tracer checklist — {req.profile_name} ({req.profile_type})", "",
           "## 1. Devices", "", "| Hostname | PT model | Role |", "|---|---|---|"]
    out += [f"| {d.hostname} | {d.model} | {d.role} |" for d in plan.devices]
    out += [f"| {h.name} | PC-PT | end host {h.ip}/{h.prefix} gw {h.gateway} |"
            for h in plan.hosts]
    out += ["", "## 2. Cabling", "", "| From | Port | To | Port | Type | Stands for |",
            "|---|---|---|---|---|---|"]
    role = {d.hostname: d.role for d in plan.devices}
    switch = ("l2switch", "l3switch")
    for c in plan.cabling:
        both_switches = role.get(c.a) in switch and role.get(c.b) in switch
        both_routers = role.get(c.a) == "router" and role.get(c.b) == "router"
        cable = ("copper cross-over" if both_switches or both_routers
                 else "copper straight-through")
        out.append(f"| {c.a} | {short(c.a_port)} | {c.b} | {short(c.b_port)} | {cable} | "
                   f"{c.physical or c.kind} |")
    out += ["", "## 3. Load the configs", "",
            "1. Place and cable the devices above (exact models and ports).",
            "2. For each device: CLI tab → `enable` → `configure terminal` → paste "
            "`configs/<hostname>.txt` (pt dialect).",
            "3. Each PC: Desktop → IP Configuration → static IP / mask / gateway from §1.",
            "4. `copy running-config startup-config` on every device."]
    if any(d.crypto for d in plan.devices):
        out.append("5. Before pasting crypto on each 2911: `license boot module c2900 "
                   "technology-package securityk9`, accept, `write`, `reload`.")
    out += ["", "## 4. Verify", "", "| On | Command | Expected |", "|---|---|---|"]
    for d in plan.devices:
        trunks = [i for i in d.interfaces if i.mode == "trunk"]
        if d.vlans:
            out.append(f"| {d.hostname} | `show vlan brief` | VLANs "
                       f"{','.join(map(str, sorted(d.vlans)))} active |")
        if trunks:
            t = trunks[0]
            out.append(f"| {d.hostname} | `show interfaces trunk` | {short(t.name)} allowed "
                       f"{','.join(map(str, t.allowed_vlans))} · native {t.native_vlan} |")
        if d.ospf:
            n = len(d.ospf.active_interfaces)
            out.append(f"| {d.hostname} | `show ip ospf neighbor` | {n} neighbor(s), FULL |")
        if d.crypto:
            out.append(f"| {d.hostname} | `show crypto isakmp sa` | QM_IDLE to "
                       f"{', '.join(p.peer_ip for p in d.crypto.peers)} (after traffic) |")
        if d.bgp:
            out.append(f"| {d.hostname} | `show ip bgp summary` | neighbor "
                       f"{d.bgp.neighbors[0].ip} up, prefixes received |")
    by_seg = {(h.site, h.segment): h for h in plan.hosts}
    for a in plan.acl_policies:
        if a.name.startswith("WIFI-IN"):
            src = next((h for h in plan.hosts if h.segment.upper().startswith("WIFI")
                        and h.vlan == int(a.name.rsplit("-", 1)[1])), None)
            mg = next((h for (s, g), h in by_seg.items() if g.upper() == "MGMT"), None)
            if src and mg:
                out.append(f"| {src.name} | `ping {mg.gateway}` | FAIL expected (ACL "
                           f"{a.name}) |")
    for h in plan.hosts[:2]:
        out.append(f"| {h.name} | `ping {h.gateway}` | success |")
    return "\n".join(out) + "\n"

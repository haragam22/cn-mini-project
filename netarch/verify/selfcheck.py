"""Self-check: 11 invariants over the generated configs (technical.md §11.1).

Parses the config text with ciscoconfparse2 and compares it with the plan, so a template or
engine bug (or a hand edit) shows up as a FAIL with the check id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ciscoconfparse2 import CiscoConfParse

from netarch.engines.vlsm import FULL, broadcast, dotted, network
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import parse_ipv4

CHECKS = {
    "C1": "interface IPs inside their planned subnet, not network/broadcast",
    "C2": "no duplicate IPs, no overlapping subnets",
    "C3": "both ends of every link share subnet and mask",
    "C4": "VLANs on access/trunk ports exist in the VLAN database",
    "C5": "trunk allowed lists as planned, native 999 both ends, never VLAN 1",
    "C6": "3560 trunks have encapsulation dot1q, 2960 never",
    "C7": "ip routing on every L3 switch with SVIs",
    "C8": "OSPF wildcards valid, transit interfaces covered, router-IDs unique",
    "C9": "every referenced ACL is defined and every defined ACL is used",
    "C10": "GRE tunnel endpoints and crypto ACLs mirror each other",
    "C11": "unique hostnames, no clear-text enable password",
}


@dataclass(frozen=True)
class CheckResult:
    id: str
    device: str
    status: str  # PASS | FAIL
    message: str


@dataclass(frozen=True)
class _If:
    name: str
    lines: list[str]

    def ip(self) -> tuple[int, int] | None:
        for line in self.lines:
            m = re.match(r"ip address (\S+) (\S+)$", line)
            if m:
                ip, msk = parse_ipv4(m[1]), parse_ipv4(m[2])
                return ip, bin(msk).count("1") if _contiguous(msk) else -1
        return None

    def has(self, prefix: str) -> str | None:
        return next((x for x in self.lines if x.startswith(prefix)), None)


def _contiguous(m: int) -> bool:
    inv = ~m & FULL
    return (inv & (inv + 1)) == 0


def _parse(text: str) -> tuple[dict[str, _If], list[str], CiscoConfParse]:
    p = CiscoConfParse(text.splitlines(), syntax="ios")
    ifs = {}
    for obj in p.find_objects(r"^interface "):
        name = obj.text.split(None, 1)[1].strip()
        ifs[name] = _If(name, [c.text.strip() for c in obj.children])
    globals_ = [ln for ln in text.splitlines() if ln and not ln.startswith((" ", "!"))]
    return ifs, globals_, p


def _children(p: CiscoConfParse, parent: str) -> list[str]:
    out = []
    for obj in p.find_objects(parent):
        out += [c.text.strip() for c in obj.children]
    return out


def run_selfcheck(plan: NetworkPlan, configs: dict[str, str]) -> list[CheckResult]:
    res: list[CheckResult] = []

    def fail(cid: str, dev: str, msg: str) -> None:
        res.append(CheckResult(cid, dev, "FAIL", msg))

    parsed = {h: _parse(t) for h, t in configs.items()}
    devs = {d.hostname: d for d in plan.devices}

    # C1, C2
    owners: dict[int, str] = {}
    nets: list[tuple[int, int, str]] = []
    for host, (ifs, _, _) in parsed.items():
        d = devs.get(host)
        for name, i in ifs.items():
            got = i.ip()
            if got is None:
                continue
            ip, p = got
            where = f"{host} {name}"
            if p < 0:
                fail("C1", host, f"{name}: non-contiguous mask")
                continue
            planned = next((x for x in d.interfaces if x.name == name), None) if d else None
            if planned is None or planned.subnet is None:
                fail("C1", host, f"{name}: {dotted(ip)} has no planned subnet")
            else:
                pnet, pp = planned.subnet.split("/")
                pnet_i, pp_i = parse_ipv4(pnet), int(pp)
                if network(ip, pp_i) != pnet_i or p != pp_i:
                    fail("C1", host, f"{name}: {dotted(ip)}/{p} is outside planned "
                                     f"{planned.subnet}")
                elif pp_i < 31 and ip in (network(ip, p), broadcast(ip, p)):
                    fail("C1", host, f"{name}: {dotted(ip)} is the network/broadcast address")
            if ip in owners:
                fail("C2", host, f"{name}: {dotted(ip)} duplicates {owners[ip]}")
            owners[ip] = where
            nets.append((network(ip, p), p, where))
    uniq = {(n, p): w for n, p, w in nets}
    keys = sorted(uniq)
    for i, (n1, p1) in enumerate(keys):
        for n2, p2 in keys[i + 1:]:
            if network(n2, min(p1, p2)) == network(n1, min(p1, p2)):
                fail("C2", "-", f"{dotted(n1)}/{p1} ({uniq[(n1, p1)]}) overlaps "
                                f"{dotted(n2)}/{p2} ({uniq[(n2, p2)]})")

    # C3
    pairs = [tuple(lk.ports.items()) for lk in plan.links if len(lk.ports) == 2]
    pairs += [((t.a, t.a_if), (t.b, t.b_if)) for t in plan.vpn_tunnels]
    for (ha, ia), (hb, ib) in pairs:
        a = parsed.get(ha, ({}, [], None))[0].get(ia)
        b = parsed.get(hb, ({}, [], None))[0].get(ib)
        ga, gb = a.ip() if a else None, b.ip() if b else None
        if not ga or not gb or ga[1] != gb[1] or network(ga[0], ga[1]) != network(gb[0], gb[1]):
            fail("C3", ha, f"{ha} {ia} ↔ {hb} {ib}: subnets/masks differ or missing")

    # C4–C7
    for host, (ifs, gl, _) in parsed.items():
        d = devs.get(host)
        if d is None:
            fail("C11", host, "config for a device that is not in the plan")
            continue
        vlan_db = {int(m[1]) for ln in gl if (m := re.match(r"vlan (\d+)$", ln))}
        for name, i in ifs.items():
            used: set[int] = set()
            if a := i.has("switchport access vlan "):
                used.add(int(a.split()[-1]))
            if t := i.has("switchport trunk allowed vlan "):
                val = t.split()[-1]
                if val == "all":
                    fail("C5", host, f"{name}: 'allowed vlan all'")
                else:
                    used |= {int(x) for x in val.split(",")}
                    planned = next((x for x in d.interfaces if x.name == name), None)
                    if planned and sorted(used) != sorted(planned.allowed_vlans):
                        fail("C5", host, f"{name}: allowed {val} ≠ planned "
                                         f"{','.join(map(str, planned.allowed_vlans))}")
            if i.has("switchport mode trunk"):
                nv = i.has("switchport trunk native vlan ")
                if not nv or nv.split()[-1] != "999":
                    fail("C5", host, f"{name}: native VLAN is not 999")
                if nv:
                    used.add(int(nv.split()[-1]))
                enc = i.has("switchport trunk encapsulation dot1q")
                if d.model.startswith("3560") and not enc:
                    fail("C6", host, f"{name}: 3560 trunk without encapsulation dot1q")
            if 1 in used:
                fail("C5", host, f"{name}: uses VLAN 1")
            if d.role != "router" and (missing := used - vlan_db):
                fail("C4", host, f"{name}: VLAN(s) {sorted(missing)} not in the VLAN database")
        text = configs[host]
        if d.model.startswith("2960") and "encapsulation dot1q" in text:
            fail("C6", host, "2960 config contains 'encapsulation dot1q'")
        svis = [n for n, i in ifs.items() if n.lower().startswith("vlan") and i.ip()]
        if d.role == "l3switch" and svis and "ip routing" not in gl:
            fail("C7", host, "SVIs without 'ip routing'")

    # C8
    rids: dict[str, str] = {}
    for host, (ifs, _, p) in parsed.items():
        lines = _children(p, r"^router ospf ")
        if not lines:
            continue
        stmts = []
        for ln in lines:
            if m := re.match(r"network (\S+) (\S+) area (\d+)$", ln):
                w = parse_ipv4(m[2])
                if not _contiguous(~w & FULL):
                    fail("C8", host, f"'{ln}': {m[2]} is not a valid wildcard")
                    continue
                stmts.append((parse_ipv4(m[1]), 32 - w.bit_length()))
            if m := re.match(r"router-id (\S+)$", ln):
                if m[1] in rids:
                    fail("C8", host, f"router-id {m[1]} duplicates {rids[m[1]]}")
                rids[m[1]] = host
        active = {ln.split()[-1] for ln in lines if ln.startswith("no passive-interface ")}
        for name in active:
            got = ifs.get(name).ip() if name in ifs else None
            if got is None or not any(network(got[0], sp) == sn for sn, sp in stmts):
                fail("C8", host, f"transit interface {name} not covered by a network statement")

    # C9
    for host in parsed:
        text = configs[host]
        defined = set(re.findall(r"^ip access-list (?:extended|standard) (\S+)$", text, re.M))
        refs = set(re.findall(r"^\s*ip access-group (\S+) (?:in|out)$", text, re.M))
        refs |= set(re.findall(r"^\s*access-class (\S+) in$", text, re.M))
        refs |= set(re.findall(r"^\s*match address (\S+)$", text, re.M))
        for name in sorted(refs - defined):
            fail("C9", host, f"ACL {name} is referenced but not defined")
        for name in sorted(defined - refs):
            fail("C9", host, f"ACL {name} is defined but never applied")

    # C10
    for t in plan.vpn_tunnels:
        a, b = parsed.get(t.a, ({},))[0].get(t.a_if), parsed.get(t.b, ({},))[0].get(t.b_if)
        if not a or not b:
            fail("C10", t.a, f"tunnel {t.name}: interface missing")
            continue
        a_dst = (a.has("tunnel destination ") or "").split()[-1:]
        b_dst = (b.has("tunnel destination ") or "").split()[-1:]
        if a_dst != [t.b_public] or b_dst != [t.a_public]:
            fail("C10", t.a, f"tunnel {t.name}: destinations are not mirror images")
        fwd = f"permit gre host {t.a_public} host {t.b_public}"
        rev = f"permit gre host {t.b_public} host {t.a_public}"
        if fwd not in configs.get(t.a, "") or rev not in configs.get(t.b, ""):
            fail("C10", t.a, f"tunnel {t.name}: crypto ACLs do not mirror")
        for host, intf, own in ((t.a, a, t.a_public), (t.b, b, t.b_public)):
            src = (intf.has("tunnel source ") or "").split()[-1:]
            src_if = parsed[host][0].get(src[0]) if src else None
            if not src_if or not src_if.ip() or dotted(src_if.ip()[0]) != own:
                fail("C10", host, f"tunnel {t.name}: tunnel source is not {own}")
        ka = re.search(rf"^crypto isakmp key (\S+) address {re.escape(t.b_public)}$",
                       configs.get(t.a, ""), re.M)
        kb = re.search(rf"^crypto isakmp key (\S+) address {re.escape(t.a_public)}$",
                       configs.get(t.b, ""), re.M)
        if not ka or not kb or ka[1] != kb[1]:
            fail("C10", t.a, f"tunnel {t.name}: pre-shared keys differ or are missing")

    # C11
    names: dict[str, str] = {}
    for host, text in configs.items():
        m = re.search(r"^hostname (\S+)$", text, re.M)
        hn = m[1] if m else ""
        if not hn or hn in names:
            fail("C11", host, f"hostname '{hn}' missing or duplicated")
        names[hn] = host
        if re.search(r"^enable password ", text, re.M):
            fail("C11", host, "clear-text 'enable password'")

    failed = {r.id for r in res}
    res += [CheckResult(cid, "*", "PASS", desc) for cid, desc in CHECKS.items()
            if cid not in failed]
    return sorted(res, key=lambda r: (int(r.id[1:]), r.status, r.device))


def all_pass(results: list[CheckResult]) -> bool:
    return all(r.status == "PASS" for r in results)

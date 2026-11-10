"""Batfish verification of the `full` configs (technical.md §11.2), with graceful skip.

If Batfish does not answer within 3 s, the result is ``NOT CONNECTED (skipped)`` and the CLI
exit code reflects only the self-check.
"""

from __future__ import annotations

import json
import socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from netarch.models.plan import NetworkPlan

PORT = 9996
TIMEOUT_S = 3.0


@dataclass
class BatfishResult:
    status: str  # PASS | FAIL | NOT CONNECTED (skipped)
    checks: list[tuple[str, str, str]] = field(default_factory=list)  # name, PASS/FAIL, detail

    @property
    def skipped(self) -> bool:
        return self.status.startswith("NOT CONNECTED")

    def report_md(self) -> str:
        lines = [f"# Batfish report — {self.status}", "", "| Check | Result | Detail |",
                 "|---|---|---|"]
        lines += [f"| {n} | {s} | {d} |" for n, s, d in self.checks]
        return "\n".join(lines) + "\n"


def reachable(host: str, port: int = PORT, timeout: float = TIMEOUT_S) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_snapshot(plan: NetworkPlan, configs: dict[str, str], root: Path) -> Path:
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "hosts").mkdir(exist_ok=True)
    for h, text in configs.items():
        (root / "configs" / f"{h}.cfg").write_text(text, encoding="utf-8")
    for h in plan.hosts:
        (root / "hosts" / f"{h.name}.json").write_text(json.dumps({
            "hostname": h.name, "iptablesFile": None, "hostInterfaces": {
                "eth0": {"name": "eth0", "prefix": f"{h.ip}/{h.prefix}",
                         "gateway": h.gateway}},
        }), encoding="utf-8")
    return root


def summary_expectations(plan: NetworkPlan) -> list[tuple[str, set[str], set[str]]]:
    """Hub router must see each other area's site block and none of its segment subnets."""
    if not plan.addressing:
        return []
    ranged = {d.site for d in plan.devices if d.ospf and d.ospf.area_ranges}
    hub = next((d.hostname for d in plan.devices
                if d.ospf and not d.ospf.area_ranges and d.role == "router"), None)
    if not hub or not ranged:
        return []
    blocks = {b.site: b.block for b in plan.addressing.site_blocks}
    present = {blocks[s] for s in ranged}
    absent = {r.cidr for r in plan.addressing.subnets if r.site in ranged} - present
    return [(hub, present, absent)]


def run_batfish(plan: NetworkPlan, configs: dict[str, str], host: str = "localhost"
                ) -> BatfishResult:
    if not reachable(host):
        return BatfishResult("NOT CONNECTED (skipped)")
    from pybatfish.client.session import Session  # pragma: no cover - needs Batfish

    bf = Session(host=host)  # pragma: no cover
    bf.set_network(f"netarch-{plan.requirements.profile_type}")  # pragma: no cover
    with tempfile.TemporaryDirectory() as tmp:  # pragma: no cover
        bf.init_snapshot(str(build_snapshot(plan, configs, Path(tmp))), name="design",
                         overwrite=True)
    return _questions(bf, plan)  # pragma: no cover


def _questions(bf, plan: NetworkPlan) -> BatfishResult:  # pragma: no cover - needs Batfish
    checks: list[tuple[str, str, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, "PASS" if ok else "FAIL", detail.replace("\n", " ")[:300]))

    st = bf.q.fileParseStatus().answer().frame()
    add("configs parsed", set(st["Status"]) <= {"PASSED"}, ",".join(set(st["Status"])))
    issues = bf.q.initIssues().answer().frame()
    errs = issues[issues["Type"].astype(str).str.contains("error", case=False)]
    add("init issues (errors)", errs.empty, f"{len(errs)} error(s)")
    pw = bf.q.parseWarning().answer().frame()
    add("parse warnings", pw.empty, f"{len(pw)} warning(s)")
    und = bf.q.undefinedReferences().answer().frame()
    add("undefined references", und.empty, f"{len(und)} reference(s)")
    dup = bf.q.ipOwners(duplicatesOnly=True).answer().frame()
    add("duplicate IPs", dup.empty, f"{len(dup)} row(s)")
    ospf = bf.q.ospfSessionCompatibility().answer().frame()
    bad = ospf[ospf["Session_Status"] != "ESTABLISHED"] if not ospf.empty else ospf
    want = sum(len(d.ospf.active_interfaces) for d in plan.devices if d.ospf)
    add("OSPF sessions", bad.empty and len(ospf) == want,
        f"{len(ospf)} sessions (planned {want}), {len(bad)} not established")
    if any(d.bgp for d in plan.devices):
        bgp = bf.q.bgpSessionStatus().answer().frame()
        add("BGP sessions", not bgp.empty and set(bgp["Established_Status"]) == {"ESTABLISHED"},
            ",".join(map(str, set(bgp.get("Established_Status", [])))))
    if plan.vpn_tunnels:
        ips = bf.q.ipsecSessionStatus().answer().frame()
        add("IPsec sessions", not ips.empty and set(ips["Status"]) == {"IPSEC_SESSION_ESTABLISHED"},
            ",".join(map(str, set(ips.get("Status", [])))))
    for host, want_present, want_absent in summary_expectations(plan):
        nets = set(map(str, bf.q.routes(nodes=host).answer().frame().get("Network", [])))
        miss, leak = sorted(want_present - nets), sorted(want_absent & nets)
        add(f"summaries on {host}", not miss and not leak,
            f"missing {miss or 'none'}; per-site subnets leaked {leak or 'none'}")
    flr = bf.q.filterLineReachability().answer().frame()
    add("ACL lines reachable", flr.empty, f"{len(flr)} unreachable line(s)")
    ok = all(s == "PASS" for _, s, _ in checks)
    return BatfishResult("PASS" if ok else "FAIL", checks)

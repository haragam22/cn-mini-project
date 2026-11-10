"""Exports (technical.md §9.4): configs, ZIP, rationale.md, ip-plan.csv, plan.json,
pt-checklist.md, topology.mmd, secrets.txt."""

from __future__ import annotations

import csv
import io
import os
import zipfile
from pathlib import Path

from netarch.configgen.interface_map import safe_name, short
from netarch.configgen.render import make_secrets, render_all
from netarch.explain.render import render_report
from netarch.models.plan import NetworkPlan
from netarch.verify.checklist import build_checklist

ARTEFACTS = ("configs", "rationale", "ip-plan", "plan", "checklist", "topology", "secrets")
DOMAIN_ORDER = ("media", "transceiver", "topology", "switching", "addressing", "routing",
                "vpn", "qos", "security")


def rationale_md(plan: NetworkPlan) -> str:
    parts = [f"# Design rationale — {plan.requirements.profile_name}", ""]
    if plan.warnings:
        parts += ["## Warnings", "", *(f"- {w}" for w in plan.warnings), ""]
    for dom in DOMAIN_ORDER:
        ds = [d for d in plan.decisions if d.domain == dom]
        if ds:
            parts += [f"## {dom.capitalize()}", "", render_report(ds, "markdown")]
    return "\n".join(parts)


def ip_plan_csv(plan: NetworkPlan) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["kind", "site", "name", "vlan", "network", "prefix", "mask", "wildcard",
                "gateway", "first_host", "last_host", "broadcast", "usable", "requested",
                "needed", "utilisation_pct"])
    for r in plan.addressing.subnets if plan.addressing else []:
        w.writerow([r.kind, _csv_safe(r.site or ""), _csv_safe(r.name), r.vlan or "", r.network,
                    r.prefix,
                    r.mask, r.wildcard, r.gateway or "", r.first_host, r.last_host,
                    r.broadcast, r.usable, r.requested, r.needed, r.utilisation_pct])
    return buf.getvalue()


def _csv_safe(text: str) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @, tab, CR at the start)."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def topology_mmd(plan: NetworkPlan) -> str:
    lines = ["flowchart LR"]
    ids = {d.hostname: safe_name(d.hostname).replace("-", "_") for d in plan.devices}
    for d in plan.devices:
        lines.append(f'  {ids[d.hostname]}["{d.hostname}<br/>{d.model}"]')
    for c in plan.cabling:
        if c.kind == "host":
            continue
        lines.append(f'  {ids[c.a]} ---|"{short(c.a_port)} ↔ {short(c.b_port)}"| {ids[c.b]}')
    for t in plan.vpn_tunnels:
        lines.append(f'  {ids[t.a]} -.-|"GRE/IPsec {t.subnet}"| {ids[t.b]}')
    return "\n".join(lines) + "\n"


def _write_private(p: Path, text: str) -> None:
    """Owner-only (0600) file for generated credentials; chmod again if it already existed."""
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.chmod(p, 0o600)


def write_all(plan: NetworkPlan, out: str | Path, *, dialect: str = "pt",
              make_zip: bool = False, only: tuple[str, ...] | None = None,
              secrets: dict[str, str] | None = None, timestamp: str | None = None) -> list[Path]:
    """Write the chosen artefacts under ``out``; returns every path written."""
    out = Path(out)
    want = set(only or ARTEFACTS)
    if bad := want - set(ARTEFACTS):
        raise ValueError(f"unknown artefact(s) {sorted(bad)}; choose from {ARTEFACTS}")
    sec = secrets if secrets is not None else make_secrets(plan)
    configs = render_all(plan, dialect, sec, timestamp=timestamp)
    files: dict[str, str] = {}
    if "configs" in want:
        files |= {f"configs/{h}.txt": t for h, t in configs.items()}
    if "rationale" in want:
        files["rationale.md"] = rationale_md(plan)
    if "ip-plan" in want:
        files["ip-plan.csv"] = ip_plan_csv(plan)
    if "plan" in want:
        files["plan.json"] = plan.model_dump_json(indent=2)
    if "checklist" in want:
        files["pt-checklist.md"] = build_checklist(plan)
    if "topology" in want:
        files["topology.mmd"] = topology_mmd(plan)
    if "secrets" in want:
        files["secrets.txt"] = ("# NetArchitect generated secrets — do NOT commit (git-ignored)\n"
                                + "".join(f"{k} = {v}\n" for k, v in sorted(sec.items())))
    written: list[Path] = []
    for rel, text in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel == "secrets.txt":
            _write_private(p, text)
        else:
            p.write_text(text, encoding="utf-8", newline="\n")
        written.append(p)
    if make_zip:
        z = out / f"netarch-{safe_name(plan.requirements.profile_name)}-configs.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, text in sorted(files.items()):
                if rel != "secrets.txt":
                    zf.writestr(rel, text)
        written.append(z)
    return written

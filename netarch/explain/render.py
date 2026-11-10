"""Decision → plain text / Markdown (technical.md §4.2: engines never write prose).

Every sentence is built from the Decision's own fields (inputs, math, rejected, counterfactual,
warnings, standards, spec_note) plus one fixed "why" sentence per (domain, rule). The why
sentences carry no measured values (m, km, dB, W, nm, Gbps), so every such number in a rationale
comes from the engine's fields.
"""

from __future__ import annotations

import textwrap
from typing import Any

from netarch.models.decisions import Decision

# The engineering reason behind each rule, worded once (technical.md §5–§6).
WHY: dict[tuple[str, str], str] = {
    ("media", "MEDIA.R1"): (
        "The run fits the 10GBASE-T copper channel over Cat6a, the cheapest 10G medium."
    ),
    ("media", "MEDIA.R2"): (
        "The run is too long for copper but within 10GBASE-SR reach over OM4 multimode; that "
        "reach is set by modal dispersion (the fibre's bandwidth-distance product)."
    ),
    ("media", "MEDIA.X1"): (
        "The run is short enough for copper, but it joins two buildings: copper between "
        "buildings is exposed to ground-potential difference, lightning and EMI, so OM4 fibre is "
        "used. Its 10GBASE-SR reach is set by modal dispersion (bandwidth-distance product)."
    ),
    ("media", "MEDIA.R3"): (
        "The run is beyond multimode reach, so OS2 single-mode fibre is used; the optic is then "
        "chosen by optical power budget, not by rated distance alone."
    ),
    ("media", "MEDIA.X2"): (
        "Horizontal cabling follows the TIA-568.2-D channel model: a permanent link plus patch "
        "cords, Cat6a so every port can run 10GBASE-T and PoE."
    ),
    ("transceiver", "MEDIA.R1"): "10GBASE-T is the copper PHY for Cat6a; no optic is needed.",
    ("transceiver", "MEDIA.R2"): (
        "10GBASE-SR is the short-wavelength multimode optic; on OM4 its reach is limited by modal "
        "dispersion (bandwidth-distance product)."
    ),
    ("transceiver", "MEDIA.X1"): (
        "10GBASE-SR is the short-wavelength multimode optic; on OM4 its reach is limited by modal "
        "dispersion (bandwidth-distance product)."
    ),
    ("transceiver", "MEDIA.R3"): (
        "The cheapest optic is chosen whose rated reach covers the distance and whose channel "
        "insertion loss leaves at least the minimum operating margin. The IEEE channel insertion "
        "loss already reserves dispersion penalties, so no extra fixed margin is stacked on top; "
        "the operating margin covers ageing, repairs and dirty connectors."
    ),
    ("topology", "TOP.R1"): (
        "One small building needs no separate distribution layer: access switches uplink to a "
        "single collapsed-core switch block."
    ),
    ("topology", "TOP.R2"): (
        "Each building gets one L3 distribution switch acting as a collapsed core; "
        "inter-building links are routed, so each spanning-tree domain stays inside one "
        "building. A full mesh suits a few blocks; beyond that a hub keeps the link count "
        "linear."
    ),
    ("topology", "TOP.R3"): (
        "With many distribution blocks a full mesh grows quadratically; a dedicated core turns "
        "it into one uplink per block."
    ),
    ("switching", "L2.VLAN"): (
        "One VLAN per segment keeps each broadcast domain and security zone separate. VLAN 1 "
        "is never used for data, and trunks use an unused native VLAN with no SVI so untagged "
        "frames land nowhere (no VLAN hopping by double tagging)."
    ),
    ("switching", "L2.TRUNK"): (
        "Trunks carry exactly the VLANs that exist at the site, never 'all': fewer VLANs on a "
        "trunk means less flooding, fewer spanning-tree instances and no accidental leakage. "
        "Negotiation (DTP) is turned off."
    ),
    ("switching", "L2.RSTP"): (
        "Rapid PVST+ converges by proposal/agreement instead of timers. The building's L3 "
        "distribution switch is root for all its VLANs, so the spanning-tree root coincides "
        "with the SVI gateway and traffic does not detour."
    ),
    ("switching", "L2.CAP"): (
        "Access switches are sized so wired endpoints, access points and uplinks all get a "
        "port, and PoE demand is stated so the PoE switch budget can be checked."
    ),
    ("addressing", "ADDR.SIZE"): (
        "Each subnet must hold its hosts after growth plus the default gateway, plus the "
        "network and broadcast addresses; blocks are powers of two, so the prefix rounds up."
    ),
    ("addressing", "ADDR.P2P"): (
        "A routed link has exactly two ends, so it needs no network or broadcast address; "
        "the prefix depends on whether the target platform accepts 31-bit prefixes."
    ),
    ("addressing", "ADDR.SITE"): (
        "Each site gets one contiguous, aligned block and its subnets are carved from it largest "
        "first, so the whole site is advertised as one summary route and its internal changes "
        "stay local."
    ),
    ("addressing", "ADDR.INFRA"): (
        "Transit links and router loopbacks share one separate block so they never break a "
        "site summary and are easy to filter and recognise."
    ),
    ("addressing", "ADDR.EFF"): (
        "Blocks are placed largest first on aligned boundaries, so there are no gaps between "
        "them and the free space stays in large contiguous blocks."
    ),
    ("topology", "LAB.MAP"): (
        "The Packet Tracer lab is representative: it keeps every protocol, VLAN, trunk and "
        "routed hop of the design with one device per role per site, using real PT port names "
        "so configs paste in unchanged."
    ),
    ("routing", "RT.R1"): (
        "Link-state OSPF converges quickly and, with few subnets and no Internet WAN, one area "
        "keeps the database small enough that a full SPF run is trivial."
    ),
    ("routing", "RT.R2"): (
        "Areas limit LSA flooding and SPF scope to one site; ABR summarisation hides each "
        "site's internal changes from the rest of the network."
    ),
    ("routing", "RT.R3"): (
        "Another administrative domain is joined with eBGP using private ASNs: BGP carries "
        "policy, and cloud gateways speak BGP, not OSPF."
    ),
    ("routing", "RT.OSPF"): (
        "Costs must tell fast links from slow ones, user segments must never form adjacencies, "
        "and stable router-IDs make the LSDB readable."
    ),
    ("routing", "RT.FAILOVER"): (
        "Each remote site is dual-homed: OSPF cost makes the HQ path primary and the Colo path "
        "backup, and short hello/dead timers bound how long a failed EVPL black-holes traffic."
    ),
    ("routing", "RT.AREA"): (
        "Every non-backbone area meets area 0 at its ABR, which advertises the site's single "
        "aligned block as one summary."
    ),
    ("vpn", "RT.R4"): (
        "OSPF hellos are multicast and policy-based IPsec carries no multicast, so OSPF runs "
        "inside GRE tunnels and IPsec protects the GRE packets."
    ),
    ("vpn", "VPN.CRYPTO"): (
        "IKEv1 with a crypto map has the widest Packet Tracer support; the strongest suite the "
        "target accepts is used."
    ),
    ("qos", "QOS.LAT"): (
        "Propagation, serialisation and processing are fixed by distance and hardware; only "
        "queuing varies with load, so the latency target is protected by queuing policy."
    ),
    ("security", "SEC.WIFI"): (
        "Wireless clients are the least trusted users: they must never reach device management "
        "and only reach servers on the service ports they need."
    ),
    ("security", "SEC.TRADING"): (
        "The trading systems are the most sensitive hosts, so only the trading desk may open "
        "connections to them."
    ),
    ("security", "SEC.IOT"): (
        "IoT devices are numerous and hard to patch, so they are limited to their collectors "
        "and to the DNS/NTP services they need."
    ),
    ("security", "SEC.CLOUD"): (
        "The cloud VPC only needs traffic from the HQ servers that use it; everything else is "
        "stopped at the org edge."
    ),
    ("security", "SEC.VTY"): (
        "Management access is encrypted (SSH) and accepted only from the management subnets."
    ),
}

def num(x: Any) -> str:
    """Plain number text: 22000.0 → '22000', 10.01 → '10.01'."""
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return f"{x:.6f}".rstrip("0").rstrip(".")
    return str(x)


def _value(key: str, v: Any) -> str:
    if isinstance(v, list | tuple):
        return ",".join(num(x) for x in v) or "none"
    text = num(v)
    if key.endswith("_m") and isinstance(v, int | float) and not isinstance(v, bool) and v >= 1000:
        text += f" ({num(v / 1000)} km)"
    return text


def _inputs(d: Decision) -> str:
    return ", ".join(f"{k}={_value(k, v)}" for k, v in d.inputs.items() if v is not None)


def why(d: Decision) -> str | None:
    return WHY.get((d.domain, d.rule_id))


def render_rationale(d: Decision) -> str:
    """One paragraph: choice, inputs, why, math, rejected, counterfactual, warnings, standards."""
    lead = f"For {d.subject}, chose {d.choice} (rule {d.rule_id})"
    inputs = _inputs(d)
    if inputs:
        lead += f" given {inputs}"
    parts = [lead + "."]
    if w := why(d):
        parts.append(w)
    if d.math:
        parts.append("Math: " + "; ".join(d.math) + ".")
    if d.rejected:
        parts.append(
            "Rejected: " + "; ".join(f"{r.option} because {r.reason}" for r in d.rejected) + "."
        )
    if d.counterfactual:
        parts.append(d.counterfactual)
    if d.warnings:
        parts.append("Warning: " + " ".join(d.warnings))
    if d.standards:
        parts.append("Standards: " + ", ".join(d.standards) + ".")
    return " ".join(parts)


def _wrap(text: str, indent: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=indent + "  ")


def render_text(d: Decision, width: int = 100) -> str:
    """Readable multi-line block for the terminal."""
    lines = [f"{d.id} [{d.domain}] {d.subject}", f"  Choice: {d.choice} (rule {d.rule_id})"]
    if inputs := _inputs(d):
        lines += _wrap(f"Inputs: {inputs}", "  ", width)
    if w := why(d):
        lines += _wrap(f"Why: {w}", "  ", width)
    if d.math:
        lines.append("  Math:")
        for m in d.math:
            lines += _wrap(f"- {m}", "    ", width)
    if d.rejected:
        lines.append("  Rejected:")
        for r in d.rejected:
            lines += _wrap(f"- {r.option}: {r.reason}", "    ", width)
    if d.counterfactual:
        lines += _wrap(f"Would change: {d.counterfactual}", "  ", width)
    for warn in d.warnings:
        lines += _wrap(f"WARNING: {warn}", "  ", width)
    if d.standards:
        lines += _wrap(f"Standards: {', '.join(d.standards)}", "  ", width)
    if d.spec_note:
        lines += _wrap(f"Spec note: {d.spec_note}", "  ", width)
    return "\n".join(lines)


def render_markdown(d: Decision) -> str:
    lines = [f"### {d.id} · {d.subject}", "", f"**Choice:** {d.choice} (rule `{d.rule_id}`)"]
    if d.inputs:
        lines.append(f"**Inputs:** {_inputs(d)}")
    if w := why(d):
        lines += ["", f"**Why:** {w}"]
    if d.math:
        lines += ["", "**Math:**", *(f"- `{m}`" for m in d.math)]
    if d.rejected:
        lines += ["", "**Rejected:**", *(f"- {r.option}: {r.reason}" for r in d.rejected)]
    if d.counterfactual:
        lines += ["", f"**Counterfactual:** {d.counterfactual}"]
    if d.warnings:
        lines += ["", "**Warnings:**", *(f"- {w}" for w in d.warnings)]
    if d.standards:
        lines += ["", f"**Standards:** {', '.join(d.standards)}"]
    if d.spec_note:
        lines += ["", f"> **Spec note:** {d.spec_note}"]
    return "\n".join(lines)


def render_report(decisions: list[Decision], fmt: str = "text") -> str:
    """All decisions, in order, as one text or Markdown document."""
    if fmt == "markdown":
        return "\n\n".join(render_markdown(d) for d in decisions) + "\n"
    if fmt != "text":
        raise ValueError(f"unknown format {fmt!r}; expected 'text' or 'markdown'")
    return "\n\n".join(render_text(d) for d in decisions) + "\n"

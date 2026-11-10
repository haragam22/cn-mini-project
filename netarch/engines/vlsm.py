"""Bitwise hierarchical VLSM allocator (technical.md §7). Pure: plan in, plan out.

Integer bit math only; ``ipaddress`` is a test oracle, never used here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import ceil
from typing import Any

from netarch.engines.optics import load_data
from netarch.engines.ptcaps import pt_result
from netarch.errors import AddressSpaceExhaustedError
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.decisions import Decision
from netarch.models.plan import AddressingPlan, NetworkPlan, SiteBlock, Subnet
from netarch.models.requirements import Requirements, parse_cidr

Block = tuple[int, int]  # (network, prefix)

# --- §7.1 primitives -------------------------------------------------------------------

FULL = 0xFFFFFFFF


def mask(p: int) -> int:
    return (FULL << (32 - p)) & FULL


def wildcard(p: int) -> int:
    return ~mask(p) & FULL


def network(ip: int, p: int) -> int:
    return ip & mask(p)


def broadcast(ip: int, p: int) -> int:
    return network(ip, p) | wildcard(p)


def block_size(p: int) -> int:
    return 1 << (32 - p)


def usable(p: int) -> int:
    if p == 32:
        return 1
    if p == 31:
        return 2  # RFC 3021
    return block_size(p) - 2


def first_host(net: int, p: int) -> int:
    return net if p >= 31 else net + 1


def last_host(net: int, p: int) -> int:
    if p == 32:
        return net
    if p == 31:
        return broadcast(net, p)
    return broadcast(net, p) - 1


def is_aligned(n: int, p: int) -> bool:
    return (n & wildcard(p)) == 0


def dotted(x: int) -> str:
    return f"{x >> 24 & 255}.{x >> 16 & 255}.{x >> 8 & 255}.{x & 255}"


def cidr(b: Block) -> str:
    return f"{dotted(b[0])}/{b[1]}"


def align_up(x: int, size: int) -> int:
    return (x + size - 1) & ~(size - 1)


def prefix_for_size(n: int) -> int:
    """Longest prefix whose block holds ``n`` addresses (may be < 0 if no IPv4 block does)."""
    return 32 - (max(n, 1) - 1).bit_length()


# --- §7.2 sizing rule ------------------------------------------------------------------


def needed_addresses(hosts: int, growth_pct: float) -> int:
    """ceil(hosts × (1 + growth/100)) + 1 for the default gateway (exact, no float rounding)."""
    return ceil(Fraction(hosts) * (100 + Fraction(str(growth_pct))) / 100) + 1


def segment_prefix(hosts: int, growth_pct: float) -> int:
    """32 − ceil(log2(needed + 2)): + network and broadcast. 253 hosts → /24, 254 → /23."""
    return prefix_for_size(needed_addresses(hosts, growth_pct) + 2)


# --- §7.3 allocation -------------------------------------------------------------------


def _clip(root: Block, r: Block) -> tuple[int, int] | None:
    """Address range [start, end) of ``r`` inside ``root`` (CIDRs nest or are disjoint)."""
    lo, hi = max(root[0], r[0]), min(root[0] + block_size(root[1]), r[0] + block_size(r[1]))
    return (lo, hi) if lo < hi else None


def _exhausted(
    root: Block, requested: int, reserved_in_root: int, *, field: str
) -> AddressSpaceExhaustedError:
    holds = block_size(root[1])
    available = holds - reserved_in_root
    shortfall = requested - available
    fits = prefix_for_size(requested + reserved_in_root)
    held = f"{holds:,}" + (f" ({available:,} after reserved ranges)" if reserved_in_root else "")
    if shortfall > 0:
        short = f"short by {shortfall:,}"
    else:
        short = "the total fits but reserved ranges leave no aligned gap large enough"
    smallest = f"Smallest root that fits: /{fits}." if fits >= 0 else "No IPv4 root is that large."
    return AddressSpaceExhaustedError(
        field=field,
        value={"requested": requested, "available": available, "shortfall": max(shortfall, 0),
               "smallest_root_prefix": fits},
        rule_id="ADDR.E1",
        message=(f"Requested {requested:,} addresses (after rounding) but {cidr(root)} holds "
                 f"{held}; {short}. {smallest}"),
        hint="Use a larger root (shorter prefix), fewer hosts or less growth headroom.",
    )


def place[K](
    root: Block,
    requests: Sequence[tuple[K, int]],
    reserved: Sequence[Block] = (),
    *,
    field: str = "address_space.root",
) -> dict[K, Block]:
    """Place power-of-two blocks in ``root``: size DESC then key ASC, lowest aligned free spot.

    Sorted descending, every block lands on the cursor with no gap (each size divides every
    larger one); reserved ranges are skipped. Raises ``AddressSpaceExhaustedError``.
    """
    used = [c for r in reserved if (c := _clip(root, r))]
    reserved_in_root = sum(hi - lo for lo, hi in used)
    requested = sum(block_size(p) for _, p in requests)
    end = root[0] + block_size(root[1])
    out: dict[K, Block] = {}
    for key, p in sorted(requests, key=lambda kp: (kp[1], kp[0])):
        size = block_size(p)
        cur = align_up(root[0], size)
        while True:
            if cur + size > end:
                raise _exhausted(root, requested, reserved_in_root, field=field)
            hit = next((u for u in used if u[0] < cur + size and cur < u[1]), None)
            if hit is None:
                break
            cur = align_up(hit[1], size)
        out[key] = (cur, p)
        used.append((cur, cur + size))
    return out


def range_to_blocks(lo: int, hi: int) -> list[Block]:
    """[lo, hi) as the fewest aligned CIDR blocks."""
    out: list[Block] = []
    while lo < hi:
        size = lo & -lo if lo else 1 << 32
        while size > hi - lo:
            size >>= 1
        out.append((lo, 32 - (size.bit_length() - 1)))
        lo += size
    return out


def free_blocks(root: Block, taken: Sequence[Block]) -> list[Block]:
    spans = sorted(c for b in taken if (c := _clip(root, b)))
    out: list[Block] = []
    cur = root[0]
    for lo, hi in spans:
        out += range_to_blocks(cur, lo)
        cur = max(cur, hi)
    return out + range_to_blocks(cur, root[0] + block_size(root[1]))


@dataclass(frozen=True)
class Allocation:
    site_blocks: dict[str, Block]
    segments: dict[str, dict[Any, Block]]  # site id -> segment key -> block
    infra_block: Block | None
    infra: dict[str, Block]
    free: list[Block]


def allocate(
    root: Block,
    sites: dict[str, dict[Any, int]],
    infra: dict[str, int],
    reserved: Sequence[Block] = (),
) -> Allocation:
    """§7.3: one aligned block per site (+ one infra block), then segments inside each.

    ``sites``: site id → {segment key: prefix}; ``infra``: item name → prefix.
    """
    demand = {s: sum(block_size(p) for p in segs.values()) for s, segs in sites.items()}
    top: list[tuple[tuple[str, int], int]] = [((s, 0), prefix_for_size(d))
                                              for s, d in demand.items()]
    if infra:
        top.append((("infra", 1), prefix_for_size(sum(block_size(p) for p in infra.values()))))
    placed = place(root, top, reserved)
    blocks = {s: placed[(s, 0)] for s in sites}
    infra_block = placed.get(("infra", 1))
    segments = {s: place(blocks[s], list(segs.items())) for s, segs in sites.items()}
    inner = place(infra_block, list(infra.items())) if infra_block else {}
    return Allocation(blocks, segments, infra_block, inner,
                      free_blocks(root, [*placed.values(), *reserved]))


# --- §7.4 summarisation ----------------------------------------------------------------


def summarise(blocks: Sequence[Block]) -> Block:
    """Common prefix of the lowest network and the highest broadcast."""
    lo = min(n for n, _ in blocks)
    hi = max(broadcast(n, p) for n, p in blocks)
    p = 32 - (lo ^ hi).bit_length()
    return network(lo, p), p


def overlaps(a: Block, b: Block) -> bool:
    m = mask(min(a[1], b[1]))
    return (a[0] & m) == (b[0] & m)


def summary_is_exact(summary: Block, others: Sequence[Block]) -> bool:
    """The summary must not cover any block assigned elsewhere."""
    return not any(overlaps(summary, o) for o in others)


# --- plan stage ------------------------------------------------------------------------

P2P_PT_ROWS = ("routed_port_slash31_3560", "router_interface_slash31")


def choose_p2p_prefix(req: Requirements) -> tuple[int, dict[str, str]]:
    """/31 (RFC 3021) unless the pt dialect has a /31 row not accepted in the PT matrix."""
    results = {row: pt_result(row) for row in P2P_PT_ROWS}
    if req.target_dialect == "full":
        return 31, results
    return (31 if all(r == "accepted" for r in results.values()) else 30), results


def infra_items(req: Requirements) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Routed point-to-point subnets (name, a, b) and loopback owners (one router per site).

    Physical links come from the input. The Global profile also gets one GRE tunnel per city
    from the HQ hub and one HQ ↔ cloud-vgw tunnel (technical.md §8.3) so they share the block.
    """
    p2p = [(f"link:{lk.a}--{lk.b}", lk.a, lk.b) for lk in req.links]
    if req.profile_type == "global":
        hub = next((s.id for s in req.sites if s.kind == "hq"), req.sites[0].id)
        p2p += [(f"tunnel:{hub}--{s.id}", hub, s.id) for s in req.sites if s.id != hub]
        if req.cloud is not None:
            p2p.append((f"tunnel:{hub}--cloud-vgw", hub, "cloud-vgw"))
    return p2p, [s.id for s in req.sites]


def _row(kind: str, site: str | None, name: str, b: Block, *, vlan: int | None = None,
         requested: int, needed: int) -> Subnet:
    net, p = b
    u = usable(p)
    return Subnet(
        kind=kind, site=site, name=name, vlan=vlan, network=dotted(net), prefix=p,
        mask=dotted(mask(p)), wildcard=dotted(wildcard(p)),
        gateway=dotted(first_host(net, p)) if kind == "segment" else None,
        first_host=dotted(first_host(net, p)), last_host=dotted(last_host(net, p)),
        broadcast=dotted(broadcast(net, p)), usable=u, requested=requested, needed=needed,
        utilisation_pct=round(100 * requested / u, 2),
    )


def _pct(a: int, b: int) -> float:
    return round(100 * a / b, 2)


def run(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    rnet, rp, _ = parse_cidr(req.address_space.root)
    root = (rnet, rp)
    reserved = [parse_cidr(r)[:2] for r in req.address_space.reserved]
    p2p_p, pt_rows = choose_p2p_prefix(req)
    p2p, lo_sites = infra_items(req)

    seg_prefix = {(s.id, g.vlan): segment_prefix(g.hosts, g.growth_pct)
                  for s in req.sites for g in s.segments}
    sites = {s.id: {(g.name, g.vlan): seg_prefix[(s.id, g.vlan)] for g in s.segments}
             for s in req.sites}
    infra = {name: p2p_p for name, _, _ in p2p} | {f"loopback:{s}": 32 for s in lo_sites}
    alloc = allocate(root, sites, infra, reserved)

    rows: list[Subnet] = []
    for s in req.sites:
        for g in s.segments:
            b = alloc.segments[s.id][(g.name, g.vlan)]
            rows.append(_row("segment", s.id, g.name, b, vlan=g.vlan, requested=g.hosts,
                             needed=needed_addresses(g.hosts, g.growth_pct)))
    for name, _, _ in p2p:
        rows.append(_row("p2p", None, name, alloc.infra[name], requested=2, needed=2))
    for s_id in lo_sites:
        rows.append(_row("loopback", None, f"loopback:{s_id}", alloc.infra[f"loopback:{s_id}"],
                         requested=1, needed=1))

    assigned = [*alloc.site_blocks.values(), *([alloc.infra_block] if alloc.infra_block else [])]
    site_blocks: list[SiteBlock] = []
    for s in req.sites:
        seg_blocks = list(alloc.segments[s.id].values())
        summ = summarise(seg_blocks)
        site_blocks.append(SiteBlock(
            site=s.id, block=cidr(alloc.site_blocks[s.id]), summary=cidr(summ),
            demand=sum(block_size(p) for _, p in seg_blocks),
        ))
    org = summarise(assigned)

    root_size = block_size(rp)
    allocated = sum(block_size(p) for _, p in assigned)
    seg_rows = [r for r in rows if r.kind == "segment"]
    largest_free = min(alloc.free, key=lambda b: b[1]) if alloc.free else None
    metrics: dict[str, Any] = {
        "root_size": root_size,
        "allocated": allocated,
        "allocated_pct": _pct(allocated, root_size),
        "requested_hosts": sum(r.requested for r in seg_rows),
        "sizing_waste": sum(r.usable - r.needed for r in seg_rows),
        "growth_headroom": sum(r.needed - r.requested - 1 for r in seg_rows),
        "block_rounding_waste": allocated - sum(block_size(r.prefix) for r in rows),
        "free_addresses": sum(block_size(p) for _, p in alloc.free),
        "largest_free_block": cidr(largest_free) if largest_free else None,
    }
    addressing = AddressingPlan(
        root=req.address_space.root, p2p_prefix=p2p_p, site_blocks=site_blocks,
        infra_block=cidr(alloc.infra_block) if alloc.infra_block else "", org_summary=cidr(org),
        subnets=rows, loopbacks={s: cidr(alloc.infra[f"loopback:{s}"]) for s in lo_sites},
        free_blocks=[cidr(b) for b in alloc.free], metrics=metrics,
    )

    by_vlan = {(r.site, r.vlan): r for r in seg_rows}
    segments = [ps.model_copy(update={"subnet": by_vlan[(ps.site, ps.vlan)].cidr,
                                      "gateway": by_vlan[(ps.site, ps.vlan)].gateway})
                if (ps.site, ps.vlan) in by_vlan else ps for ps in plan.segments]
    p2p_rows = {r.name: r for r in rows if r.kind == "p2p"}
    links = [pl.model_copy(update={"subnet": p2p_rows[f"link:{lk.a}--{lk.b}"].cidr})
             if (pl.a, pl.b) == (lk.a, lk.b) else pl
             for pl, lk in zip(plan.links, req.links, strict=False)] + plan.links[len(req.links):]

    decisions = _decisions(plan, req, addressing, alloc, pt_rows, p2p, lo_sites)
    warnings = [f"{d.id}: {w}" for d in decisions for w in d.warnings]
    return plan.model_copy(update={
        "addressing": addressing, "segments": segments, "links": links,
        "decisions": [*plan.decisions, *decisions], "warnings": [*plan.warnings, *warnings],
    })


# --- decisions -------------------------------------------------------------------------


def _g(growth: float) -> str:
    return f"{1 + growth / 100:g}"


def _decisions(
    plan: NetworkPlan,
    req: Requirements,
    ap: AddressingPlan,
    alloc: Allocation,
    pt_rows: dict[str, str],
    p2p: list[tuple[str, str, str]],
    lo_sites: list[str],
) -> list[Decision]:
    std = load_data("standards.yaml")
    n0 = sum(d.id.startswith("L3-") for d in plan.decisions)
    out: list[Decision] = []

    def nid() -> str:
        return decision_id("L3", n0 + len(out) + 1)

    seg_rows = [r for r in ap.subnets if r.kind == "segment"]
    big = max(seg_rows, key=lambda r: (r.needed, r.name))
    over_24 = sum(1 for r in seg_rows if r.needed > 254)
    out.append(make_decision(
        id=nid(), domain="addressing", subject="Subnet sizing rule",
        choice="needed = ceil(hosts × (1 + growth)) + 1 gateway; prefix = 32 − ceil(log2(needed "
               "+ 2))",
        rule_id="ADDR.SIZE",
        inputs={"segments": len(seg_rows), "largest_segment": f"{big.site}/{big.name}",
                "largest_needed": big.needed},
        math=[
            "253 hosts: 253 + 1 gateway = 254, + 2 (network, broadcast) = 256 → /24",
            "254 hosts: 254 + 1 gateway = 255, + 2 = 257 > 256 → /23",
            f"largest: {big.site}/{big.name} needs {big.needed} → /{big.prefix} "
            f"({big.usable} usable)",
        ],
        standards=[std["rfc_950"], std["rfc_1878"]],
        rejected=[
            rejected("hosts + 2 with no gateway reserve",
                     "a /24 would be chosen for 254 hosts and the gateway would have no address"),
            rejected("fixed /24 per VLAN",
                     f"{len(seg_rows)} × 256 = {256 * len(seg_rows):,} addresses, and "
                     f"{over_24} segment(s) need more than 254"),
        ],
        counterfactual="A segment moves to the next shorter prefix as soon as needed + 2 "
                       "passes its block size.",
    ))

    p = ap.p2p_prefix
    n_p2p = len(p2p)
    pt_txt = ", ".join(f"{k}={v}" for k, v in pt_rows.items())
    if p == 31:
        choice, other = "/31 point-to-point links (RFC 3021)", "/30 point-to-point links"
        why_not = f"/30 spends 4 addresses per link ({4 * n_p2p} vs {2 * n_p2p}) for 2 hosts"
        cf = "Would use /30 if the pt dialect's /31 rows in the PT matrix were not accepted."
    else:
        choice, other = "/30 point-to-point links", "/31 point-to-point links (RFC 3021)"
        why_not = f"Packet Tracer support is not confirmed ({pt_txt})"
        cf = ("Would use /31 once both /31 rows of the PT capability matrix are accepted, or "
              "with the full dialect.")
    out.append(make_decision(
        id=nid(), domain="addressing", subject="Point-to-point link prefix", choice=choice,
        rule_id="ADDR.P2P",
        inputs={"target_dialect": req.target_dialect, "p2p_links": n_p2p, "pt_matrix": pt_txt},
        math=["/31: 2 addresses, both usable as link ends (no network or broadcast)",
              "/30: 4 addresses, 2 usable",
              f"{n_p2p} links × {block_size(p)} = {n_p2p * block_size(p)} addresses"],
        standards=[std["rfc_3021"], std["rfc_950"]],
        rejected=[rejected(other, why_not)],
        counterfactual=cf,
    ))

    blocks_by_site = {b.site: b for b in ap.site_blocks}
    other_blocks = {s: [b for t, b in alloc.site_blocks.items() if t != s]
                    for s in alloc.site_blocks}
    for s in req.sites:
        sb = blocks_by_site[s.id]
        sbp = alloc.site_blocks[s.id][1]
        rows = [r for r in seg_rows if r.site == s.id]
        math = [
            f"{r.name}: ceil({r.requested} × {_g(g.growth_pct)}) + 1 = {r.needed}, + 2 = "
            f"{r.needed + 2} ≤ {block_size(r.prefix)} → {r.cidr} ({r.usable} usable, "
            f"{r.utilisation_pct:g}% used)"
            for r, g in zip(rows, s.segments, strict=True)
        ]
        exact = summary_is_exact(alloc.site_blocks[s.id],
                                 [*other_blocks[s.id],
                                  *([alloc.infra_block] if alloc.infra_block else [])])
        math += [f"site demand = {sb.demand} → /{sbp} ({block_size(sbp)} addresses)",
                 f"summary of the site's subnets = {sb.summary} "
                 f"({'equals the block, covers no other site' if exact else 'NOT exact'})"]
        out.append(make_decision(
            id=nid(), domain="addressing", subject=f"Site {s.id} address block",
            choice=f"{sb.block}, advertised as one summary route", rule_id="ADDR.SITE",
            inputs={"segments": len(rows), "demand_addresses": sb.demand},
            math=math, standards=[std["rfc_4632"], std["rfc_1878"]],
            rejected=[rejected("segments allocated straight from the root",
                               f"the {len(rows)} subnets could interleave with other sites, so "
                               "no single summary would cover exactly this site")],
            counterfactual=f"Would grow to /{sbp - 1} if the site's demand passed "
                           f"{block_size(sbp)} addresses.",
            warnings=[] if exact else [f"summary {sb.summary} overlaps another allocation"],
        ))

    out.append(make_decision(
        id=nid(), domain="addressing", subject="Infrastructure block (links and loopbacks)",
        choice=f"{ap.infra_block}: {n_p2p} × /{p} links + {len(lo_sites)} × /32 loopbacks",
        rule_id="ADDR.INFRA",
        inputs={"p2p_links": n_p2p, "loopbacks": len(lo_sites)},
        math=[f"{n_p2p} × {block_size(p)} + {len(lo_sites)} × 1 = "
              f"{n_p2p * block_size(p) + len(lo_sites)} → {ap.infra_block}",
              "loopback /32 = router-ID for OSPF/BGP"],
        standards=[std["rfc_3021"], std["rfc_4632"]],
        rejected=[rejected("link subnets taken from a site block",
                           "a link joins two sites, so it belongs inside neither site's summary")],
    ))

    m = ap.metrics
    out.append(make_decision(
        id=nid(), domain="addressing", subject=f"Address plan in {ap.root}",
        choice=f"{m['allocated']:,} of {m['root_size']:,} addresses allocated "
               f"({m['allocated_pct']:g}%), org summary {ap.org_summary}",
        rule_id="ADDR.EFF",
        inputs={"root": ap.root, "reserved": list(req.address_space.reserved),
                "requested_hosts": m["requested_hosts"]},
        math=[f"waste by sizing (rounding to a power of two) = {m['sizing_waste']:,} addresses",
              f"growth headroom = {m['growth_headroom']:,} addresses",
              f"site/infra block rounding = {m['block_rounding_waste']:,} addresses",
              f"free = {m['free_addresses']:,}; largest free block {m['largest_free_block']}"],
        standards=[std["rfc_4632"], std["rfc_1918"]],
        rejected=[rejected("allocation in input order",
                           "unsorted power-of-two blocks leave alignment gaps; descending size "
                           "packs them with none")],
    ))
    return out

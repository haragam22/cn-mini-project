"""P3: bitwise VLSM allocator (technical.md §7, test catalogue §14.2). ``ipaddress`` = oracle."""

import ipaddress

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from netarch.cli import app
from netarch.engines import design, ptcaps, vlsm
from netarch.errors import AddressSpaceExhaustedError, InputValidationError
from netarch.models.requirements import load_preset, load_requirements, parse_cidr


def _net(text):
    return ipaddress.ip_network(text)


def _ip(x):
    return str(ipaddress.ip_address(x))


# --- §7.1 primitives -------------------------------------------------------------------


@pytest.mark.parametrize("p", range(33))
def test_wildcard_and_mask_every_prefix_match_ipaddress(p):
    n = _net(f"0.0.0.0/{p}")
    assert vlsm.dotted(vlsm.wildcard(p)) == str(n.hostmask)
    assert vlsm.dotted(vlsm.mask(p)) == str(n.netmask)
    assert vlsm.block_size(p) == n.num_addresses


@pytest.mark.parametrize(
    ("p", "wc"),
    [(0, "255.255.255.255"), (8, "0.255.255.255"), (24, "0.0.0.255"), (30, "0.0.0.3"),
     (31, "0.0.0.1"), (32, "0.0.0.0")],
)
def test_wildcard_named_edges(p, wc):
    assert vlsm.dotted(vlsm.wildcard(p)) == wc


@pytest.mark.parametrize("text", ["10.1.2.0/24", "10.1.2.4/30", "10.1.2.6/31", "10.1.2.7/32",
                                  "172.16.0.0/12", "0.0.0.0/0", "192.168.1.128/25"])
def test_host_range_matches_ipaddress(text):
    n = _net(text)
    net, p, _ = parse_cidr(text)
    hosts = list(n.hosts()) if n.num_addresses <= 256 else None
    assert vlsm.network(net + 1 if p < 32 else net, p) == int(n.network_address)
    assert vlsm.broadcast(net, p) == int(n.broadcast_address)
    assert vlsm.is_aligned(net, p)
    if hosts is not None:
        assert vlsm.usable(p) == len(hosts)
        assert vlsm.first_host(net, p) == int(hosts[0])
        assert vlsm.last_host(net, p) == int(hosts[-1])
    else:
        assert vlsm.usable(p) == n.num_addresses - 2


def test_misaligned_detected():
    assert not vlsm.is_aligned(parse_cidr("10.0.0.4/30")[0], 29)


@pytest.mark.parametrize(("n", "p"), [(1, 32), (2, 31), (3, 30), (4, 30), (5, 29), (256, 24),
                                      (257, 23), (1 << 32, 0), ((1 << 32) + 1, -1)])
def test_prefix_for_size(n, p):
    assert vlsm.prefix_for_size(n) == p


# --- §7.2 sizing -----------------------------------------------------------------------


def test_gateway_rule_253_fits_slash24_254_needs_slash23():
    assert vlsm.segment_prefix(253, 0) == 24
    assert vlsm.segment_prefix(254, 0) == 23


@pytest.mark.parametrize(("hosts", "g", "needed"),
                         [(100, 20, 121), (200, 20, 241), (220, 20, 265), (1, 0, 2),
                          (3, 33.33, 5), (10, 200, 31), (7, 10, 9)])
def test_needed_addresses_exact(hosts, g, needed):
    assert vlsm.needed_addresses(hosts, g) == needed


def test_growth_uses_exact_decimal_not_float():
    # 0.1 + 100 in float is not exact; 10 × 1.1 = 11 must not round up to 12
    assert vlsm.needed_addresses(10, 10.0) == 12  # 11 + gateway


# --- §7.3 allocation, exhaustion -------------------------------------------------------

ROOT24 = parse_cidr("10.0.0.0/24")[:2]


def test_exact_fit_fills_root():
    a = vlsm.allocate(ROOT24, {"s": {"A": vlsm.segment_prefix(253, 0)}}, {})
    assert a.site_blocks["s"] == ROOT24
    assert a.free == []


def test_one_address_over_raises_with_correct_shortfall():
    with pytest.raises(AddressSpaceExhaustedError) as ei:
        vlsm.allocate(ROOT24, {"s": {"A": vlsm.segment_prefix(254, 0)}}, {})
    e = ei.value
    assert e.value == {"requested": 512, "available": 256, "shortfall": 256,
                       "smallest_root_prefix": 23}
    assert e.rule_id == "ADDR.E1"
    assert e.field == "address_space.root"


def test_exhaustion_message_matches_spec_example():
    root = parse_cidr("10.0.0.0/16")[:2]
    with pytest.raises(AddressSpaceExhaustedError) as ei:  # 65,536 + 4,096 + 512 = 70,144
        vlsm.place(root, [("a", 16), ("b", 20), ("c", 23)])
    assert str(ei.value) == ("Requested 70,144 addresses (after rounding) but 10.0.0.0/16 holds "
                             "65,536; short by 4,608. Smallest root that fits: /15.")


def test_slash30_root_one_host_fits_two_hosts_do_not():
    root = parse_cidr("10.0.0.0/30")[:2]
    a = vlsm.allocate(root, {"s": {"A": vlsm.segment_prefix(1, 0)}}, {})
    assert a.segments["s"]["A"] == root
    with pytest.raises(AddressSpaceExhaustedError) as ei:
        vlsm.allocate(root, {"s": {"A": vlsm.segment_prefix(2, 0)}}, {})
    assert ei.value.value["shortfall"] == 4
    assert ei.value.value["smallest_root_prefix"] == 29


def _raw(**over):
    raw = load_preset("campus").model_dump()
    raw.update(over)
    return raw


def test_slash32_root_rejected_at_input():
    with pytest.raises(InputValidationError):
        load_requirements(_raw(address_space={"root": "10.0.0.0/32", "reserved": []}))


def test_huge_host_count_says_no_ipv4_root_fits():
    with pytest.raises(AddressSpaceExhaustedError) as ei:
        vlsm.allocate(ROOT24, {"s": {"A": vlsm.segment_prefix(10**10, 0)}}, {})
    assert "No IPv4 root is that large" in str(ei.value)


def test_many_small_subnets_unsorted_input_allocates_like_sorted():
    reqs = [(f"n{i:02d}", p) for i, p in enumerate([30, 26, 28, 24, 30, 25, 27, 29, 26, 30])]
    a = vlsm.place(ROOT24[:1] + (22,), reqs)
    b = vlsm.place(ROOT24[:1] + (22,), sorted(reqs, key=lambda kp: (kp[1], kp[0])))
    assert a == b
    total = sum(vlsm.block_size(p) for _, p in reqs)
    used_end = max(n + vlsm.block_size(p) for n, p in a.values())
    assert used_end - ROOT24[0] == total  # no gaps: fragment-free


def test_reserved_range_is_skipped():
    root = parse_cidr("10.0.0.0/24")[:2]
    res = [parse_cidr("10.0.0.0/25")[:2]]
    out = vlsm.place(root, [("a", 26), ("b", 26)], res)
    assert [vlsm.cidr(b) for b in out.values()] == ["10.0.0.128/26", "10.0.0.192/26"]
    with pytest.raises(AddressSpaceExhaustedError) as ei:
        vlsm.place(root, [("a", 25), ("b", 26)], res)
    assert "after reserved ranges" in str(ei.value)
    assert ei.value.value["shortfall"] == 64


def test_reserved_fragmentation_reported_without_negative_shortfall():
    root = parse_cidr("10.0.0.0/24")[:2]
    res = [parse_cidr(t)[:2] for t in ("10.0.0.64/26", "10.0.0.128/26")]  # 128 free, no /25
    with pytest.raises(AddressSpaceExhaustedError) as ei:
        vlsm.place(root, [("a", 25)], res)
    assert ei.value.value["shortfall"] == 0
    assert "no aligned gap" in str(ei.value)


def test_reserved_outside_root_and_covering_root():
    root = parse_cidr("10.0.0.0/24")[:2]
    assert vlsm.place(root, [("a", 24)], [parse_cidr("10.9.0.0/16")[:2]]) == {"a": root}
    with pytest.raises(AddressSpaceExhaustedError):
        vlsm.place(root, [("a", 30)], [parse_cidr("10.0.0.0/8")[:2]])


@pytest.mark.parametrize(("lo", "hi"), [("10.0.0.0", "10.0.0.255"), ("10.0.0.3", "10.0.1.17"),
                                        ("0.0.0.0", "255.255.255.255"), ("10.0.0.5", "10.0.0.5")])
def test_range_to_blocks_matches_ipaddress(lo, hi):
    a, b = int(ipaddress.ip_address(lo)), int(ipaddress.ip_address(hi))
    want = [str(n) for n in ipaddress.summarize_address_range(ipaddress.ip_address(lo),
                                                              ipaddress.ip_address(hi))]
    assert [vlsm.cidr(x) for x in vlsm.range_to_blocks(a, b + 1)] == want


def test_free_blocks_cover_the_rest_of_root():
    root = parse_cidr("10.0.0.0/24")[:2]
    taken = [parse_cidr("10.0.0.0/26")[:2], parse_cidr("10.0.0.128/27")[:2]]
    free = [vlsm.cidr(b) for b in vlsm.free_blocks(root, taken)]
    assert free == ["10.0.0.64/26", "10.0.0.160/27", "10.0.0.192/26"]


# --- §7.4 summarisation ----------------------------------------------------------------


def test_summarise_and_exactness():
    blocks = [parse_cidr(t)[:2] for t in ("10.0.8.0/23", "10.0.10.0/24", "10.0.11.0/26")]
    s = vlsm.summarise(blocks)
    assert vlsm.cidr(s) == "10.0.8.0/22"
    assert vlsm.summary_is_exact(s, [parse_cidr("10.0.12.0/22")[:2]])
    assert not vlsm.summary_is_exact(s, [parse_cidr("10.0.11.128/25")[:2]])


# --- property suite vs ipaddress oracle -----------------------------------------------

segments = st.lists(st.tuples(st.integers(1, 1500), st.integers(0, 200)), min_size=1, max_size=5)


@settings(max_examples=1800, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    root_p=st.integers(8, 21),
    root_seed=st.integers(0, (1 << 32) - 1),
    site_segs=st.lists(segments, min_size=1, max_size=6),
    n_p2p=st.integers(0, 12),
    p2p_p=st.sampled_from([30, 31]),
)
def test_allocation_properties_vs_ipaddress(root_p, root_seed, site_segs, n_p2p, p2p_p):
    # 1,800 examples: ~72 % allocate (≥ 1,000 for the P3 gate), the rest check exhaustion.
    root = (vlsm.network(root_seed, root_p), root_p)
    root_net = _net(vlsm.cidr(root))
    sites = {f"s{i}": {(f"g{j}", j): vlsm.segment_prefix(h, g) for j, (h, g) in enumerate(segs)}
             for i, segs in enumerate(site_segs)}
    need = {(f"s{i}", (f"g{j}", j)): vlsm.needed_addresses(h, g)
            for i, segs in enumerate(site_segs) for j, (h, g) in enumerate(segs)}
    infra = {f"p{k}": p2p_p for k in range(n_p2p)} | {f"lo{s}": 32 for s in sites}
    requested = sum(vlsm.block_size(vlsm.prefix_for_size(sum(vlsm.block_size(p)
                                                             for p in segs.values())))
                    for segs in sites.values())
    requested += vlsm.block_size(vlsm.prefix_for_size(sum(vlsm.block_size(p)
                                                          for p in infra.values())))
    try:
        a = vlsm.allocate(root, sites, infra)
    except AddressSpaceExhaustedError as e:
        assert requested > root_net.num_addresses
        assert e.value["shortfall"] == requested - root_net.num_addresses
        event("exhausted")
        return
    event("allocated")
    assert requested <= root_net.num_addresses

    top = {**{s: _net(vlsm.cidr(b)) for s, b in a.site_blocks.items()},
           "infra": _net(vlsm.cidr(a.infra_block))}
    leaves = [(s, k, _net(vlsm.cidr(b))) for s, segs in a.segments.items() for k, b in segs.items()]
    leaves += [("infra", k, _net(vlsm.cidr(b))) for k, b in a.infra.items()]
    nets = [n for *_, n in leaves]
    for i, x in enumerate(nets):  # no overlap, all aligned (strict parse above), inside root
        assert x.subnet_of(root_net)
        for y in nets[i + 1:]:
            assert not x.overlaps(y)
    tops = list(top.values())
    for i, x in enumerate(tops):
        for y in tops[i + 1:]:
            assert not x.overlaps(y)
    for s, k, n in leaves:
        assert n.subnet_of(top[s])
        if s != "infra":
            assert n.num_addresses - 2 >= need[(s, k)]
    for s, block in top.items():
        if s == "infra":
            continue
        summ = _net(vlsm.cidr(vlsm.summarise(list(a.segments[s].values()))))
        assert summ == block
        assert not any(summ.overlaps(o) for t, o in top.items() if t != s)
    free = [_net(vlsm.cidr(b)) for b in a.free]
    assert sum(n.num_addresses for n in free) + sum(n.num_addresses for n in tops) == \
        root_net.num_addresses


# --- plan stage on the presets ---------------------------------------------------------


@pytest.fixture(scope="module", params=["campus", "metro", "global"])
def preset_plan(request):
    return design(load_preset(request.param))


def test_site_summary_equals_block_and_is_exact(preset_plan):
    ap = preset_plan.addressing
    blocks = {b.site: _net(b.block) for b in ap.site_blocks}
    infra = _net(ap.infra_block)
    for b in ap.site_blocks:
        assert b.summary == b.block
        summ = _net(b.summary)
        for r in ap.subnets:
            n = _net(r.cidr)
            if r.site == b.site:
                assert n.subnet_of(summ)
            else:
                assert not n.overlaps(summ)
        assert not any(summ.overlaps(o) for s, o in blocks.items() if s != b.site)
        assert not summ.overlaps(infra)


def test_rows_match_ipaddress_oracle(preset_plan):
    for r in preset_plan.addressing.subnets:
        n = _net(r.cidr)
        assert r.mask == str(n.netmask) and r.wildcard == str(n.hostmask)
        assert r.broadcast == str(n.broadcast_address)
        if r.kind == "segment":
            assert r.gateway == _ip(int(n.network_address) + 1)
            assert r.usable - 1 >= r.needed - 1 >= r.requested  # gateway + hosts fit
        if r.kind == "loopback":
            assert n.prefixlen == 32


def test_reserved_and_vpc_never_allocated(preset_plan):
    req = preset_plan.requirements
    others = [_net(x) for x in req.address_space.reserved]
    if req.cloud:
        others.append(_net(req.cloud.vpc_cidr))
    for r in preset_plan.addressing.subnets:
        assert not any(_net(r.cidr).overlaps(o) for o in others)


def test_plan_segments_and_links_get_subnets(preset_plan):
    assert all(s.subnet and s.gateway for s in preset_plan.segments)
    assert all(lk.subnet for lk in preset_plan.links)
    rows = {r.name for r in preset_plan.addressing.subnets if r.kind == "p2p"}
    assert {f"link:{lk.a}--{lk.b}" for lk in preset_plan.links} <= rows


def test_loopbacks_one_per_site_unique(preset_plan):
    lo = preset_plan.addressing.loopbacks
    assert set(lo) == {s.id for s in preset_plan.sites}
    assert len(set(lo.values())) == len(lo)


def test_addressing_decisions_complete(preset_plan):
    ds = [d for d in preset_plan.decisions if d.domain == "addressing"]
    assert len(ds) == 4 + len(preset_plan.sites)
    for d in ds:
        assert d.id.startswith("L3-") and d.rationale and d.standards and d.rejected
    sites = [d for d in ds if d.rule_id == "ADDR.SITE"]
    for d, b in zip(sites, preset_plan.addressing.site_blocks, strict=True):
        assert b.block in d.choice and str(b.demand) in d.rationale
        assert not d.warnings


def test_metrics_add_up(preset_plan):
    ap = preset_plan.addressing
    m = ap.metrics
    assert m["allocated"] + m["free_addresses"] + sum(
        _net(r).num_addresses for r in preset_plan.requirements.address_space.reserved
    ) == m["root_size"]
    assert m["largest_free_block"] in ap.free_blocks


def test_global_has_tunnel_and_cloud_p2p():
    plan = design(load_preset("global"))
    names = {r.name for r in plan.addressing.subnets if r.kind == "p2p"}
    assert names == {"tunnel:delhi--mumbai", "tunnel:delhi--bangalore",
                     "tunnel:delhi--singapore", "tunnel:delhi--cloud-vgw"}


def test_campus_numbers():
    ap = design(load_preset("campus")).addressing
    blocks = {b.site: b.block for b in ap.site_blocks}
    assert blocks == {"bldg-c": "10.0.0.0/21", "bldg-a": "10.0.8.0/22", "bldg-b": "10.0.12.0/22"}
    assert ap.infra_block == "10.0.16.0/28" and ap.p2p_prefix == 30


def test_deterministic():
    a = design(load_preset("metro")).model_dump_json()
    assert a == design(load_preset("metro")).model_dump_json()


# --- /31 vs /30 from the PT matrix -----------------------------------------------------


def test_full_dialect_uses_slash31():
    req = load_requirements(_raw(target_dialect="full"))
    assert vlsm.choose_p2p_prefix(req)[0] == 31
    ap = design(req).addressing
    assert all(r.prefix == 31 for r in ap.subnets if r.kind == "p2p")
    d = next(d for d in design(req).decisions if d.rule_id == "ADDR.P2P")
    assert d.choice.startswith("/31") and d.rejected[0].option.startswith("/30")


def test_pt_untested_falls_back_to_slash30():
    assert vlsm.choose_p2p_prefix(load_preset("campus"))[0] == 30


def test_pt_accepted_rows_switch_to_slash31(monkeypatch):
    monkeypatch.setattr(vlsm, "pt_result", lambda row: "accepted")
    assert vlsm.choose_p2p_prefix(load_preset("campus"))[0] == 31
    monkeypatch.setattr(vlsm, "pt_result",
                        lambda row: "accepted" if row == "router_interface_slash31" else "rejected")
    assert vlsm.choose_p2p_prefix(load_preset("campus"))[0] == 30


def test_ptcaps_lookup():
    assert ptcaps.pt_result("rapid_pvst") in {"untested", "accepted", "rejected", "alternative"}
    assert ptcaps.pt_accepts() is True
    assert ptcaps.pt_accepts("router_interface_slash31") is (
        ptcaps.pt_result("router_interface_slash31") == "accepted")


def test_pt_accepts_needs_every_row(monkeypatch):
    rows = {"a": "accepted", "b": "rejected", "c": "accepted"}
    monkeypatch.setattr(ptcaps, "pt_result", rows.__getitem__)
    assert ptcaps.pt_accepts("a", "c")
    assert not ptcaps.pt_accepts("a", "b")
    with pytest.raises(KeyError):
        ptcaps.pt_result("no_such_row")


# --- end to end ------------------------------------------------------------------------


def test_root_too_small_raises_from_design():
    req = load_requirements(_raw(address_space={"root": "10.0.0.0/22", "reserved": []}))
    with pytest.raises(AddressSpaceExhaustedError) as ei:
        design(req)
    assert "Requested 4,112" in str(ei.value)  # 2048 + 1024 + 1024 + infra 16
    assert "Smallest root that fits: /19." in str(ei.value)


def test_cli_explain_addressing_and_exhaustion(tmp_path):
    r = CliRunner().invoke(app, ["explain", "--preset", "campus", "--domain", "addressing"])
    assert r.exit_code == 0 and "ADDR.SITE" in r.stdout and "10.0.8.0/22" in r.stdout
    import json

    f = tmp_path / "small.json"
    f.write_text(json.dumps(_raw(address_space={"root": "10.0.0.0/22", "reserved": []})))
    r = CliRunner().invoke(app, ["explain", "--input", str(f)])
    assert r.exit_code == 3 and "ADDR.E1" in r.stderr

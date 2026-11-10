"""P2: L2 switching (technical.md §6.2–6.3): VLANs, trunks, native 999, RSTP, capacity."""

import pytest

from netarch.engines import l2_switching as l2
from netarch.errors import CapacityError
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import load_preset


def _plan(name, **kw):
    return l2.run(NetworkPlan(requirements=load_preset(name)), **kw)


def _site(plan, site, rule):
    return next(d for d in plan.decisions if d.rule_id == rule and site in d.subject)


# --- capacity math -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wired", "aps", "n"),
    [(0, 0, 0), (1, 0, 1), (24, 0, 1), (25, 0, 2), (240, 8, 11), (320, 10, 14)],
)
def test_access_switches_needed(wired, aps, n):
    assert l2.access_switches_needed(wired, aps, ports_per_switch=26, uplinks_per_switch=2) == n


def test_check_access_ports_passes_at_exact_fit():
    # 24 endpoints + 2 uplinks = 26 ports on one 26-port switch
    l2.check_access_ports(24, 0, 1, ports_per_switch=26, uplinks_per_switch=2, field="f")


def test_check_access_ports_raises_with_switch_count_needed():
    with pytest.raises(CapacityError) as ei:
        l2.check_access_ports(240, 8, 10, ports_per_switch=26, uplinks_per_switch=2,
                              field="sites[0]")
    e = ei.value
    assert e.rule_id == "L2.CAP.PORTS" and e.field == "sites[0]"
    assert "11" in e.message and "268" in e.message and "260" in e.message


def test_poe_demand_and_check():
    assert l2.poe_demand_w(8, per_ap_w=30) == 240
    l2.check_poe(8, 240, per_ap_w=30, field="f")  # exact fit passes
    with pytest.raises(CapacityError) as ei:
        l2.check_poe(9, 240, per_ap_w=30, field="sites[1].access_points")
    assert ei.value.rule_id == "L2.CAP.POE"
    assert "270 W" in ei.value.message and "240 W" in ei.value.message


def test_ap_density_warning():
    assert l2.ap_density_warning(400, 10, max_per_ap=40) is None  # exactly 40
    w = l2.ap_density_warning(401, 10, max_per_ap=40)
    assert w and "40.1" in w and "40" in w
    assert "no access points" in l2.ap_density_warning(50, 0, max_per_ap=40)
    assert l2.ap_density_warning(0, 0, max_per_ap=40) is None


def test_run_raises_capacity_error_when_poe_budget_too_small():
    with pytest.raises(CapacityError) as ei:
        _plan("campus", poe_budget_w=200)
    assert ei.value.field == "sites[0].access_points"


def test_run_with_enough_poe_budget_has_no_poe_warning():
    cap = _site(_plan("campus", poe_budget_w=300), "bldg-c", "L2.CAP")
    assert not any("PoE" in w for w in cap.warnings)
    assert any("PoE 300 W ≤ 300 W budget" in m for m in cap.math)  # 10 APs × 30 W = 300 W


# --- decisions -----------------------------------------------------------------------


def test_campus_vlans_and_native():
    plan = _plan("campus")
    v = _site(plan, "bldg-a", "L2.VLAN")
    assert v.inputs["vlans"] == [10, 20, 40, 99]
    assert v.inputs["native_vlan"] == 999
    assert 1 not in v.inputs["vlans"]
    assert any(r.option.startswith("VLAN 1") for r in v.rejected)
    segs = [(s.site, s.name, s.vlan) for s in plan.segments]
    assert ("bldg-b", "LABS", 30) in segs and len(segs) == 12


def test_trunk_allowed_list_is_exact_and_native_999():
    t = _site(_plan("campus"), "bldg-b", "L2.TRUNK")
    assert t.inputs["allowed_vlans"] == [10, 20, 30, 99]
    assert "allowed vlan 10,20,30,99" in t.choice
    assert "native vlan 999" in t.choice
    assert "all" not in t.choice.split()
    assert any("allowed vlan all" in r.option for r in t.rejected)
    assert any("native vlan 1" in r.option for r in t.rejected)
    assert 999 not in t.inputs["allowed_vlans"]


def test_rstp_root_is_the_distribution_switch_for_every_site_vlan():
    r = _site(_plan("campus"), "bldg-c", "L2.RSTP")
    assert "rapid-pvst" in r.choice and "root primary" in r.choice
    assert "distribution" in r.choice
    assert r.inputs["vlans"] == [10, 20, 30, 99]
    assert any("802.1w" in s for s in r.standards)


def test_wired_endpoints_include_growth_with_ceil():
    # ceil(hosts × (1 + growth/100)), same rounding as §7.2 without the +1 gateway
    assert l2.wired_with_growth(200, 20) == 240  # 200 × 1.2 = 240 exactly (no float drift)
    assert l2.wired_with_growth(41, 20) == 50  # 41 × 1.2 = 49.2 → 50
    assert l2.wired_with_growth(10, 0) == 10
    assert l2.wired_with_growth(3, 33.33) == 4  # 3 × 1.3333 = 3.9999 → 4
    assert l2.wired_with_growth(100, 0.1) == 101  # 100.1 → 101 (decimal, not binary 0.1)


def test_campus_capacity_numbers():
    plan = _plan("campus")
    a = _site(plan, "bldg-a", "L2.CAP")
    # bldg-a wired: STAFF ceil(200 × 1.2) = 240, SERVERS ceil(40 × 1.2) = 48; WIFI, MGMT excluded
    wired_a = 240 + 48
    assert wired_a == 288
    assert a.inputs["wired_endpoints"] == wired_a and a.inputs["access_points"] == 8
    # n = ceil((288 + 8) / 24) = ceil(296 / 24) = ceil(12.33) = 13
    assert a.inputs["access_switches"] == 13
    assert any("STAFF ceil(200 × (1 + 20/100)) = 240" in m for m in a.math)
    assert any("SERVERS ceil(40 × (1 + 20/100)) = 48" in m for m in a.math)
    assert any("8 APs × 30 W = 240 W" in m for m in a.math)
    assert any("ceil(296 / (26 − 2)) = 13" in m for m in a.math)
    assert any(r.option.startswith("12 ") for r in a.rejected)
    c = _site(plan, "bldg-c", "L2.CAP")
    # bldg-c wired: STAFF ceil(220 × 1.2) = 264, LABS ceil(100 × 1.2) = 120 → 384
    # n = ceil((384 + 10) / 24) = ceil(394 / 24) = ceil(16.42) = 17
    assert c.inputs["wired_endpoints"] == 264 + 120
    assert c.inputs["access_switches"] == 17


def test_campus_poe_recommends_802_3at_switching_sized_from_aps():
    plan = _plan("campus")
    for site, aps in (("bldg-a", 8), ("bldg-c", 10)):
        cap = _site(plan, site, "L2.CAP")
        need = aps * 30  # APs × 30 W (802.3at Class 4 at the PSE)
        assert cap.inputs["poe_required_w"] == need
        assert "802.3at (PoE+)" in cap.choice
        assert f"PoE budget ≥ {need} W" in cap.choice
        assert f"{aps} APs × 30 W = {need} W" in cap.rationale
        assert "802.3at" in cap.rationale
        # lab mapping limitation (§6.4): 3560-24PS is 802.3af 15.4 W, 2960-24TT has no PoE
        assert "3560-24PS" in cap.rationale and "802.3af" in cap.rationale
        assert "15.4 W per port" in cap.rationale
        assert "2960-24TT has no PoE" in cap.rationale
        assert "logical config identical" in cap.rationale
        # the old "budget not in the catalogue" warning is gone
        assert not any("PoE" in w for w in cap.warnings)
        assert not any("catalogue" in w for w in cap.warnings)


def test_metro_sites_without_aps_have_no_poe_line():
    cap = _site(_plan("metro"), "remote-1", "L2.CAP")
    assert cap.inputs["access_points"] == 0
    assert not any("PoE" in w for w in cap.warnings)
    assert "PoE" not in cap.choice and "802.3af" not in cap.rationale
    assert "poe_required_w" not in cap.inputs


def test_ids_are_l2_and_sequential():
    plan = _plan("campus")
    ids = [d.id for d in plan.decisions]
    assert ids == [f"L2-{n:02d}" for n in range(1, 13)]


def test_run_is_pure():
    base = NetworkPlan(requirements=load_preset("campus"))
    l2.run(base)
    assert base.decisions == [] and base.segments == []

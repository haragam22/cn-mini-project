"""P2: topology tier TOP.R1–R3 with link-count math (technical.md §6.1)."""

import pytest

from netarch.engines import topology
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import Requirements, load_preset


@pytest.mark.parametrize(("n", "links"), [(1, 0), (2, 1), (3, 3), (4, 6), (5, 10), (8, 28)])
def test_full_mesh_link_count(n, links):
    assert topology.full_mesh_links(n) == links


@pytest.mark.parametrize(("n", "links"), [(1, 0), (3, 2), (4, 3), (8, 7)])
def test_hub_link_count(n, links):
    assert topology.hub_links(n) == links


def test_core_uplinks():
    assert topology.core_uplinks(8) == 8


@pytest.mark.parametrize(
    ("blocks", "endpoints", "rule"),
    [
        (1, 500, "TOP.R1"),
        (1, 501, "TOP.R2"),
        (2, 100, "TOP.R2"),
        (4, 5000, "TOP.R2"),
        (4, 5001, "TOP.R3"),
        (5, 100, "TOP.R3"),
    ],
)
def test_select_tier_boundaries(blocks, endpoints, rule):
    assert topology.select_tier(blocks, endpoints) == rule


def _plan(name):
    return topology.run(NetworkPlan(requirements=load_preset(name)))


def test_campus_is_r2_full_mesh_triangle():
    plan = _plan("campus")
    (d,) = [d for d in plan.decisions if d.domain == "topology"]
    assert d.id == "TOP-01" and d.rule_id == "TOP.R2"
    assert "full mesh" in d.choice and "3" in d.choice
    assert d.inputs["distribution_blocks"] == 3
    assert d.inputs["endpoints"] == 1580
    assert d.inputs["input_links"] == 3
    assert any("n(n−1)/2 = 3·2/2 = 3" in m for m in d.math)
    assert {r.option.split(" ")[0] for r in d.rejected} >= {"TOP.R1", "TOP.R3"}
    assert d.warnings == []
    assert d.standards


def test_metro_four_sites_hub_at_hq():
    d = next(d for d in _plan("metro").decisions if d.domain == "topology")
    assert d.rule_id == "TOP.R2" and "hub" in d.choice and "hq" in d.choice
    assert any("n − 1 = 3" in m for m in d.math)


def test_global_four_cities_hub_no_physical_links():
    d = next(d for d in _plan("global").decisions if d.domain == "topology")
    assert d.rule_id == "TOP.R2" and "delhi" in d.choice
    assert any("no physical inter-site links" in m for m in d.math)


def _req(n_sites, hosts, links=()):
    sites = [
        {"id": f"s{i}", "kind": "building",
         "segments": [{"name": "U", "vlan": 10, "hosts": hosts, "growth_pct": 0,
                       "role": "users"}]}
        for i in range(n_sites)
    ]
    return Requirements.model_validate({
        "profile_name": "t", "profile_type": "campus",
        "address_space": {"root": "10.0.0.0/8"}, "sites": sites,
        "links": list(links), "resiliency": "dual_uplink",
    })


def test_single_small_building_r1():
    d = topology.run(NetworkPlan(requirements=_req(1, 300))).decisions[0]
    assert d.rule_id == "TOP.R1"


def test_five_blocks_r3_states_mesh_vs_core_math():
    d = topology.run(NetworkPlan(requirements=_req(5, 100))).decisions[0]
    assert d.rule_id == "TOP.R3"
    assert any("5·4/2 = 10" in m for m in d.math)
    assert any("5 uplinks" in m for m in d.math)


def test_missing_mesh_link_warns():
    links = [{"a": "s0", "b": "s1", "distance_m": 200, "inter_building": True,
              "required_gbps": 10}]
    d = topology.run(NetworkPlan(requirements=_req(3, 100, links))).decisions[0]
    assert any("1 link" in w and "3" in w for w in d.warnings)


def test_run_is_pure():
    base = NetworkPlan(requirements=load_preset("campus"))
    topology.run(base)
    assert base.decisions == []


def test_single_large_building_is_r2_single_block():
    # §6.1 gap: 1 building with > 500 endpoints is not R1 and not R3 → R2, one block.
    d = topology.run(NetworkPlan(requirements=_req(1, 501))).decisions[0]
    assert d.rule_id == "TOP.R2" and "single distribution block" in d.choice

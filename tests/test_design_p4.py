"""P4: routing, VPN, QoS, ACL design + lab mapping (technical.md §8, §6.4, §9.1)."""

import ipaddress

import pytest

from netarch.configgen import interface_map
from netarch.engines import design, qos, routing, vpn
from netarch.errors import CapacityError
from netarch.models.requirements import load_preset, load_requirements


@pytest.fixture(scope="module", params=["campus", "metro", "global"])
def plan(request):
    return design(load_preset(request.param))


def _raw(name, **over):
    raw = load_preset(name).model_dump(mode="json")
    raw.update(over)
    return raw


# --- plan.json completeness (gate 1) ---------------------------------------------------


def test_every_device_has_model_and_every_ip_has_mask(plan):
    for d in plan.devices:
        assert d.model in {"2911", "3560-24PS", "2960-24TT"}
        for i in d.interfaces:
            if i.ip:
                assert i.prefix is not None and i.subnet
                assert ipaddress.ip_address(i.ip) in ipaddress.ip_network(i.subnet)


def test_every_link_has_media_optic_and_ports(plan):
    for lk in plan.links:
        assert lk.media and lk.optic and lk.subnet and len(lk.ports) == 2


def test_routing_per_l3_device(plan):
    for d in plan.devices:
        if d.role in ("router", "l3switch") and d.hostname != "cloud-vgw":
            assert d.ospf and d.ospf.router_id and d.ospf.reference_bandwidth == 10000
    rids = [d.ospf.router_id for d in plan.devices if d.ospf]
    assert len(rids) == len(set(rids))


def test_plan_json_roundtrip(plan):
    js = plan.model_dump_json()
    assert type(plan).model_validate_json(js) == plan


# --- routing decisions (gate 2) --------------------------------------------------------


def _rules(plan):
    return {d.rule_id for d in plan.decisions}


def test_campus_single_area():
    p = design(load_preset("campus"))
    assert "RT.R1" in _rules(p) and "RT.R2" not in _rules(p)
    assert all(n.area == 0 for d in p.devices if d.ospf for n in d.ospf.networks)


def test_metro_single_area_with_failover():
    p = design(load_preset("metro"))
    assert {"RT.R1", "RT.FAILOVER", "QOS.LAT"} <= _rules(p)
    r1 = p.device("rtr-remote-1")
    costs = {i.description.split()[-1]: i.ospf.cost for i in r1.interfaces
             if i.ospf and i.ospf.cost}
    assert costs == {"rtr-hq": 10, "rtr-colo": 100}
    assert all(i.ospf.hello == 1 and i.ospf.dead == 4 for i in r1.interfaces
               if i.ospf and i.ospf.cost)


def test_global_multi_area_ebgp_gre():
    p = design(load_preset("global"))
    assert {"RT.R2", "RT.R3", "RT.R4", "RT.AREA"} <= _rules(p)
    hub = p.device("rtr-delhi")
    assert hub.bgp.asn == 65001 and hub.bgp.neighbors[0].remote_as == 64512
    assert ("10.0.0.0", "255.255.192.0", "Null0") in hub.static_routes
    assert hub.ospf.redistribute_bgp == "BGP-TO-OSPF"
    assert hub.prefix_lists["VPC-ONLY"] == ["seq 5 permit 172.31.0.0/16"]
    for d in p.devices:
        if d.ospf and d.site != "delhi":
            assert len(d.ospf.area_ranges) == 1  # ABR summarises its site block
    assert len(p.vpn_tunnels) == 4


def test_routing_decisions_have_rationale_and_rejections(plan):
    for d in plan.decisions:
        if d.domain in ("routing", "vpn", "qos", "security"):
            assert d.rationale and d.standards and d.rejected, d.id


def test_multi_area_threshold():
    req = load_preset("campus")
    assert not routing.is_multi_area(req, 49)
    assert routing.is_multi_area(req, 50)
    areas = routing.site_areas(req, True)
    assert sorted(areas.values()) == [1, 2, 3]  # campus has no hq: every building is an area


# --- latency (gate 3) ------------------------------------------------------------------


def test_metro_latency_reproduces_spec_example():
    t = qos.latency_ms(35000)
    assert t["propagation"] == pytest.approx(0.175)
    assert t["serialisation"] == pytest.approx(0.024)
    assert t["processing"] == pytest.approx(0.10)
    assert round(t["total"], 2) == 0.30
    d = next(d for d in design(load_preset("metro")).decisions if d.rule_id == "QOS.LAT")
    assert "≈ 0.30 ms" in d.rationale and "= 4.701 ms" in d.rationale


def test_latency_target_unreachable_warns():
    raw = _raw("metro", latency_target_ms=0.1)
    d = next(d for d in design(load_requirements(raw)).decisions if d.rule_id == "QOS.LAT")
    assert any("exceeded" in w for w in d.warnings)


def test_no_latency_target_no_qos():
    p = design(load_preset("campus"))
    assert p.qos_policies == [] and "QOS.LAT" not in _rules(p)


def test_metro_llq_on_wan_and_marking_on_trading():
    p = design(load_preset("metro"))
    hq = p.device("rtr-hq")
    assert any(i.policy_out == "WAN-EDGE" for i in hq.interfaces)
    assert any(i.policy_in == "MARK-TRADING" and i.vlan == 50 for i in hq.interfaces)


# --- ports (gate 4) --------------------------------------------------------------------


def test_no_port_used_twice_and_every_port_exists(plan):
    from importlib.resources import files

    import yaml

    dev = yaml.safe_load((files("netarch") / "data" / "devices.yaml").read_text("utf-8"))
    valid = {"2911": set(dev["router"]["ports"])}
    for m, spec in dev["lab_ports"].items():
        valid[m] = set(spec["uplink"]) | {f"{spec['access_prefix']}{i}" for i in range(1, 25)}
    for d in plan.devices:
        phys = [i.name for i in d.interfaces if i.kind == "physical"]
        assert len(phys) == len(set(phys)), d.hostname
        assert set(phys) <= valid[d.model], (d.hostname, set(phys) - valid[d.model])
    used = [(c.a, c.a_port) for c in plan.cabling] + [(c.b, c.b_port) for c in plan.cabling]
    assert len(used) == len(set(used))


def test_port_exhaustion_raises_capacity_error():
    ports = interface_map._Ports()
    for _ in range(3):
        ports.take("r", "2911", "uplink")
    with pytest.raises(CapacityError):
        ports.take("r", "2911", "uplink")


def test_hostnames_are_ios_safe_and_unique():
    raw = _raw("campus")
    raw["sites"][1]["id"] = "bldg a!"
    raw["sites"][2]["id"] = "BLDG-A!"
    raw["links"] = [{**lk, "a": {"bldg-b": "bldg a!", "bldg-c": "BLDG-A!"}.get(lk["a"], lk["a"]),
                     "b": {"bldg-b": "bldg a!", "bldg-c": "BLDG-A!"}.get(lk["b"], lk["b"])}
                    for lk in raw["links"]]
    p = design(load_requirements(raw))
    names = [d.hostname for d in p.devices]
    assert len(names) == len(set(names))
    assert all(n.replace("-", "").isalnum() for n in names)


def test_lab_mapping_decision(plan):
    d = next(d for d in plan.decisions if d.rule_id == "LAB.MAP")
    assert str(len(plan.hosts)) in d.choice


# --- VPN / ACL -------------------------------------------------------------------------


def test_tunnels_mirror_and_crypto():
    p = design(load_preset("global"))
    for t in p.vpn_tunnels:
        a, b = p.device(t.a).interface(t.a_if), p.device(t.b).interface(t.b_if)
        assert a.tunnel_destination == t.b_public and b.tunnel_destination == t.a_public
        assert a.ip_mtu == 1400 and a.tcp_mss == 1360
    assert vpn.crypto_suite("full")["hash"] == "sha256"
    assert vpn.crypto_suite("pt")["hash"] == "sha"  # matrix row untested → fallback


def test_vpn_skipped_without_tunnels():
    p = design(load_preset("campus"))
    assert p.vpn_tunnels == [] and not any(d.crypto for d in p.devices)


def test_acls_end_with_explicit_deny_and_are_attached(plan):
    attached = {(d.hostname, n) for d in plan.devices for i in d.interfaces
                for n in (i.acl_in, i.acl_out) if n}
    attached |= {(d.hostname, d.vty_acl) for d in plan.devices if d.vty_acl}
    for a in plan.acl_policies:
        assert a.entries[-1].action == "deny"
        assert (a.device, a.name) in attached


def test_campus_wifi_policy():
    p = design(load_preset("campus"))
    a = next(a for a in p.acl_policies if a.name == "WIFI-IN-20" and a.device == "dist-bldg-a")
    texts = [f"{e.action} {e.text}" for e in a.entries]
    assert texts[0].startswith("deny ip 10.0.8.0 0.0.1.255 10.0.11.64")  # → MGMT
    assert "permit tcp 10.0.8.0 0.0.1.255 10.0.11.0 0.0.0.63 eq 443" in texts


def test_metro_trading_protect_outbound_at_colo():
    p = design(load_preset("metro"))
    colo = p.device("rtr-colo")
    assert any(i.acl_out == "TRADING-PROTECT" and i.vlan == 50 for i in colo.interfaces)


def test_global_iot_and_cloud_acl():
    p = design(load_preset("global"))
    names = {(a.device, a.name) for a in p.acl_policies}
    assert ("rtr-mumbai", "IOT-IN-60") in names and ("rtr-delhi", "CLOUD-OUT") in names


def test_cloud_ignored_outside_global_warns():
    raw = _raw("campus", cloud={"vpc_cidr": "172.31.0.0/16"})
    p = design(load_requirements(raw))
    assert any("cloud is set" in w for w in p.warnings)


def test_iot_without_hub_servers_warns():
    raw = _raw("global")
    for s in raw["sites"]:
        if s["id"] == "delhi":
            s["segments"] = [g for g in s["segments"] if g["role"] != "servers"]
    p = design(load_requirements(raw))
    assert any("IoT traffic is denied" in w for w in p.warnings)


def test_no_mgmt_segment_no_vty_acl():
    raw = _raw("campus")
    for s in raw["sites"]:
        s["segments"] = [g for g in s["segments"] if g["role"] != "management"]
    p = design(load_requirements(raw))
    assert all(d.vty_acl is None for d in p.devices)
    assert any("not source-filtered" in w for w in p.warnings)


def test_single_link_campus_and_single_uplink():
    raw = _raw("campus", resiliency="dual_homed")
    raw["sites"] = raw["sites"][:1]
    raw["links"] = []
    p = design(load_requirements(raw))
    acc = p.device("acc-bldg-a")
    assert sum(i.mode == "trunk" for i in acc.interfaces) == 1


def test_pure_and_deterministic():
    req = load_preset("global")
    assert design(req).model_dump_json() == design(req).model_dump_json()

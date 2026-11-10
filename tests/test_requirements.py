"""P1: input schema validation (technical.md §4.1) and the error hierarchy (§13).

Every invalid-input test asserts the specific error class AND the field path.
"""

import copy
import json

import pytest

from netarch.errors import (
    AddressOverlapError,
    InputValidationError,
    NetArchError,
    PhysicalDistanceViolationError,
    TopologyConstraintError,
)
from netarch.models.requirements import (
    PRESET_NAMES,
    Requirements,
    collect_errors,
    load_preset,
    load_requirements,
    load_requirements_file,
)

BASE = {
    "profile_name": "t",
    "profile_type": "campus",
    "address_space": {"root": "10.0.0.0/16", "reserved": ["10.0.255.0/24"]},
    "sites": [
        {
            "id": "bldg-a",
            "kind": "building",
            "segments": [
                {"name": "STAFF", "vlan": 10, "hosts": 300, "growth_pct": 20, "role": "users"},
                {"name": "MGMT", "vlan": 99, "hosts": 20, "growth_pct": 0, "role": "management"},
            ],
            "access_points": 4,
            "access_run_max_m": 85,
        },
        {
            "id": "bldg-b",
            "kind": "building",
            "segments": [
                {"name": "STAFF", "vlan": 10, "hosts": 100, "growth_pct": 20, "role": "users"},
            ],
        },
    ],
    "links": [
        {
            "a": "bldg-a",
            "b": "bldg-b",
            "distance_m": 180,
            "inter_building": True,
            "required_gbps": 10,
            "requested_media": None,
        }
    ],
    "resiliency": "dual_uplink",
    "latency_target_ms": None,
    "cloud": None,
    "target_dialect": "pt",
}

METRO = {
    "profile_name": "m",
    "profile_type": "metro",
    "address_space": {"root": "10.0.0.0/16", "reserved": []},
    "sites": [
        {"id": "hq", "kind": "hq",
         "segments": [{"name": "STAFF", "vlan": 10, "hosts": 50, "growth_pct": 0,
                       "role": "users"}]},
        {"id": "colo", "kind": "colo",
         "segments": [{"name": "TRADING", "vlan": 50, "hosts": 10, "growth_pct": 0,
                       "role": "trading"}]},
        {"id": "remote-1", "kind": "remote",
         "segments": [{"name": "STAFF", "vlan": 10, "hosts": 20, "growth_pct": 0,
                       "role": "users"}]},
    ],
    "links": [
        {"a": "hq", "b": "colo", "distance_m": 15000, "inter_building": True,
         "required_gbps": 10},
        {"a": "hq", "b": "remote-1", "distance_m": 22000, "inter_building": True,
         "required_gbps": 10},
        {"a": "colo", "b": "remote-1", "distance_m": 20000, "inter_building": True,
         "required_gbps": 10},
    ],
    "resiliency": "dual_homed",
    "latency_target_ms": 5,
    "cloud": None,
    "target_dialect": "pt",
}


def mutate(base=BASE, **_):
    return copy.deepcopy(base)


def only_error(data):
    errs = collect_errors(data)
    assert len(errs) == 1, [(type(e).__name__, e.field, e.message) for e in errs]
    return errs[0]


def assert_single(data, cls, field):
    err = only_error(data)
    assert type(err) is cls, (type(err).__name__, err.field, err.message)
    assert err.field == field
    assert err.message and err.rule_id and err.hint
    with pytest.raises(cls) as exc:
        load_requirements(data)
    assert exc.value.field == field
    return err


# --- valid inputs -------------------------------------------------------------------


def test_base_example_is_valid():
    assert collect_errors(BASE) == []
    req = load_requirements(BASE)
    assert isinstance(req, Requirements)
    assert req.sites[0].segments[0].vlan == 10


def test_metro_dual_homed_valid():
    assert collect_errors(METRO) == []


@pytest.mark.parametrize("name", PRESET_NAMES)
def test_presets_load_with_zero_errors(name):
    from importlib.resources import files

    raw = json.loads((files("netarch") / "presets" / f"{name}.json").read_text("utf-8"))
    assert collect_errors(raw) == []
    req = load_preset(name)
    assert req.profile_type == name


def test_preset_names_are_the_three_profiles():
    assert sorted(PRESET_NAMES) == ["campus", "global", "metro"]


def test_load_requirements_file(tmp_path):
    p = tmp_path / "in.json"
    p.write_text(json.dumps(BASE), encoding="utf-8")
    assert load_requirements_file(p).profile_name == "t"


def test_load_requirements_file_bad_json(tmp_path):
    p = tmp_path / "in.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(InputValidationError) as exc:
        load_requirements_file(p)
    assert exc.value.field == "<file>"


def test_copper_at_exactly_100m_passes():
    d = mutate()
    d["links"][0].update(distance_m=100, requested_media="copper")
    assert collect_errors(d) == []


def test_vlan_boundaries_2_and_4094_pass():
    d = mutate()
    d["sites"][0]["segments"][0]["vlan"] = 2
    d["sites"][0]["segments"][1]["vlan"] = 4094
    assert collect_errors(d) == []


def test_root_prefix_8_and_30_pass():
    for root in ("10.0.0.0/8", "10.0.0.0/30"):
        d = mutate()
        d["address_space"] = {"root": root, "reserved": []}
        assert collect_errors(d) == [], root


def test_distance_with_two_decimals_passes():
    d = mutate()
    d["links"][0]["distance_m"] = 100.01
    assert collect_errors(d) == []


# --- invalid inputs: one specific error class + field each ---------------------------


def test_bad_cidr_root():
    d = mutate()
    d["address_space"]["root"] = "10.0.0.256/16"
    assert_single(d, InputValidationError, "address_space.root")


def test_root_not_cidr_text():
    d = mutate()
    d["address_space"]["root"] = "campus"
    assert_single(d, InputValidationError, "address_space.root")


def test_root_host_bits_set():
    d = mutate()
    d["address_space"]["root"] = "10.0.0.1/16"
    err = assert_single(d, InputValidationError, "address_space.root")
    assert "host bits" in err.message


@pytest.mark.parametrize("root", ["10.0.0.0/7", "10.0.0.0/31", "10.0.0.0/32"])
def test_root_prefix_outside_8_30(root):
    d = mutate()
    d["address_space"] = {"root": root, "reserved": []}
    assert_single(d, InputValidationError, "address_space.root")


def test_vlan_1_rejected():
    d = mutate()
    d["sites"][0]["segments"][0]["vlan"] = 1
    err = assert_single(d, InputValidationError, "sites[0].segments[0].vlan")
    assert err.value == 1


def test_vlan_1003_reserved():
    d = mutate()
    d["sites"][0]["segments"][1]["vlan"] = 1003
    assert_single(d, InputValidationError, "sites[0].segments[1].vlan")


def test_vlan_999_reserved_native():
    d = mutate()
    d["sites"][0]["segments"][0]["vlan"] = 999
    err = assert_single(d, InputValidationError, "sites[0].segments[0].vlan")
    assert err.rule_id == "INPUT.vlan_native"
    assert err.value == 999


@pytest.mark.parametrize("vlan", [0, 1002, 1005, 4095])
def test_vlan_out_of_range_or_reserved(vlan):
    d = mutate()
    d["sites"][0]["segments"][0]["vlan"] = vlan
    assert_single(d, InputValidationError, "sites[0].segments[0].vlan")


def test_duplicate_vlan_within_site():
    d = mutate()
    d["sites"][0]["segments"][1]["vlan"] = 10
    assert_single(d, InputValidationError, "sites[0].segments[1].vlan")


def test_same_vlan_in_different_sites_is_fine():
    # BASE uses VLAN 10 in both buildings
    assert collect_errors(BASE) == []


def test_duplicate_site_id():
    d = mutate()
    d["sites"][1]["id"] = "bldg-a"
    d["links"] = []
    assert_single(d, InputValidationError, "sites[1].id")


def test_unknown_link_endpoint():
    d = mutate()
    d["links"][0]["b"] = "bldg-z"
    err = assert_single(d, InputValidationError, "links[0].b")
    assert err.value == "bldg-z"


def test_negative_distance():
    d = mutate()
    d["links"][0]["distance_m"] = -5
    assert_single(d, InputValidationError, "links[0].distance_m")


def test_zero_distance():
    d = mutate()
    d["links"][0]["distance_m"] = 0
    assert_single(d, InputValidationError, "links[0].distance_m")


def test_distance_over_120km():
    d = mutate()
    d["links"][0]["distance_m"] = 120_000.01
    assert_single(d, InputValidationError, "links[0].distance_m")


def test_distance_more_than_two_decimals():
    d = mutate()
    d["links"][0]["distance_m"] = 100.005
    assert_single(d, InputValidationError, "links[0].distance_m")


@pytest.mark.parametrize("dist", [100.01, 120])
def test_copper_over_100m(dist):
    d = mutate()
    d["links"][0].update(distance_m=dist, requested_media="copper")
    err = assert_single(d, PhysicalDistanceViolationError, "links[0].requested_media")
    assert err.rule_id == "MEDIA.E1"
    assert "IEEE 802.3an" in err.message
    assert "bldg-a ↔ bldg-b" in err.message


def test_physical_distance_message_template():
    err = PhysicalDistanceViolationError.for_link("bldg-a", "bldg-c", 120, field="links[1]")
    assert err.message == (
        "Copper requested for link bldg-a ↔ bldg-c at 120 m. Category 6a / 10GBASE-T is "
        "limited to a 100 m channel (IEEE 802.3an); beyond this, insertion loss and "
        "crosstalk exceed receiver tolerance. Use OM4 multimode fibre (10GBASE-SR, ≤ 400 m)."
    )


def test_hosts_zero():
    d = mutate()
    d["sites"][0]["segments"][0]["hosts"] = 0
    assert_single(d, InputValidationError, "sites[0].segments[0].hosts")


def test_hosts_not_integer():
    d = mutate()
    d["sites"][0]["segments"][0]["hosts"] = 2.5
    assert_single(d, InputValidationError, "sites[0].segments[0].hosts")


def test_growth_pct_over_200():
    d = mutate()
    d["sites"][0]["segments"][0]["growth_pct"] = 201
    assert_single(d, InputValidationError, "sites[0].segments[0].growth_pct")


def test_growth_pct_negative():
    d = mutate()
    d["sites"][0]["segments"][0]["growth_pct"] = -1
    assert_single(d, InputValidationError, "sites[0].segments[0].growth_pct")


def test_latency_target_zero():
    d = mutate()
    d["latency_target_ms"] = 0
    assert_single(d, InputValidationError, "latency_target_ms")


def test_vpc_overlaps_root():
    d = mutate()
    d["cloud"] = {"vpc_cidr": "10.0.128.0/17"}
    err = assert_single(d, AddressOverlapError, "cloud.vpc_cidr")
    assert "10.0.0.0/16" in err.message


def test_vpc_contains_root():
    d = mutate()
    d["cloud"] = {"vpc_cidr": "10.0.0.0/8"}
    assert_single(d, AddressOverlapError, "cloud.vpc_cidr")


def test_vpc_outside_rfc1918():
    d = mutate()
    d["cloud"] = {"vpc_cidr": "8.8.0.0/16"}
    assert_single(d, AddressOverlapError, "cloud.vpc_cidr")


def test_vpc_172_32_is_outside_rfc1918():
    # 172.16.0.0/12 ends at 172.31.255.255; an off-by-one here is a classic mistake
    d = mutate()
    d["cloud"] = {"vpc_cidr": "172.32.0.0/16"}
    assert_single(d, AddressOverlapError, "cloud.vpc_cidr")


def test_vpc_172_31_is_fine():
    d = mutate()
    d["cloud"] = {"vpc_cidr": "172.31.0.0/16"}
    assert collect_errors(d) == []


def test_vpc_host_bits_set():
    d = mutate()
    d["cloud"] = {"vpc_cidr": "172.31.0.1/16"}
    assert_single(d, InputValidationError, "cloud.vpc_cidr")


def test_reserved_outside_rfc1918():
    d = mutate()
    d["address_space"]["reserved"] = ["100.64.0.0/24"]
    assert_single(d, AddressOverlapError, "address_space.reserved[0]")


def test_reserved_ranges_overlap_each_other():
    d = mutate()
    d["address_space"]["reserved"] = ["10.0.255.0/24", "10.0.255.128/25"]
    assert_single(d, AddressOverlapError, "address_space.reserved[1]")


def test_reserved_bad_cidr():
    d = mutate()
    d["address_space"]["reserved"] = ["10.0.255.0/33"]
    assert_single(d, InputValidationError, "address_space.reserved[0]")


def test_vpc_overlaps_reserved_outside_root():
    d = mutate()
    d["address_space"]["reserved"] = ["192.168.10.0/24"]
    d["cloud"] = {"vpc_cidr": "192.168.0.0/16"}
    assert_single(d, AddressOverlapError, "cloud.vpc_cidr")


def test_dual_homed_remote_with_one_link():
    d = copy.deepcopy(METRO)
    d["links"] = d["links"][:2]  # remote-1 now only reaches hq
    err = assert_single(d, TopologyConstraintError, "sites[2]")
    assert err.value == "remote-1"


def test_dual_uplink_remote_with_one_link_is_fine():
    d = copy.deepcopy(METRO)
    d["links"] = d["links"][:2]
    d["resiliency"] = "dual_uplink"
    assert collect_errors(d) == []


def test_unknown_field_rejected():
    d = mutate()
    d["sites"][0]["acess_points"] = 4  # typo must not be silently dropped
    assert_single(d, InputValidationError, "sites[0].acess_points")


def test_missing_required_field():
    d = mutate()
    del d["address_space"]
    assert_single(d, InputValidationError, "address_space")


def test_unknown_profile_type():
    d = mutate()
    d["profile_type"] = "datacentre"
    assert_single(d, InputValidationError, "profile_type")


def test_unknown_requested_media():
    d = mutate()
    d["links"][0]["requested_media"] = "wifi"
    assert_single(d, InputValidationError, "links[0].requested_media")


def test_link_to_itself():
    d = mutate()
    d["links"][0]["b"] = "bldg-a"
    assert_single(d, InputValidationError, "links[0].b")


# --- aggregation: all failures at once --------------------------------------------


def test_three_separate_mistakes_reports_all_three():
    d = mutate()
    d["sites"][0]["segments"][0]["vlan"] = 1  # field-level
    d["links"][0]["b"] = "bldg-z"  # cross-field: unknown endpoint
    d["cloud"] = {"vpc_cidr": "10.0.0.0/24"}  # overlap
    errs = collect_errors(d)
    got = sorted((type(e).__name__, e.field) for e in errs)
    assert got == [
        ("AddressOverlapError", "cloud.vpc_cidr"),
        ("InputValidationError", "links[0].b"),
        ("InputValidationError", "sites[0].segments[0].vlan"),
    ]
    with pytest.raises(InputValidationError) as exc:
        load_requirements(d)
    assert len(exc.value.errors) == 3
    assert {e.field for e in exc.value.errors} == {
        "cloud.vpc_cidr",
        "links[0].b",
        "sites[0].segments[0].vlan",
    }


def test_mixed_typed_mistakes_reported_together():
    d = mutate()
    d["links"][0].update(distance_m=150, requested_media="copper")
    d["sites"][0]["segments"][0]["hosts"] = 0
    d["address_space"]["root"] = "10.0.0.1/16"
    errs = collect_errors(d)
    got = sorted((type(e).__name__, e.field) for e in errs)
    assert got == [
        ("InputValidationError", "address_space.root"),
        ("InputValidationError", "sites[0].segments[0].hosts"),
        ("PhysicalDistanceViolationError", "links[0].requested_media"),
    ]


def test_all_errors_are_netarch_errors_with_fields():
    d = mutate()
    d["sites"][0]["segments"][0]["vlan"] = 1003
    d["links"][0]["distance_m"] = -1
    for e in collect_errors(d):
        assert isinstance(e, NetArchError)
        assert e.field and e.rule_id and e.message and e.hint

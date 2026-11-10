"""P1: preset numbers (implementation.md P1 task 4); integer CIDR parsing vs ipaddress."""

import ipaddress

import pytest
from hypothesis import given
from hypothesis import strategies as st

from netarch.models.requirements import in_rfc1918, load_preset, overlaps, parse_cidr


def _dist(req, a, b):
    for lk in req.links:
        if {lk.a, lk.b} == {a, b}:
            return lk.distance_m
    raise AssertionError(f"no link {a}-{b}")


def test_campus_numbers():
    req = load_preset("campus")
    assert req.address_space.root == "10.0.0.0/16"
    assert [s.id for s in req.sites] == ["bldg-a", "bldg-b", "bldg-c"]
    assert _dist(req, "bldg-a", "bldg-b") == 180
    assert _dist(req, "bldg-b", "bldg-c") == 320
    assert _dist(req, "bldg-a", "bldg-c") == 390
    assert all(lk.inter_building for lk in req.links)
    total = sum(seg.hosts for s in req.sites for seg in s.segments)
    assert 1500 <= total <= 1700  # "~1,600 endpoints"
    names = {seg.name for s in req.sites for seg in s.segments}
    assert names == {"STAFF", "WIFI", "LABS", "SERVERS", "MGMT"}
    assert all(s.access_points > 0 for s in req.sites)


def test_metro_numbers():
    req = load_preset("metro")
    assert _dist(req, "hq", "remote-1") == 22_000
    assert _dist(req, "hq", "remote-2") == 35_000
    assert _dist(req, "hq", "colo") == 15_000
    assert req.resiliency == "dual_homed"
    assert req.latency_target_ms == 5
    users = sum(
        seg.hosts for s in req.sites if s.kind != "colo"
        for seg in s.segments if seg.role in ("users", "trading")
    )
    assert users == 450
    assert any(seg.name == "TRADING" for s in req.sites for seg in s.segments)


def test_global_numbers():
    req = load_preset("global")
    assert len(req.sites) == 4
    assert [s.id for s in req.sites] == ["delhi", "mumbai", "bangalore", "singapore"]
    assert [s.kind for s in req.sites].count("hq") == 1
    assert next(s for s in req.sites if s.kind == "hq").id == "delhi"
    assert req.cloud is not None and req.cloud.vpc_cidr == "172.31.0.0/16"
    assert sum(seg.hosts for s in req.sites for seg in s.segments if seg.role == "iot") == 2000
    for s in req.sites:
        assert {seg.name for seg in s.segments} == {"IOT", "USERS", "SERVERS", "MGMT"}


@given(st.integers(0, 2**32 - 1), st.integers(0, 32))
def test_parse_cidr_matches_ipaddress(addr, prefix):
    text = f"{ipaddress.IPv4Address(addr)}/{prefix}"
    got_addr, got_prefix, host_bits = parse_cidr(text)
    assert (got_addr, got_prefix) == (addr, prefix)
    try:
        ipaddress.IPv4Network(text, strict=True)
        strict_ok = True
    except ValueError:
        strict_ok = False
    assert host_bits is (not strict_ok)


@pytest.mark.parametrize(
    "text", ["10.0.0.256/8", "10.0.0/8", "10.0.0.0/33", "10.0.0.0", "010.0.0.0/8",
             "10.0.0.0/08", "a.b.c.d/8", "10.0.0.0/-1", " 10.0.0.0/8", "10.0.0.0//8"],
)
def test_parse_cidr_rejects_malformed(text):
    with pytest.raises(ValueError):
        parse_cidr(text)


def _net(n):
    return int(n.network_address), n.prefixlen


@given(st.integers(0, 2**32 - 1), st.integers(0, 32), st.integers(0, 2**32 - 1),
       st.integers(0, 32))
def test_overlaps_matches_ipaddress(a, pa, b, pb):
    na = ipaddress.IPv4Network((a, pa), strict=False)
    nb = ipaddress.IPv4Network((b, pb), strict=False)
    assert overlaps(_net(na), _net(nb)) is na.overlaps(nb)


@given(st.integers(0, 2**32 - 1), st.integers(0, 32))
def test_in_rfc1918_matches_ipaddress(a, p):
    n = ipaddress.IPv4Network((a, p), strict=False)
    private = [ipaddress.IPv4Network(x) for x in ("10.0.0.0/8", "172.16.0.0/12",
                                                    "192.168.0.0/16")]
    assert in_rfc1918(_net(n)) is any(n.subnet_of(r) for r in private)

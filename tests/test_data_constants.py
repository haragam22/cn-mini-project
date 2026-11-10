"""P0 gate: every optics/media constant carries a source citation (technical.md §5.3)."""

from pathlib import Path

import pytest
import yaml

DATA = Path(__file__).resolve().parents[1] / "netarch" / "data"


def load(name: str):
    return yaml.safe_load((DATA / name).read_text(encoding="utf-8"))


def constants(node, path=""):
    """Yield (path, mapping) for every constant, i.e. every mapping that has a `value` key."""
    if isinstance(node, dict):
        if "value" in node:
            yield path, node
            return
        for key, child in node.items():
            yield from constants(child, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, child in enumerate(node):
            yield from constants(child, f"{path}[{i}]")


def unsourced(node):
    return [
        p
        for p, c in constants(node)
        if not isinstance(c.get("source"), str) or not c["source"].strip()
    ]


def bare_numbers(node, path=""):
    """Numbers that sit outside a {value, source} constant (they would escape the source check)."""
    if isinstance(node, dict):
        if "value" in node:
            return []
        return [b for k, c in node.items() for b in bare_numbers(c, f"{path}.{k}" if path else k)]
    if isinstance(node, list):
        return [b for i, c in enumerate(node) for b in bare_numbers(c, f"{path}[{i}]")]
    is_number = isinstance(node, int | float) and not isinstance(node, bool)
    return [path] if is_number else []


def test_bare_numbers_detects_unwrapped_values():
    doc = {"a": {"value": 1, "source": "x"}, "b": 7, "c": [{"d": 2.5}], "e": True}
    assert bare_numbers(doc) == ["b", "c[0].d"]


CONSTANT_FILES = ["media.yaml", "optics.yaml", "devices.yaml", "topology.yaml", "design.yaml"]


@pytest.mark.parametrize("name", CONSTANT_FILES)
def test_no_number_escapes_the_source_rule(name):
    assert bare_numbers(load(name)) == []


def test_unsourced_detects_missing_and_blank_source():
    doc = {
        "a": {"value": 1, "source": "x"},
        "b": {"value": 2},
        "c": {"d": {"value": 3, "source": " "}},
    }
    assert unsourced(doc) == ["b", "c.d"]


@pytest.mark.parametrize("name", CONSTANT_FILES)
def test_every_constant_has_a_source(name):
    doc = load(name)
    found = list(constants(doc))
    assert found, f"{name} has no constants"
    assert unsourced(doc) == []


def _v(doc, dotted):
    node = doc
    for part in dotted.split("."):
        node = node[part]
    return node["value"]


def test_media_working_values_match_technical_md():
    media = load("media.yaml")
    assert _v(media, "attenuation.os2_1310nm") == 0.35
    assert _v(media, "attenuation.os2_1550nm") == 0.25
    assert _v(media, "attenuation.om4_850nm") == 3.0
    assert _v(media, "connector.loss_db") == 0.5
    assert _v(media, "connector.tia_max_db") == 0.75
    assert _v(media, "connector.per_link") == 2
    assert _v(media, "splice.loss_db") == 0.1
    assert _v(media, "splice.tia_max_db") == 0.3
    assert _v(media, "reel_length_km") == 4
    assert _v(media, "min_operating_margin_db") == 1.0


def test_optics_table_matches_technical_md():
    optics = load("optics.yaml")["optics"]
    expected = {
        # name: (reach_m, channel insertion loss dB, cost rank)
        "10GBASE-T": (100, None, 1),
        "10GBASE-SR": ({"OM3": 300, "OM4": 400}, None, 2),
        "10GBASE-LR": (10000, 6.2, 3),
        "10GBASE-ER": (40000, 11, 4),
        "10GBASE-ZR": (80000, 23, 5),
    }
    assert set(optics) == set(expected)
    for name, (reach, cil, rank) in expected.items():
        o = optics[name]
        assert o["reach_m"]["value"] == reach, name
        assert o["channel_insertion_loss_db"]["value"] == cil, name
        assert o["cost_rank"]["value"] == rank, name
    assert optics["10GBASE-ZR"]["ieee"] is False


def test_p2_copper_and_device_constants_match_technical_md():
    media = load("media.yaml")
    assert _v(media, "copper.channel_max_m") == 100
    assert _v(media, "copper.permanent_link_max_m") == 90
    assert _v(media, "copper.patch_cords_max_m") == 10
    assert _v(media, "copper.cat6_10g_max_m") == 55
    devices = load("devices.yaml")
    assert _v(devices, "access_switch.access_ports") == 24
    assert _v(devices, "access_switch.uplink_ports") == 2
    assert _v(devices, "poe.per_ap_w") == 30
    # lab PoE facts (docs/QUESTIONS.md P2): 3560-24PS 802.3af 15.4 W/port, 2960-24TT none
    assert _v(devices, "distribution_switch.poe_standard") == "802.3af"
    assert _v(devices, "distribution_switch.poe_per_port_w") == 15.4
    assert _v(devices, "access_switch.poe_per_port_w") == 0
    assert _v(devices, "wireless.max_clients_per_ap") == 40


def test_standards_cover_technical_md_15_refs_used_by_p2():
    std = load("standards.yaml")
    assert all(isinstance(v, str) and v.strip() for v in std.values())
    for ref in ("802.3an", "802.3ae", "802.3at", "802.1Q", "802.1w", "568.2-D", "568.3-D"):
        assert any(ref in v for v in std.values()), ref


def test_topology_thresholds_match_technical_md():
    t = load("topology.yaml")
    assert _v(t, "collapsed_single_block_max_endpoints") == 500
    assert _v(t, "two_tier_max_blocks") == 4
    assert _v(t, "full_mesh_max_blocks") == 3
    assert _v(t, "two_tier_max_endpoints") == 5000
    assert _v(t, "native_vlan") == 999

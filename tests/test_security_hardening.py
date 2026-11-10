"""Regression tests for the 2026-11-10 security-breaker findings (docs/security/p0-p7.md)."""

import asyncio
import csv
import io
import json
import time

import pytest
from typer.testing import CliRunner

from netarch.cli import app
from netarch.configgen.render import render_all
from netarch.engines import design
from netarch.errors import AddressOverlapError, InputValidationError, NetArchError
from netarch.export.writer import ip_plan_csv
from netarch.models.requirements import load_preset, load_requirements, load_requirements_file
from netarch.tui.app import NetArchApp

runner = CliRunner()


def _raw(name="campus"):
    return load_preset(name).model_dump(mode="json")


def _file(tmp_path, raw, name="in.json"):
    f = tmp_path / name
    f.write_text(json.dumps(raw), encoding="utf-8")
    return str(f)


def _codes(raw):
    with pytest.raises(NetArchError) as ei:
        load_requirements(raw)
    e = ei.value
    return {x.rule_id for x in getattr(e, "errors", [e])}


# F1: markup in user strings must print literally, never crash -------------------------


@pytest.mark.parametrize("cmd", ["validate", "plan", "design", "checklist"])
def test_markup_in_names_does_not_crash_cli(tmp_path, cmd):
    raw = _raw()
    raw["profile_name"] = "[/]"
    raw["sites"][0]["segments"][0]["name"] = "[/x]"
    r = runner.invoke(app, [cmd, "--input", _file(tmp_path, raw)])
    assert r.exit_code == 0, r.output
    assert r.exception is None


def test_markup_in_error_value_prints_panel(tmp_path):
    raw = _raw()
    raw["links"][0]["a"] = "[/x]"
    r = runner.invoke(app, ["validate", "--input", _file(tmp_path, raw)])
    assert r.exit_code == 2 and "[/x]" in r.stderr and r.exception is None or \
        isinstance(r.exception, SystemExit)


def test_markup_in_names_does_not_crash_tui(tmp_path):
    raw = _raw()
    raw["profile_name"] = "[/]"
    raw["sites"][0]["segments"][0]["name"] = "[b]x[/i]"
    bad = _raw()
    bad["links"][0]["a"] = "[/x]"

    async def go():
        a = NetArchApp()
        async with a.run_test(size=(120, 35)):
            assert a.load_raw(raw)
            assert not a.load_raw(bad)
            assert a.load_json(_file(tmp_path, raw)) is True

    asyncio.run(go())


# F2/F3: name collisions ---------------------------------------------------------------


def test_duplicate_link_rejected():
    raw = _raw()
    raw["links"].append({**raw["links"][0], "a": raw["links"][0]["b"],
                         "b": raw["links"][0]["a"]})
    assert "INPUT.LINK_DUPLICATE" in _codes(raw)


@pytest.mark.parametrize("sid", ["a--b", "cloud-vgw", "INET-SW", "evpl-carrier", "internet"])
def test_reserved_and_separator_site_ids_rejected(sid):
    raw = _raw("global")
    raw["sites"][1]["id"] = sid
    assert "INPUT.SITE_ID_RESERVED" in _codes(raw)


# F4: root overlapping the emulated Internet block --------------------------------------


def test_root_overlapping_public_block_rejected():
    raw = _raw("global")
    raw["address_space"]["root"] = "203.0.113.0/24"
    with pytest.raises(AddressOverlapError):
        load_requirements(raw)


# F5: hostile files exit 2 -------------------------------------------------------------


@pytest.mark.parametrize("content", [b"[" * 100000 + b"]" * 100000, b"\xff\xfe{}",
                                     b'{"a": 1, "a": 2}'],
                         ids=["deep", "not-utf8", "dup-key"])
def test_hostile_files_are_input_errors(tmp_path, content):
    f = tmp_path / "bad.json"
    f.write_bytes(content)
    with pytest.raises(InputValidationError) as ei:
        load_requirements_file(f)
    assert ei.value.rule_id == "INPUT.FILE"
    r = runner.invoke(app, ["validate", "--input", str(f)])
    assert r.exit_code == 2


def test_tui_deep_json_does_not_crash(tmp_path):
    f = tmp_path / "deep.json"
    f.write_bytes(b"[" * 100000 + b"]" * 100000)

    async def go():
        a = NetArchApp()
        async with a.run_test():
            assert a.load_json(str(f)) is False

    asyncio.run(go())


# F6: caps and speed -------------------------------------------------------------------


def _site(i):
    return {"id": f"s{i}", "kind": "building", "segments": [
        {"name": "STAFF", "vlan": 10, "hosts": 20, "growth_pct": 0, "role": "users"}]}


def test_site_and_link_caps():
    raw = _raw()
    raw["sites"] = [_site(i) for i in range(65)]
    raw["links"] = []
    assert "INPUT.FIELD" in _codes(raw) or _codes(raw)
    raw["sites"] = raw["sites"][:64]
    load_requirements(raw)


def test_max_sites_designs_and_renders_quickly():
    raw = _raw()
    raw["sites"] = [_site(i) for i in range(64)]
    raw["links"] = []
    t0 = time.perf_counter()
    plan = design(load_requirements(raw))
    render_all(plan, "pt")
    assert time.perf_counter() - t0 < 20


def test_huge_hosts_rejected():
    raw = _raw()
    raw["sites"][0]["segments"][0]["hosts"] = 10**30
    with pytest.raises(NetArchError):
        load_requirements(raw)


# F7/F8: VLAN names --------------------------------------------------------------------


def test_vlan_names_unique_and_short():
    raw = _raw()
    segs = raw["sites"][0]["segments"]
    segs[0]["name"] = "A B"
    segs[1]["name"] = "a-b"
    segs[2]["name"] = "ENGINEERING-AND-RESEARCH-STAFF-FLOOR-3"
    plan = design(load_requirements(raw))
    names = list(plan.device("acc-bldg-a").vlans.values())
    assert len(names) == len(set(names))
    assert all(len(n) <= 32 for n in names)
    pcs = [h.name for h in plan.hosts]
    assert len(pcs) == len(set(pcs))


# F9: CSV ------------------------------------------------------------------------------


def test_csv_site_and_tab_prefixed_names_neutralised():
    raw = _raw()
    raw["sites"][0]["id"] = "=HYPERLINK(1)"
    for lk in raw["links"]:
        for end in ("a", "b"):
            if lk[end] == "bldg-a":
                lk[end] = "=HYPERLINK(1)"
    raw["sites"][1]["segments"][0]["name"] = "+1"
    rows = list(csv.DictReader(io.StringIO(ip_plan_csv(design(load_requirements(raw))))))
    assert all(r["site"][:1] not in "=+-@\t\r" or r["site"] == "" for r in rows)
    assert all(r["name"][:1] not in "=+@\t\r" for r in rows)


# F10/F13: control characters ----------------------------------------------------------


@pytest.mark.parametrize("bad", ["ESC\x1b]0;PWNED\x07", "x\nhostname PWNED", "tab\there"])
def test_control_characters_rejected(bad):
    raw = _raw()
    raw["profile_name"] = bad
    with pytest.raises(NetArchError):
        load_requirements(raw)
    raw = _raw()
    raw["sites"][0]["segments"][0]["name"] = bad
    with pytest.raises(NetArchError):
        load_requirements(raw)


# F12: infinity ------------------------------------------------------------------------


def test_infinity_rejected():
    raw = _raw()
    raw["links"][0]["required_gbps"] = float("inf")
    with pytest.raises(NetArchError):
        load_requirements(raw)

"""P7: every CLI command + exit code (technical.md §10.1) and the TUI flow (§10.2–10.3)."""

import asyncio
import json

import pytest
from textual.widgets import DataTable, Input, Select, Static, TabbedContent, Tree
from typer.testing import CliRunner

from netarch.cli import app
from netarch.models.requirements import load_preset
from netarch.tui.app import NetArchApp
from netarch.verify import batfish_runner

runner = CliRunner()


def run(*args):
    return runner.invoke(app, list(args))


def _write(tmp_path, raw, name="in.json"):
    f = tmp_path / name
    f.write_text(json.dumps(raw), encoding="utf-8")
    return str(f)


def _raw(name="campus", **over):
    raw = load_preset(name).model_dump(mode="json")
    raw.update(over)
    return raw


@pytest.fixture(autouse=True)
def no_batfish(monkeypatch):
    monkeypatch.setattr(batfish_runner, "reachable", lambda host, **_: False)


def test_presets():
    r = run("presets")
    assert r.exit_code == 0 and all(p in r.stdout for p in ("campus", "metro", "global"))


def test_validate_ok_and_invalid(tmp_path):
    assert run("validate", "--preset", "metro").exit_code == 0
    bad = _raw()
    bad["sites"][0]["segments"][0]["vlan"] = 1
    bad["links"][0]["distance_m"] = -5
    r = run("validate", "--input", _write(tmp_path, bad))
    assert r.exit_code == 2
    assert "vlan" in r.stderr and "distance_m" in r.stderr and "hint" in r.stderr


def test_input_argument_errors(tmp_path):
    assert run("validate").exit_code == 2
    assert run("validate", "--preset", "campus", "--input", "x.json").exit_code == 2
    assert run("validate", "--preset", "nope").exit_code == 2
    assert run("validate", "--input", str(tmp_path / "missing.json")).exit_code == 2


def test_design_summary_and_json():
    r = run("design", "--preset", "global")
    assert r.exit_code == 0 and "rtr-delhi" in r.stdout and "RT-" in r.stdout
    r = run("design", "--preset", "campus", "--json")
    assert r.exit_code == 0 and json.loads(r.stdout)["devices"]


def test_design_constraint_exit_3(tmp_path):
    f = _write(tmp_path, _raw(address_space={"root": "10.0.0.0/24", "reserved": []}))
    r = run("design", "--input", f)
    assert r.exit_code == 3 and "ADDR.E1" in r.stderr


def test_debug_shows_exception(tmp_path):
    f = _write(tmp_path, _raw(address_space={"root": "10.0.0.0/24", "reserved": []}))
    r = run("--debug", "design", "--input", f)
    assert r.exit_code != 0 and r.exception is not None


def test_explain_filters():
    assert "RT.R2" in run("explain", "--preset", "global", "--domain", "routing").stdout
    assert run("explain", "--preset", "metro", "--id", "QOS-01", "--markdown").exit_code == 0
    assert run("explain", "--preset", "metro", "--id", "ZZ-99").exit_code == 2


def test_plan_table():
    r = run("plan", "--preset", "campus")
    assert r.exit_code == 0 and "0.0.1.255" in r.stdout


def test_export_and_options(tmp_path):
    r = run("export", "--preset", "campus", "--out", str(tmp_path), "--zip",
            "--dialect", "full")
    assert r.exit_code == 0 and (tmp_path / "netarch-campus-configs.zip").exists()
    assert (tmp_path / "configs" / "dist-bldg-a.txt").exists()
    r = run("export", "--preset", "campus", "--out", str(tmp_path / "o"), "--only", "configs")
    assert r.exit_code == 0 and not (tmp_path / "o" / "plan.json").exists()
    assert run("export", "--preset", "campus", "--dialect", "xr").exit_code == 2
    assert run("export", "--preset", "campus", "--out", str(tmp_path),
               "--only", "bogus").exit_code == 2


@pytest.mark.parametrize("name", ["campus", "metro", "global"])
def test_verify_passes_with_batfish_skipped(name):
    r = run("verify", "--preset", name)
    assert r.exit_code == 0
    assert "SELF-CHECK: PASS" in r.stdout and "NOT CONNECTED (skipped)" in r.stdout


def test_verify_no_batfish_flag_and_failure(monkeypatch):
    assert "skipped (--no-batfish)" in run("verify", "--preset", "campus",
                                           "--no-batfish").stdout
    from netarch.verify import selfcheck

    monkeypatch.setattr(selfcheck, "all_pass", lambda res: False)
    assert run("verify", "--preset", "campus", "--no-batfish").exit_code == 1


def test_verify_batfish_fail_sets_exit_1(monkeypatch):
    monkeypatch.setattr(batfish_runner, "run_batfish", lambda *a, **k: batfish_runner
                        .BatfishResult("FAIL", [("OSPF sessions", "FAIL", "x")]))
    r = run("verify", "--preset", "campus")
    assert r.exit_code == 1 and "BATFISH: FAIL" in r.stdout


def test_checklist_command():
    r = run("checklist", "--preset", "metro")
    assert r.exit_code == 0 and "evpl-carrier" in r.stdout


# --- TUI -------------------------------------------------------------------------------


def _tui(coro):
    async def go():
        app_ = NetArchApp()
        async with app_.run_test(size=(120, 35)) as pilot:
            await coro(app_, pilot)

    asyncio.run(go())


def test_tui_preset_decisions_verify_export(tmp_path):
    async def flow(a, pilot):
        await pilot.click("#preset-campus")
        await pilot.pause()
        assert a.plan is not None
        assert a.query_one("#iptable", DataTable).row_count == len(a.plan.addressing.subnets)
        assert len(a.query_one("#tree", Tree).root.children) >= 5
        a.action_tab("verify")
        a.run_verify()
        assert "SELF-CHECK: PASS" in str(a.query_one("#verify-status", Static).render())
        a.action_tab("export")
        a.query_one("#export-path", Input).value = str(tmp_path)
        a.do_export()
        assert (tmp_path / "configs" / "dist-bldg-a.txt").exists()
        assert a.query_one("#tabs", TabbedContent).active == "export"

    _tui(flow)


def test_tui_broken_json_shows_field_errors(tmp_path):
    bad = _raw()
    bad["sites"][0]["segments"][0]["hosts"] = 0
    path = _write(tmp_path, bad)

    async def flow(a, pilot):
        a.query_one("#json-path", Input).value = path
        await pilot.click("#load-json")
        await pilot.pause()
        text = str(a.query_one("#errors", Static).render())
        assert "hosts" in text and a.plan is None
        assert a.load_json(str(tmp_path / "missing.json")) is False
        assert "cannot read" in str(a.query_one("#errors", Static).render())

    _tui(flow)


def test_tui_distance_whatif_walks_media():
    async def flow(a, pilot):
        raw = _raw("campus")
        raw["links"][0]["inter_building"] = False
        assert a.load_raw(raw)
        a.query_one("#link-select", Select).value = "0"
        seen = []
        for d in ("95", "105", "450", "12000", "36000"):
            a.query_one("#distance", Input).value = d
            a.apply_distance()
            seen.append(str(a.query_one("#whatif-out", Static).render()))
        assert "Cat6a" in seen[0] or "copper" in seen[0].lower()
        assert "OM4" in seen[1]
        assert "LR" in seen[2] and "ER" in seen[3] and "ZR" in seen[4]
        a.query_one("#distance", Input).value = "abc"
        a.apply_distance()
        assert "not a number" in str(a.query_one("#whatif-out", Static).render())
        a.query_one("#distance", Input).value = "200000"
        a.apply_distance()
        assert "✗" in str(a.query_one("#whatif-out", Static).render())

    _tui(flow)


def test_tui_config_viewer_and_keys():
    async def flow(a, pilot):
        await pilot.click("#preset-global")
        await pilot.pause()
        a.query_one("#device-select", Select).value = "rtr-delhi"
        await pilot.pause()
        assert "router bgp 65001" in str(a.query_one("#config-view", Static).render())
        await pilot.press("v")
        assert a.query_one("#tabs", TabbedContent).active == "verify"

    _tui(flow)


def test_tui_actions_without_plan_are_safe():
    async def flow(a, pilot):
        a.run_verify()
        a.do_export()
        a.apply_distance()
        assert "Load a design" in str(a.query_one("#whatif-out", Static).render())

    _tui(flow)


def test_export_write_error_is_a_panel_not_a_traceback(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    r = run("export", "--preset", "campus", "--out", str(blocker / "sub"))
    assert r.exit_code == 2 and "Export error" in r.stderr and "Traceback" not in r.stderr


def test_tui_uses_one_secret_set_per_plan(tmp_path):
    async def flow(a, pilot):
        await pilot.click("#preset-global")
        await pilot.pause()
        a.query_one("#export-path", Input).value = str(tmp_path)
        a.do_export()
        a.query_one("#device-select", Select).value = "rtr-delhi"
        await pilot.pause()
        shown = str(a.query_one("#config-view", Static).render())
        assert a.secrets["enable"] in shown
        assert a.secrets["enable"] in (tmp_path / "configs" / "rtr-delhi.txt").read_text()

    _tui(flow)


def test_verify_writes_batfish_report_when_run(monkeypatch, tmp_path):
    monkeypatch.setattr(batfish_runner, "run_batfish", lambda *a, **k: batfish_runner
                        .BatfishResult("PASS", [("configs parsed", "PASS", "")]))
    rep = tmp_path / "r" / "batfish-report.md"
    r = run("verify", "--preset", "campus", "--report", str(rep))
    assert r.exit_code == 0 and "Batfish report — PASS" in rep.read_text("utf-8")

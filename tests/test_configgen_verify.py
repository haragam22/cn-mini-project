"""P5 config generator + exports, P6 self-check (mutations) and Batfish graceful skip."""

import csv
import io
import json
import re
import zipfile

import pytest

from netarch.configgen import render
from netarch.engines import design
from netarch.export.writer import ip_plan_csv, write_all
from netarch.models.requirements import load_preset, load_requirements
from netarch.verify import batfish_runner
from netarch.verify.checklist import build_checklist
from netarch.verify.selfcheck import CHECKS, all_pass, run_selfcheck

PRESETS = ["campus", "metro", "global"]
FIXED_TS = "2026-11-10T00:00:00Z"


def fixed_secrets(plan):
    s = {"enable": "ENABLESECRET", "admin": "ADMINSECRET"}
    return s | {t.psk_ref: f"PSK{i}" for i, t in enumerate(plan.vpn_tunnels)}


@pytest.fixture(scope="module")
def plans():
    return {p: design(load_preset(p)) for p in PRESETS}


def configs(plan, dialect):
    return render.render_all(plan, dialect, fixed_secrets(plan), timestamp=FIXED_TS)


# --- P5 config hygiene -----------------------------------------------------------------


@pytest.mark.parametrize("name", PRESETS)
@pytest.mark.parametrize("dialect", ["pt", "full"])
def test_config_hygiene(plans, name, dialect):
    for host, text in configs(plans[name], dialect).items():
        assert "allowed vlan all" not in text, host
        assert not re.search(r"native vlan 1$", text, re.M), host
        assert not re.search(r"^enable password", text, re.M), host
        for m in re.finditer(r"^ network (\S+) (\S+) area", text, re.M):
            assert m[2].startswith("0."), f"{host}: mask in OSPF network: {m[0]}"
        if "2960" in plans[name].device(host).model:
            assert "encapsulation dot1q" not in text
        assert text.rstrip().endswith("end")


def test_3560_trunk_has_encapsulation_before_mode(plans):
    text = configs(plans["campus"], "pt")["dist-bldg-a"]
    block = text.split("interface FastEthernet0/1\n", 1)[1].split("!", 1)[0]
    assert block.index("encapsulation dot1q") < block.index("switchport mode trunk")


def test_skeleton_order(plans):
    text = configs(plans["global"], "full")["rtr-delhi"]
    # §9.3 order, except crypto/QoS definitions come before the interfaces that apply them
    # (decisions.md 2026-11-10: IOS rejects service-policy for an undefined policy-map).
    order = ["\nhostname", "\nservice password-encryption", "\nno ip domain-lookup",
             "\nbanner", "\nusername admin", "\ncrypto isakmp policy", "\ninterface ",
             "\nrouter ospf", "\nrouter bgp", "\nip route", "\nip prefix-list",
             "\nroute-map", "\nip access-list extended IOT", "\nline vty", "\nend"]
    pos = [text.index(k) for k in order]
    assert pos == sorted(pos)


def test_pt_compat_header_lists_downgrades(plans):
    pt = configs(plans["metro"], "pt")["rtr-hq"]
    full = configs(plans["metro"], "full")["rtr-hq"]
    assert "! NETARCH-PT-COMPAT: QoS (MQC/LLQ) block omitted" in pt
    assert "policy-map WAN-EDGE" not in pt and "service-policy" not in pt
    assert "policy-map WAN-EDGE" in full and "service-policy output WAN-EDGE" in full
    assert "priority percent 30" in full and "set dscp ef" in full
    assert "NETARCH-PT-COMPAT" not in full


def test_full_dialect_crypto_and_log(plans):
    full = configs(plans["global"], "full")["rtr-delhi"]
    pt = configs(plans["global"], "pt")["rtr-delhi"]
    assert "hash sha256" in full and "group 14" in full and "esp-sha256-hmac" in full
    assert "hash sha\n" in pt and "group 5" in pt
    assert "deny ip any any log" in full and "deny ip any any log" not in pt
    assert "ip mtu 1400" in full and "ip tcp adjust-mss 1360" in full
    assert "crypto isakmp key PSK0 address" in full


def test_pt_accepted_rows_switch_features_on(plans, monkeypatch):
    monkeypatch.setattr(render, "pt_result", lambda row: "accepted")
    pt = configs(plans["metro"], "pt")["rtr-hq"]
    assert "policy-map WAN-EDGE" in pt and "NETARCH-PT-COMPAT: QoS" not in pt


def test_profile_name_cannot_inject_config_lines():
    raw = load_preset("campus").model_dump(mode="json")
    raw["profile_name"] = "x\nenable password hacked"
    with pytest.raises(Exception, match="pattern"):  # rejected at input (security F10)
        load_requirements(raw)
    # defence in depth: the header filter still flattens control characters
    assert render.ios_text("x\nenable password hacked") == "x?enable password hacked"
    p = design(load_preset("campus"))
    text = render.render_all(p, "pt", timestamp=FIXED_TS)["dist-bldg-a"]
    assert not re.search(r"^enable password", text, re.M)


def test_unknown_dialect_rejected(plans):
    p = plans["campus"]
    with pytest.raises(ValueError):
        render.render_device(p, p.devices[0], "xr", fixed_secrets(p))


def test_random_secrets_differ(plans):
    a, b = render.make_secrets(plans["global"]), render.make_secrets(plans["global"])
    assert a["enable"] != b["enable"] and len(a) == 2 + 4


@pytest.mark.parametrize("name", PRESETS)
@pytest.mark.parametrize("dialect", ["pt", "full"])
def test_golden_configs(plans, name, dialect, snapshot):
    cfg = configs(plans[name], dialect)
    assert "\n".join(f"===== {h}\n{t}" for h, t in sorted(cfg.items())) == snapshot


# --- exports ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PRESETS)
def test_export_writes_all_artefacts(plans, name, tmp_path):
    p = plans[name]
    paths = write_all(p, tmp_path, dialect="pt", make_zip=True, secrets=fixed_secrets(p),
                      timestamp=FIXED_TS)
    names = {x.relative_to(tmp_path).as_posix() for x in paths}
    assert {"rationale.md", "ip-plan.csv", "plan.json", "pt-checklist.md", "topology.mmd",
            "secrets.txt", f"netarch-{name}-configs.zip"} <= names
    assert {f"configs/{d.hostname}.txt" for d in p.devices} <= names
    with zipfile.ZipFile(tmp_path / f"netarch-{name}-configs.zip") as z:
        zn = set(z.namelist())
        assert "secrets.txt" not in zn and "rationale.md" in zn and "pt-checklist.md" in zn
    assert json.loads((tmp_path / "plan.json").read_text("utf-8"))["requirements"]
    assert "PSK" in (tmp_path / "secrets.txt").read_text() or not p.vpn_tunnels


def test_secrets_file_owner_only(plans, tmp_path):
    import os
    import stat

    write_all(plans["global"], tmp_path, only=("secrets",))
    mode = stat.S_IMODE(os.stat(tmp_path / "secrets.txt").st_mode)
    if os.name == "posix":
        assert mode == 0o600
    else:  # Windows maps only the write bit; the file must still be written correctly
        assert (tmp_path / "secrets.txt").read_text().startswith("# NetArchitect")
    write_all(plans["global"], tmp_path, only=("secrets",))  # overwriting works


def test_export_only_and_bad_artefact(plans, tmp_path):
    paths = write_all(plans["campus"], tmp_path, only=("rationale",))
    assert [x.name for x in paths] == ["rationale.md"]
    with pytest.raises(ValueError):
        write_all(plans["campus"], tmp_path, only=("nope",))


def test_ip_plan_csv_rows_and_formula_injection():
    raw = load_preset("campus").model_dump(mode="json")
    raw["sites"][0]["segments"][0]["name"] = "=HYPERLINK(1)"
    p = design(load_requirements(raw))
    rows = list(csv.DictReader(io.StringIO(ip_plan_csv(p))))
    assert len(rows) == len(p.addressing.subnets)
    assert all(not r["name"].startswith("=") for r in rows)


def test_checklist_content(plans):
    md = build_checklist(plans["global"])
    assert "securityk9" in md and "show crypto isakmp sa" in md and "## 2. Cabling" in md
    md = build_checklist(plans["campus"])
    assert "FAIL expected (ACL WIFI-IN-20)" in md and "show interfaces trunk" in md
    assert "copper cross-over" in md and "copper straight-through" in md


# --- P6 self-check ---------------------------------------------------------------------


@pytest.mark.parametrize("name", PRESETS)
@pytest.mark.parametrize("dialect", ["pt", "full"])
def test_selfcheck_all_pass(plans, name, dialect):
    res = run_selfcheck(plans[name], configs(plans[name], dialect))
    assert all_pass(res), [r for r in res if r.status == "FAIL"]
    assert {r.id for r in res} == set(CHECKS)


def _mutate(plans, name, host, old, new, count=1):
    cfg = configs(plans[name], "pt")
    assert old in cfg[host], old
    cfg[host] = cfg[host].replace(old, new, count)
    return {r.id for r in run_selfcheck(plans[name], cfg) if r.status == "FAIL"}


def test_mutation_duplicate_ip(plans):
    failed = _mutate(plans, "campus", "dist-bldg-b", "ip address 10.0.16.13 ",
                     "ip address 10.0.16.12 ")
    assert "C2" in failed


def test_mutation_missing_vlan_on_trunk(plans):
    failed = _mutate(plans, "campus", "acc-bldg-a", "allowed vlan 10,20,40,99",
                     "allowed vlan 10,20,40")
    assert "C5" in failed


def test_mutation_vlan_missing_from_database(plans):
    failed = _mutate(plans, "campus", "acc-bldg-a", "vlan 40\n name SERVERS\n", "")
    assert "C4" in failed


def test_mutation_wrong_wildcard(plans):
    failed = _mutate(plans, "campus", "dist-bldg-a", "network 10.0.10.0 0.0.0.255",
                     "network 10.0.10.0 0.0.255.0")
    assert "C8" in failed


@pytest.mark.parametrize(("name", "host", "old", "new", "cid"), [
    ("campus", "dist-bldg-a", "ip address 10.0.10.1 ", "ip address 10.0.20.1 ", "C1"),
    ("campus", "dist-bldg-a", "ip address 10.0.10.1 ", "ip address 10.0.10.0 ", "C1"),
    ("campus", "dist-bldg-a", "ip address 10.0.16.1 255.255.255.252",
     "ip address 10.0.16.1 255.255.255.0", "C1"),
    ("campus", "dist-bldg-a", "native vlan 999", "native vlan 1", "C5"),
    ("campus", "dist-bldg-a", "allowed vlan 10,20,40,99", "allowed vlan all", "C5"),
    ("campus", "dist-bldg-a", " switchport trunk encapsulation dot1q\n", "", "C6"),
    ("campus", "acc-bldg-a", "switchport mode trunk", "switchport trunk encapsulation dot1q\n"
     " switchport mode trunk", "C6"),
    ("campus", "dist-bldg-a", "ip routing\n", "", "C7"),
    ("campus", "dist-bldg-b", "router-id 10.0.16.13", "router-id 10.0.16.12", "C8"),
    ("campus", "dist-bldg-a", "ip access-group WIFI-IN-20 in", "ip access-group NOPE in", "C9"),
    ("global", "rtr-mumbai", "tunnel destination 203.0.113.1", "tunnel destination 203.0.113.9",
     "C10"),
    ("global", "rtr-mumbai", "permit gre host 203.0.113.2 host 203.0.113.1",
     "permit gre host 203.0.113.2 host 203.0.113.7", "C10"),
    ("campus", "dist-bldg-a", "enable secret", "enable password", "C11"),
    ("campus", "dist-bldg-b", "hostname dist-bldg-b", "hostname dist-bldg-a", "C11"),
])
def test_mutations_hit_the_right_check(plans, name, host, old, new, cid):
    assert cid in _mutate(plans, name, host, old, new)


def test_link_end_mismatch_c3(plans):
    cfg = configs(plans["campus"], "pt")
    cfg["dist-bldg-b"] = cfg["dist-bldg-b"].replace(
        "ip address 10.0.16.2 255.255.255.252", "ip address 10.0.16.2 255.255.255.248")
    failed = {r.id for r in run_selfcheck(plans["campus"], cfg) if r.status == "FAIL"}
    assert "C3" in failed


def test_unknown_device_and_unused_acl(plans):
    cfg = configs(plans["campus"], "pt")
    cfg["rogue"] = "hostname rogue\nend\n"
    cfg["dist-bldg-a"] += "ip access-list extended UNUSED\n deny ip any any\n"
    failed = {r.id for r in run_selfcheck(plans["campus"], cfg) if r.status == "FAIL"}
    assert {"C9", "C11"} <= failed


# --- Batfish graceful skip -------------------------------------------------------------


def test_batfish_unreachable_is_skipped(plans, monkeypatch):
    monkeypatch.setattr(batfish_runner, "reachable", lambda host, **_: False)
    r = batfish_runner.run_batfish(plans["campus"], {})
    assert r.skipped and r.status == "NOT CONNECTED (skipped)"
    assert "NOT CONNECTED" in r.report_md()


def test_reachable_false_on_closed_port():
    assert batfish_runner.reachable("127.0.0.1", port=1, timeout=0.5) is False


def test_snapshot_layout(plans, tmp_path):
    p = plans["global"]
    root = batfish_runner.build_snapshot(p, configs(p, "full"), tmp_path)
    assert len(list((root / "configs").glob("*.cfg"))) == len(p.devices)
    assert len(list((root / "hosts").glob("*.json"))) == len(p.hosts)


@pytest.mark.batfish
@pytest.mark.parametrize("name", PRESETS)
def test_batfish_full_configs(plans, name):
    r = batfish_runner.run_batfish(plans[name], configs(plans[name], "full"))
    assert not r.skipped, "start Batfish first"
    assert r.status == "PASS", r.report_md()


def test_pt_omits_redistribution_when_row_untested(plans):
    pt = configs(plans["global"], "pt")["rtr-delhi"]
    full = configs(plans["global"], "full")["rtr-delhi"]
    assert "route-map BGP-TO-OSPF" not in pt and "ip prefix-list" not in pt
    assert "redistribute bgp" not in pt and "BGP → OSPF redistribution" in pt
    assert "redistribute bgp 65001 subnets route-map BGP-TO-OSPF" in full
    assert all_pass(run_selfcheck(plans["global"], configs(plans["global"], "pt")))


def test_vty_all_lines(plans):
    assert "line vty 0 15" in configs(plans["campus"], "pt")["dist-bldg-a"]


@pytest.mark.parametrize(("old", "new"), [
    ("crypto isakmp key PSK0 address 203.0.113.1", "crypto isakmp key WRONG address 203.0.113.1"),
    ("tunnel source GigabitEthernet0/1", "tunnel source Loopback0"),
])
def test_c10_psk_and_source_mutations(plans, old, new):
    assert "C10" in _mutate(plans, "global", "rtr-mumbai", old, new)


def test_summary_expectations_global(plans):
    [(hub, present, absent)] = batfish_runner.summary_expectations(plans["global"])
    blocks = {b.site: b.block for b in plans["global"].addressing.site_blocks}
    assert hub == "rtr-delhi"
    assert present == {blocks[s] for s in ("mumbai", "bangalore", "singapore")}
    assert absent and not absent & present
    assert batfish_runner.summary_expectations(plans["campus"]) == []


def test_host_json_has_gateway(plans, tmp_path):
    p = plans["campus"]
    root = batfish_runner.build_snapshot(p, configs(p, "full"), tmp_path)
    h = json.loads(next((root / "hosts").glob("*.json")).read_text())
    assert h["hostInterfaces"]["eth0"]["gateway"]

"""P2 gate: every decision is complete and backed by its inputs; renderers; explain CLI."""

import json
import re

import pytest
from typer.testing import CliRunner

from netarch.cli import app
from netarch.engines import design_l1_l2, l1_media
from netarch.explain.render import render_markdown, render_report, render_text
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import PRESET_NAMES, Requirements, load_preset


def _all_decisions():
    out = []
    for name in PRESET_NAMES:
        out += design_l1_l2(load_preset(name)).decisions
    return out


DECISIONS = _all_decisions()


def _num(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def _numbers(key, v):
    """Text forms an input value must appear as in the rationale."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return []
    if isinstance(v, list):
        return [_num(x) for x in v]
    forms = [_num(v)]
    if key.endswith("_m") and v >= 1000:
        forms.append(f"{_num(v / 1000)} km")
    return forms


def test_presets_produce_decisions_for_every_domain_built_in_p2():
    assert {d.domain for d in DECISIONS} == {"media", "transceiver", "topology", "switching"}


@pytest.mark.parametrize("d", DECISIONS, ids=lambda d: f"{d.id}-{d.subject}")
def test_every_decision_is_complete(d):
    assert d.rationale.strip()
    assert d.standards and all(s.strip() for s in d.standards)
    single_switch = d.rule_id == "L2.CAP" and d.inputs["access_switches"] <= 1
    if not single_switch:  # the only P2 decision with no alternative is "1 switch suffices"
        assert d.rejected, "alternatives exist but none listed"
    assert all(r.option and r.reason for r in d.rejected)
    assert d.counterfactual
    for key, v in d.inputs.items():
        for form in _numbers(key, v):
            assert form in d.rationale, f"{key}={v!r}: {form!r} missing from rationale"


def test_22km_link_rationale_says_22_km():
    d = next(d for d in DECISIONS if d.subject == "Link hq ↔ remote-1" and d.domain == "media")
    assert "22 km" in d.rationale and "22000" in d.rationale


def _om4(decisions):
    return [d for d in decisions if d.choice.startswith("OM4") or d.choice == "10GBASE-SR"]


def test_no_om4_rationale_blames_attenuation():
    extra = []
    for dist, inter in ((60, True), (100.01, False), (250, False), (400, False)):
        req = Requirements.model_validate({
            "profile_name": "t", "profile_type": "campus",
            "address_space": {"root": "10.0.0.0/16"},
            "sites": [
                {"id": s, "kind": "building",
                 "segments": [{"name": "U", "vlan": 10, "hosts": 5, "growth_pct": 0,
                               "role": "users"}]}
                for s in ("a", "b")
            ],
            "links": [{"a": "a", "b": "b", "distance_m": dist, "inter_building": inter,
                       "required_gbps": 10}],
            "resiliency": "dual_uplink",
        })
        extra += l1_media.run(NetworkPlan(requirements=req)).decisions
    om4 = _om4(DECISIONS + extra)
    assert len(om4) >= 14  # campus 3 links × 2 + 4 synthetic × 2
    for d in om4:
        assert "attenuation" not in d.rationale.lower(), d.id
        assert "modal dispersion" in d.rationale, d.id


def test_spec_notes_rendered_where_spec_is_refined():
    d = _om4(DECISIONS)[0]
    assert d.spec_note
    assert f"Spec note: {d.spec_note[:30]}" in render_text(d, width=10_000)
    assert "**Spec note:**" in render_markdown(d)


def test_render_text_sections():
    d = next(d for d in DECISIONS if d.choice == "10GBASE-ZR")
    text = render_text(d)
    for piece in ("[transceiver] Link hq ↔ remote-2", "Choice: 10GBASE-ZR (rule MEDIA.R3)",
                  "Why:", "Math:", "Rejected:", "Would change:", "WARNING:", "Standards:"):
        assert piece in text, piece
    assert all(len(line) <= 100 for line in text.splitlines())


def test_render_report_formats():
    ds = DECISIONS[:2]
    assert render_report(ds).count("\n\n") == 1
    md = render_report(ds, "markdown")
    assert md.startswith("### L1-01")
    with pytest.raises(ValueError):
        render_report(ds, "html")


runner = CliRunner()


def test_cli_explain_campus_prints_every_link():
    res = runner.invoke(app, ["explain", "--preset", "campus"])
    assert res.exit_code == 0, res.output
    for pair in ("bldg-a ↔ bldg-b", "bldg-b ↔ bldg-c", "bldg-a ↔ bldg-c"):
        assert f"[media] Link {pair}" in res.output
        assert f"[transceiver] Link {pair}" in res.output
    assert "TOP-01" in res.output and "L2-12" in res.output


def test_cli_explain_filters_and_markdown():
    res = runner.invoke(app, ["explain", "--preset", "metro", "--id", "L1-04", "--markdown"])
    assert res.exit_code == 0, res.output
    assert res.output.startswith("### L1-04") and "10GBASE-ZR" in res.output
    res = runner.invoke(app, ["explain", "--preset", "metro", "--domain", "topology"])
    assert res.exit_code == 0 and "TOP-01" in res.output and "L1-01" not in res.output


def test_cli_explain_errors(tmp_path):
    assert runner.invoke(app, ["explain"]).exit_code == 2
    assert runner.invoke(app, ["explain", "--preset", "nope"]).exit_code == 2
    data = json.loads(json.dumps(load_preset("metro").model_dump()))
    data["links"][1]["distance_m"] = 81000
    f = tmp_path / "far.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    res = runner.invoke(app, ["explain", "--input", str(f)])
    assert res.exit_code == 3
    assert "OpticalBudget" in res.output or "MEDIA.R3" in res.output


def test_why_sentences_carry_no_numbers():
    # Every number in a rationale must come from the engine's fields, not fixed prose.
    from netarch.explain.render import WHY

    measured = re.compile(r"\d+(\.\d+)?\s*(m|km|dB|W|nm|Gbps)\b")
    for key, text in WHY.items():
        assert not measured.search(text), key
    for d in DECISIONS:
        assert (d.domain, d.rule_id) in WHY, d.rule_id

"""P1: error hierarchy (§13), Decision/NetworkPlan models (§4.2–4.3), explain skeleton."""

import json

import pytest
from pydantic import ValidationError

from netarch import errors
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.explain.render import render_markdown, render_rationale
from netarch.models.decisions import Decision, Rejected
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import load_preset

SUBCLASSES = [
    "InputValidationError",
    "PhysicalDistanceViolationError",
    "OpticalBudgetExceededError",
    "AddressSpaceExhaustedError",
    "AddressOverlapError",
    "TopologyConstraintError",
    "CapacityError",
    "VerificationError",
]


@pytest.mark.parametrize("name", SUBCLASSES)
def test_error_hierarchy(name):
    cls = getattr(errors, name)
    assert issubclass(cls, errors.NetArchError)
    e = cls(field="f", value=3, rule_id="R.1", message="m", hint="h")
    assert (e.field, e.value, e.rule_id, e.message, e.hint) == ("f", 3, "R.1", "m", "h")
    assert str(e) == "m"
    assert e.to_dict() == {
        "error": name, "field": "f", "value": 3, "rule_id": "R.1", "message": "m", "hint": "h",
    }


def test_netarch_error_is_exception():
    assert issubclass(errors.NetArchError, Exception)


def _decision(**over):
    kw = dict(
        id="L1-03",
        domain="media",
        subject="Link HQ ↔ Remote-1",
        choice="OS2 SMF + 10GBASE-ER",
        rule_id="MEDIA.R3",
        inputs={"distance_m": 22000, "required_gbps": 10},
        math=["loss = 22 × 0.25 + 2 × 0.5 + 5 × 0.1 = 7.0 dB"],
        standards=["IEEE 802.3 Cl.52"],
        rejected=[Rejected(option="OM4 + 10GBASE-SR", reason="reach 400 m < 22,000 m required")],
        counterfactual="Would select LR if distance ≤ 10 km",
        warnings=[],
        spec_note=None,
    )
    kw.update(over)
    return make_decision(**kw)


def test_decision_fields_and_domain_literal():
    d = _decision()
    assert isinstance(d, Decision)
    with pytest.raises(ValidationError):
        Decision(**{**d.model_dump(), "domain": "magic"})


def test_decision_id_format():
    assert decision_id("L1", 3) == "L1-03"
    assert decision_id("RT", 12) == "RT-12"
    with pytest.raises(ValueError):
        decision_id("XX", 1)


def test_rejected_helper():
    r = rejected("Cat6a", "100 m channel")
    assert r == Rejected(option="Cat6a", reason="100 m channel")


def test_builder_fills_rationale_from_fields():
    d = _decision()
    assert d.rationale == render_rationale(d)
    for piece in ("Link HQ ↔ Remote-1", "OS2 SMF + 10GBASE-ER", "MEDIA.R3",
                  "distance_m=22000", "OM4 + 10GBASE-SR", "reach 400 m < 22,000 m required",
                  "IEEE 802.3 Cl.52", "7.0 dB"):
        assert piece in d.rationale, piece


def test_render_rationale_without_alternatives_or_math():
    d = _decision(rejected=[], math=[], standards=[], counterfactual=None, inputs={})
    text = render_rationale(d)
    assert text.startswith("For Link HQ ↔ Remote-1, chose OS2 SMF + 10GBASE-ER")
    assert "Rejected" not in text


def test_render_markdown_lists_everything():
    d = _decision(warnings=["ER would leave only 0.45 dB margin"], spec_note="spec says X")
    md = render_markdown(d)
    assert md.startswith("### L1-03")
    for piece in ("OS2 SMF + 10GBASE-ER", "MEDIA.R3", "7.0 dB", "OM4 + 10GBASE-SR",
                  "IEEE 802.3 Cl.52", "0.45 dB margin", "spec says X",
                  "Would select LR if distance ≤ 10 km"):
        assert piece in md, piece


def test_network_plan_round_trips_json():
    req = load_preset("campus")
    plan = NetworkPlan(requirements=req, decisions=[_decision()], warnings=["w"])
    assert plan.sites == req.sites
    text = plan.model_dump_json()
    back = NetworkPlan.model_validate_json(text)
    assert back == plan
    assert json.loads(text)["decisions"][0]["id"] == "L1-03"


def test_network_plan_defaults_empty():
    plan = NetworkPlan(requirements=load_preset("metro"))
    assert plan.devices == [] and plan.links == [] and plan.segments == []
    assert plan.decisions == [] and plan.warnings == []

"""P2: L1 media + transceiver engine (technical.md §5.1–5.4)."""

import pytest

from netarch.engines import l1_media
from netarch.errors import OpticalBudgetExceededError, PhysicalDistanceViolationError
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import Requirements, load_preset


def _req(links, *, access_run=None, aps=0):
    """Requirements built with model_validate only (skips P1 cross-checks on purpose, so the
    engine's own guards are exercised)."""
    seg = [{"name": "STAFF", "vlan": 10, "hosts": 50, "growth_pct": 0, "role": "users"}]
    sites = [
        {"id": "a", "kind": "building", "segments": seg, "access_points": aps,
         "access_run_max_m": access_run},
        {"id": "b", "kind": "building", "segments": seg},
    ]
    return Requirements.model_validate({
        "profile_name": "t", "profile_type": "campus",
        "address_space": {"root": "10.0.0.0/16"},
        "sites": sites, "links": links, "resiliency": "dual_uplink",
    })


def _link(d, *, inter=False, media=None):
    return {"a": "a", "b": "b", "distance_m": d, "inter_building": inter,
            "required_gbps": 10, "requested_media": media}


def _run(*links, **kw):
    return l1_media.run(NetworkPlan(requirements=_req(list(links), **kw)))


def _pair(plan, i=0):
    """(media decision, transceiver decision) for link i."""
    ds = [d for d in plan.decisions if d.subject.startswith("Link")]
    return ds[2 * i], ds[2 * i + 1]


@pytest.mark.parametrize(
    ("d", "media", "optic", "rule"),
    [
        (100, "Cat6a", "10GBASE-T", "MEDIA.R1"),
        (100.01, "OM4", "10GBASE-SR", "MEDIA.R2"),
        (400, "OM4", "10GBASE-SR", "MEDIA.R2"),
        (400.01, "OS2", "10GBASE-LR", "MEDIA.R3"),
        (10000, "OS2", "10GBASE-LR", "MEDIA.R3"),
        (10010, "OS2", "10GBASE-ER", "MEDIA.R3"),
    ],
)
def test_distance_boundaries(d, media, optic, rule):
    plan = _run(_link(d))
    assert (plan.links[0].media, plan.links[0].optic) == (media, optic)
    m, x = _pair(plan)
    assert (m.domain, x.domain) == ("media", "transceiver")
    assert m.rule_id == rule and x.rule_id == rule
    assert x.choice == optic


def test_10km_lr_reports_1_5_db_margin():
    _, x = _pair(_run(_link(10000)))
    assert any("margin = 6.2 − 4.70 = 1.50 dB" in line for line in x.math)
    assert x.warnings == []


def test_metro_preset_15_22_35_km():
    plan = l1_media.run(NetworkPlan(requirements=load_preset("metro")))
    by_pair = {(lk.a, lk.b): lk.optic for lk in plan.links}
    assert by_pair[("hq", "colo")] == "10GBASE-ER"
    assert by_pair[("hq", "remote-1")] == "10GBASE-ER"
    assert by_pair[("hq", "remote-2")] == "10GBASE-ZR"
    zr = next(d for d in plan.decisions if d.domain == "transceiver" and "remote-2" in d.subject
              and "hq" in d.subject)
    assert zr.choice == "10GBASE-ZR"
    assert any("non-IEEE" in w for w in zr.warnings)
    assert any("0.45 dB" in w and "10GBASE-ER" in w for w in zr.warnings)
    er_rej = next(r for r in zr.rejected if r.option == "10GBASE-ER")
    assert "0.45 dB" in er_rej.reason and "1 dB" in er_rej.reason
    # 15 and 22 km ER links carry no warnings
    for d in plan.decisions:
        if d.domain == "transceiver" and d.choice == "10GBASE-ER":
            assert d.warnings == []
    assert any("non-IEEE" in w for w in plan.warnings)


def test_81km_raises_optical_budget_error():
    with pytest.raises(OpticalBudgetExceededError) as ei:
        _run(_link(81000))
    assert ei.value.field == "links[0].distance_m"


def test_80km_zr_selected_with_margin_warning():
    _, x = _pair(_run(_link(80000)))
    assert x.choice == "10GBASE-ZR"
    assert any("0.10 dB" in w and "below" in w for w in x.warnings)


def test_er_22km_rejects_lr_with_reach_and_loss():
    _, x = _pair(_run(_link(22000)))
    lr = next(r for r in x.rejected if r.option == "10GBASE-LR")
    assert "10 km < 22 km" in lr.reason and "9.20 dB" in lr.reason and "6.2 dB" in lr.reason
    assert any("7.00 dB" in line for line in x.math)
    assert x.counterfactual and "10GBASE-LR" in x.counterfactual


def test_copper_requested_over_100m_raises_e1():
    with pytest.raises(PhysicalDistanceViolationError) as ei:
        _run(_link(100.01, media="copper"))
    assert ei.value.rule_id == "MEDIA.E1"
    assert ei.value.field == "links[0].requested_media"
    with pytest.raises(PhysicalDistanceViolationError):
        _run(_link(120, media="copper"))


def test_copper_requested_at_100m_passes():
    assert _run(_link(100, media="copper")).links[0].media == "Cat6a"


def test_inter_building_60m_is_fibre_refinement_x1():
    m, x = _pair(_run(_link(60, inter=True)))
    assert m.rule_id == "MEDIA.X1" and m.choice.startswith("OM4")
    assert x.choice == "10GBASE-SR"
    assert any(r.option.startswith("Cat6a") for r in m.rejected)
    assert m.spec_note and "MEDIA.R1" in m.spec_note and "Cat6a" in m.spec_note


def test_inter_building_overrides_copper_request_with_warning():
    m, _ = _pair(_run(_link(60, inter=True, media="copper")))
    assert m.rule_id == "MEDIA.X1"
    assert any("copper" in w for w in m.warnings)


def test_cat6_rejected_above_55m_x3():
    m, _ = _pair(_run(_link(80)))
    cat6 = next(r for r in m.rejected if r.option.startswith("Cat6 "))
    assert "55 m" in cat6.reason and "80 m" in cat6.reason


@pytest.mark.parametrize("d", [100.01, 250, 400])
def test_om4_rationale_says_modal_dispersion_not_attenuation_x4(d):
    m, x = _pair(_run(_link(d)))
    for dec in (m, x):
        assert "modal dispersion" in dec.rationale
        assert "attenuation" not in dec.rationale.lower()
    assert m.spec_note and "attenuation" in m.spec_note  # spec wording recorded, not used


def test_access_run_95m_warns_x2():
    plan = _run(_link(180, inter=True), access_run=95, aps=4)
    acc = next(d for d in plan.decisions if d.rule_id == "MEDIA.X2")
    assert any("95 m" in w and "90 m" in w for w in acc.warnings)
    assert "90 m" in acc.rationale and "10 m" in acc.rationale


def test_access_run_85m_no_warning():
    acc = next(d for d in _run(access_run=85).decisions if d.rule_id == "MEDIA.X2")
    assert acc.warnings == []


def test_access_run_over_100m_raises_e1():
    with pytest.raises(PhysicalDistanceViolationError) as ei:
        _run(access_run=101)
    assert ei.value.field == "sites[0].access_run_max_m"


def test_requested_om4_beyond_reach_falls_back_with_warning():
    m, x = _pair(_run(_link(500, media="om4")))
    assert m.choice.startswith("OS2")
    assert any("om4" in w.lower() and "400 m" in w for w in m.warnings)


def test_requested_os2_short_run_honoured():
    m, x = _pair(_run(_link(200, media="os2")))
    assert m.choice.startswith("OS2") and x.choice == "10GBASE-LR"
    assert m.spec_note and "requested" in m.spec_note


def test_run_is_pure_and_numbers_ids():
    base = NetworkPlan(requirements=load_preset("campus"))
    out = l1_media.run(base)
    assert base.decisions == [] and base.links == []
    ids = [d.id for d in out.decisions]
    assert ids == [f"L1-{n:02d}" for n in range(1, len(ids) + 1)]
    # campus: 3 links × (media + transceiver) + 3 access-cabling decisions
    assert len(ids) == 9
    assert [lk.optic for lk in out.links] == ["10GBASE-SR"] * 3


def test_requested_om4_short_intra_building_honoured_with_note():
    m, x = _pair(_run(_link(50, media="om4")))
    assert m.choice.startswith("OM4") and x.choice == "10GBASE-SR"
    assert "requested" in m.spec_note and "Cat6a" in m.spec_note


def test_required_gbps_above_catalogue_warns():
    link = _link(180)
    link["required_gbps"] = 40
    m, _ = _pair(_run(link))
    assert any("40 Gbps" in w for w in m.warnings)

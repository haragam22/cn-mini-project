"""P2: optical loss / power-budget math (technical.md §5.3)."""

import pytest

from netarch.engines import optics
from netarch.errors import OpticalBudgetExceededError

DB = 0.005  # "to 0.01 dB"


@pytest.fixture(scope="module")
def plant():
    return optics.load_plant()


@pytest.fixture(scope="module")
def cat():
    return optics.load_optics()


def test_constants_load_from_yaml(plant, cat):
    assert plant.alpha_db_per_km == {1310: 0.35, 1550: 0.25, 850: 3.0}
    assert (plant.connector_loss_db, plant.connectors_per_link) == (0.5, 2)
    assert (plant.splice_loss_db, plant.reel_km, plant.min_margin_db) == (0.1, 4, 1.0)
    assert cat["10GBASE-LR"].cil_db == 6.2 and cat["10GBASE-LR"].reach_m == 10000
    assert cat["10GBASE-ER"].cil_db == 11 and cat["10GBASE-ER"].reach_m == 40000
    assert cat["10GBASE-ZR"].cil_db == 23 and not cat["10GBASE-ZR"].ieee
    assert cat["10GBASE-SR"].reach_m == 400  # OM4 reach
    assert cat["10GBASE-T"].reach_m == 100


@pytest.mark.parametrize(
    ("km", "n"), [(0.5, 0), (4, 0), (4.01, 1), (8, 1), (10, 2), (15, 3), (22, 5), (35, 8), (81, 20)]
)
def test_splice_count(km, n):
    assert optics.splice_count(km, 4) == n


# technical.md §5.3 worked examples (Metro preset): loss parts, total, ER margin.
@pytest.mark.parametrize(
    ("distance_m", "fibre", "splices", "total", "er_margin"),
    [
        (15000, 3.75, 0.3, 5.05, 5.95),
        (22000, 5.50, 0.5, 7.00, 4.00),
        (35000, 8.75, 0.8, 10.55, 0.45),
    ],
)
def test_metro_worked_examples(plant, cat, distance_m, fibre, splices, total, er_margin):
    er = optics.evaluate(distance_m, cat["10GBASE-ER"], plant, plant.min_margin_db)
    assert er.loss.fibre_db == pytest.approx(fibre, abs=DB)
    assert er.loss.connector_db == pytest.approx(1.0, abs=DB)
    assert er.loss.splice_db == pytest.approx(splices, abs=DB)
    assert er.loss.total_db == pytest.approx(total, abs=DB)
    assert er.margin_db == pytest.approx(er_margin, abs=DB)
    lr = optics.evaluate(distance_m, cat["10GBASE-LR"], plant, plant.min_margin_db)
    assert not lr.reach_ok


def test_metro_35km_zr_margin(plant, cat):
    zr = optics.evaluate(35000, cat["10GBASE-ZR"], plant, plant.min_margin_db)
    assert zr.margin_db == pytest.approx(12.45, abs=DB)
    assert zr.meets_margin


def test_lr_10km_sanity_check(plant, cat):
    lr = optics.evaluate(10000, cat["10GBASE-LR"], plant, plant.min_margin_db)
    assert lr.loss.total_db == pytest.approx(4.7, abs=DB)
    assert lr.margin_db == pytest.approx(1.5, abs=DB)
    assert lr.reach_ok and lr.meets_margin


def test_lr_loss_at_22km_matches_idea_md(plant, cat):
    # idea.md §4: "at 1310 nm the loss would also be ≈ 9.2 dB"
    assert optics.evaluate(22000, cat["10GBASE-LR"], plant, 1.0).loss.total_db == pytest.approx(
        9.2, abs=DB
    )


@pytest.mark.parametrize(
    ("distance_m", "name", "margin"),
    [
        (10000, "10GBASE-LR", 1.5),
        (10010, "10GBASE-ER", None),
        (15000, "10GBASE-ER", 5.95),
        (22000, "10GBASE-ER", 4.00),
        (35000, "10GBASE-ZR", 12.45),
    ],
)
def test_selection_boundaries(distance_m, name, margin):
    sel = optics.select_os2_optic(distance_m)
    assert sel.chosen.optic.name == name
    assert not sel.fallback
    if margin is not None:
        assert sel.chosen.margin_db == pytest.approx(margin, abs=DB)


def test_short_os2_picks_cheapest_lr():
    assert optics.select_os2_optic(500).chosen.optic.name == "10GBASE-LR"


def test_80km_zr_is_a_fallback_with_thin_margin():
    # 80 km at 1550 nm: 20 + 1.0 + 19 × 0.1 = 22.9 dB → ZR margin 0.1 dB (≥ 0, < 1.0)
    sel = optics.select_os2_optic(80000)
    assert sel.chosen.optic.name == "10GBASE-ZR"
    assert sel.fallback
    assert sel.chosen.margin_db == pytest.approx(0.1, abs=DB)


def test_81km_raises_budget_error_with_shortfall():
    with pytest.raises(OpticalBudgetExceededError) as ei:
        optics.select_os2_optic(81000, field="links[0].distance_m")
    e = ei.value
    assert e.field == "links[0].distance_m"
    assert e.value == 81000
    assert e.rule_id == "MEDIA.R3"
    # ZR: loss 20.25 + 1.0 + 2.0 = 23.25 dB; + 1.0 margin − 23 dB budget = 1.25 dB short
    assert "1.25 dB" in e.message
    assert "81 km" in e.message
    assert e.hint


def test_min_margin_is_configurable():
    # With a 0 dB operating reserve, 35 km fits ER (0.45 dB margin).
    assert optics.select_os2_optic(35000, min_margin_db=0.0).chosen.optic.name == "10GBASE-ER"
    # With a 2 dB reserve, 10 km no longer fits LR (1.5 dB margin).
    assert optics.select_os2_optic(10000, min_margin_db=2.0).chosen.optic.name == "10GBASE-ER"


def test_loss_formula_text(plant, cat):
    text = optics.evaluate(22000, cat["10GBASE-ER"], plant, 1.0).loss.formula()
    assert text == (
        "loss = 22 km × 0.25 dB/km + 2 × 0.5 dB + 5 × 0.1 dB = 5.50 + 1.00 + 0.50 = 7.00 dB"
    )

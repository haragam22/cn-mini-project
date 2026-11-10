"""Optical loss and power-budget math (technical.md §5.3). Pure functions.

    link_loss_dB = L_km × α(λ) + n_conn × c_loss + n_splice × s_loss
    n_splice     = max(0, ceil(L_km / reel_km) − 1)
    margin_dB    = CIL_dB(optic) − link_loss_dB
    select: cheapest optic where L_km ≤ reach_km AND margin_dB ≥ min_margin_dB
    fallback: none meets min_margin but one has margin ≥ 0 → select it with a warning
    none fits → OpticalBudgetExceededError (states the shortfall in dB)

Every constant comes from ``netarch/data/{media,optics}.yaml``; nothing is hard-coded here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Any

import yaml

from netarch.errors import OpticalBudgetExceededError


@cache
def load_data(name: str) -> dict[str, Any]:
    """Parsed ``netarch/data/<name>`` (read-only constants, cached)."""
    return yaml.safe_load((files("netarch") / "data" / name).read_text(encoding="utf-8"))


def value(doc: dict[str, Any], dotted: str) -> Any:
    node: Any = doc
    for part in dotted.split("."):
        node = node[part]
    return node["value"]


@dataclass(frozen=True)
class Optic:
    name: str
    media: str
    wavelength_nm: int | None
    ieee: bool
    reach_m: float  # for SR: the OM4 reach
    cil_db: float | None  # channel insertion loss; None = reach-limited / copper
    cost_rank: int


@dataclass(frozen=True)
class Plant:
    alpha_db_per_km: dict[int, float]  # wavelength nm → attenuation
    connector_loss_db: float
    connectors_per_link: int
    splice_loss_db: float
    reel_km: float
    min_margin_db: float


def load_optics() -> dict[str, Optic]:
    out: dict[str, Optic] = {}
    for name, o in load_data("optics.yaml")["optics"].items():
        reach = o["reach_m"]["value"]
        if isinstance(reach, dict):
            reach = reach["OM4"]
        out[name] = Optic(
            name=name,
            media=o["media"],
            wavelength_nm=o["wavelength_nm"]["value"],
            ieee=bool(o["ieee"]),
            reach_m=reach,
            cil_db=o["channel_insertion_loss_db"]["value"],
            cost_rank=o["cost_rank"]["value"],
        )
    return out


def load_plant() -> Plant:
    m = load_data("media.yaml")
    alpha = {}
    for key, c in m["attenuation"].items():
        nm = int(key.split("_")[1].removesuffix("nm"))
        alpha[nm] = c["value"]
    return Plant(
        alpha_db_per_km=alpha,
        connector_loss_db=value(m, "connector.loss_db"),
        connectors_per_link=value(m, "connector.per_link"),
        splice_loss_db=value(m, "splice.loss_db"),
        reel_km=m["reel_length_km"]["value"],
        min_margin_db=m["min_operating_margin_db"]["value"],
    )


def km(distance_m: float) -> float:
    return float(Decimal(repr(distance_m)) / 1000)


def fmt_num(x: float) -> str:
    """Shortest exact text for an input number: 22 → '22', 10.01 → '10.01'."""
    return f"{x:.6f}".rstrip("0").rstrip(".")


def splice_count(length_km: float, reel_km: float) -> int:
    """n_splice = max(0, ceil(L / reel) − 1), in exact decimal arithmetic."""
    reels = math.ceil(Decimal(repr(length_km)) / Decimal(repr(reel_km)))
    return max(0, reels - 1)


@dataclass(frozen=True)
class Loss:
    length_km: float
    alpha_db_per_km: float
    fibre_db: float
    n_conn: int
    conn_loss_db: float
    connector_db: float
    n_splice: int
    splice_loss_db: float
    splice_db: float
    total_db: float

    def formula(self) -> str:
        return (
            f"loss = {fmt_num(self.length_km)} km × {fmt_num(self.alpha_db_per_km)} dB/km"
            f" + {self.n_conn} × {fmt_num(self.conn_loss_db)} dB"
            f" + {self.n_splice} × {fmt_num(self.splice_loss_db)} dB"
            f" = {self.fibre_db:.2f} + {self.connector_db:.2f} + {self.splice_db:.2f}"
            f" = {self.total_db:.2f} dB"
        )


def link_loss(
    length_km: float,
    alpha_db_per_km: float,
    *,
    n_conn: int,
    conn_loss_db: float,
    reel_km: float,
    splice_loss_db: float,
) -> Loss:
    n_splice = splice_count(length_km, reel_km)
    fibre = length_km * alpha_db_per_km
    conn = n_conn * conn_loss_db
    splice = n_splice * splice_loss_db
    return Loss(
        length_km=length_km,
        alpha_db_per_km=alpha_db_per_km,
        fibre_db=fibre,
        n_conn=n_conn,
        conn_loss_db=conn_loss_db,
        connector_db=conn,
        n_splice=n_splice,
        splice_loss_db=splice_loss_db,
        splice_db=splice,
        total_db=fibre + conn + splice,
    )


def optic_loss(distance_m: float, optic: Optic, plant: Plant) -> Loss:
    """Link loss at the optic's wavelength."""
    if optic.wavelength_nm is None:
        raise ValueError(f"{optic.name} is a copper PHY; it has no optical loss")
    return link_loss(
        km(distance_m),
        plant.alpha_db_per_km[optic.wavelength_nm],
        n_conn=plant.connectors_per_link,
        conn_loss_db=plant.connector_loss_db,
        reel_km=plant.reel_km,
        splice_loss_db=plant.splice_loss_db,
    )


@dataclass(frozen=True)
class Evaluation:
    optic: Optic
    loss: Loss
    margin_db: float
    reach_ok: bool
    meets_margin: bool  # reach ok AND margin ≥ min margin

    @property
    def fits(self) -> bool:
        """Usable at all (reach ok and margin ≥ 0)."""
        return self.reach_ok and self.margin_db >= 0


def evaluate(distance_m: float, optic: Optic, plant: Plant, min_margin_db: float) -> Evaluation:
    if optic.cil_db is None:
        raise ValueError(f"{optic.name} has no channel insertion loss budget")
    loss = optic_loss(distance_m, optic, plant)
    margin = optic.cil_db - loss.total_db
    reach_ok = distance_m <= optic.reach_m
    return Evaluation(optic, loss, margin, reach_ok, reach_ok and margin >= min_margin_db)


@dataclass(frozen=True)
class Selection:
    chosen: Evaluation
    evaluations: tuple[Evaluation, ...]  # every OS2 optic, cheapest first
    fallback: bool  # chosen margin < min margin (warning)
    min_margin_db: float


def os2_optics(optics: dict[str, Optic]) -> list[Optic]:
    smf = [o for o in optics.values() if o.media == "OS2" and o.cil_db is not None]
    return sorted(smf, key=lambda o: o.cost_rank)


def select_os2_optic(
    distance_m: float,
    *,
    plant: Plant | None = None,
    optics: dict[str, Optic] | None = None,
    min_margin_db: float | None = None,
    field: str = "distance_m",
) -> Selection:
    plant = plant or load_plant()
    optics = optics or load_optics()
    mm = plant.min_margin_db if min_margin_db is None else min_margin_db
    evals = tuple(evaluate(distance_m, o, plant, mm) for o in os2_optics(optics))
    for e in evals:
        if e.meets_margin:
            return Selection(e, evals, False, mm)
    for e in evals:
        if e.fits:
            return Selection(e, evals, True, mm)
    raise _budget_error(distance_m, evals, mm, field)


def _budget_error(
    distance_m: float, evals: tuple[Evaluation, ...], mm: float, field: str
) -> OpticalBudgetExceededError:
    best = max(evals, key=lambda e: e.margin_db)
    shortfall = best.loss.total_db + mm - (best.optic.cil_db or 0.0)
    reach = ", ".join(f"{e.optic.name} {fmt_num(km(e.optic.reach_m))} km" for e in evals)
    return OpticalBudgetExceededError(
        field=field,
        value=distance_m,
        rule_id="MEDIA.R3",
        message=(
            f"No 10G optic fits {fmt_num(km(distance_m))} km of OS2 fibre. Rated reach: {reach}. "
            f"Best budget {best.optic.name}: loss {best.loss.total_db:.2f} dB + "
            f"{fmt_num(mm)} dB operating margin vs {fmt_num(best.optic.cil_db or 0)} dB channel "
            f"insertion loss, shortfall {shortfall:.2f} dB."
        ),
        hint=(
            "Shorten the fibre path, add an intermediate site, or use a carrier/DWDM service "
            "for this span."
        ),
    )

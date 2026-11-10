"""Layer 1: media and transceiver per link (technical.md §5). Pure: plan in, plan out.

Baseline rules MEDIA.R1–R3 and E1 (§5.1) with refinements X1–X4 (§5.2). Media and transceiver
are separate Decisions (§5.4). The OS2 optic is chosen by power budget (``engines/optics.py``).
Engines fill Decision fields only; ``explain/render.py`` writes the prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from netarch.engines.optics import (
    Optic,
    Plant,
    Selection,
    fmt_num,
    km,
    load_data,
    load_optics,
    load_plant,
    select_os2_optic,
    value,
)
from netarch.errors import PhysicalDistanceViolationError
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.decisions import Decision, Rejected
from netarch.models.plan import NetworkPlan, PlanLink
from netarch.models.requirements import Link, Site

MEDIA_LABEL = {
    "Cat6a": "Cat6a UTP copper",
    "OM4": "OM4 multimode fibre",
    "OS2": "OS2 single-mode fibre",
}
MEDIA_OPTIC = {"Cat6a": "10GBASE-T", "OM4": "10GBASE-SR"}


@dataclass(frozen=True)
class Copper:
    channel_m: float
    permanent_m: float
    patch_m: float
    cat6_10g_m: float


def load_copper() -> Copper:
    m = load_data("media.yaml")
    return Copper(
        channel_m=value(m, "copper.channel_max_m"),
        permanent_m=value(m, "copper.permanent_link_max_m"),
        patch_m=value(m, "copper.patch_cords_max_m"),
        cat6_10g_m=value(m, "copper.cat6_10g_max_m"),
    )


def dist(d_m: float) -> str:
    """Distance as people say it: 180 m, 22 km, 10.01 km."""
    return f"{fmt_num(km(d_m))} km" if d_m >= 1000 else f"{fmt_num(d_m)} m"


@dataclass
class _Ctx:
    plant: Plant
    optics: dict[str, Optic]
    copper: Copper
    std: dict[str, str]
    min_margin_db: float | None
    decisions: list[Decision] = field(default_factory=list)
    next_n: int = 1

    def add(self, **fields) -> Decision:
        d = make_decision(id=decision_id("L1", self.next_n), **fields)
        self.next_n += 1
        self.decisions.append(d)
        return d


def run(plan: NetworkPlan, *, min_margin_db: float | None = None) -> NetworkPlan:
    """Media + transceiver decisions for every link, access cabling for every site."""
    req = plan.requirements
    ctx = _Ctx(
        plant=load_plant(),
        optics=load_optics(),
        copper=load_copper(),
        std=load_data("standards.yaml"),
        min_margin_db=min_margin_db,
        next_n=1 + sum(d.id.startswith("L1-") for d in plan.decisions),
    )
    links = [_design_link(ctx, i, link) for i, link in enumerate(req.links)]
    for i, site in enumerate(req.sites):
        _access_cabling(ctx, i, site)
    warnings = [f"{d.id}: {w}" for d in ctx.decisions for w in d.warnings]
    return plan.model_copy(update={
        "links": [*plan.links, *links],
        "decisions": [*plan.decisions, *ctx.decisions],
        "warnings": [*plan.warnings, *warnings],
    })


# --- per link ----------------------------------------------------------------------------


def _pick_media(link: Link, c: Copper, sr_reach: float) -> tuple[str, str, list[str], str | None]:
    """(media, rule_id, warnings, spec_note for requests)."""
    d, req = link.distance_m, link.requested_media
    warnings: list[str] = []
    note = None
    if req == "os2":
        if d <= sr_reach:
            note = ("requested_media=os2 honoured; the rules alone would not need single-mode "
                    f"at {dist(d)}.")
        return "OS2", "MEDIA.R3", warnings, note
    if req == "om4":
        if d <= sr_reach:
            if d <= c.channel_m and not link.inter_building:
                note = ("requested_media=om4 honoured; the rules alone would choose Cat6a at "
                        f"{dist(d)}.")
            return "OM4", "MEDIA.R2", warnings, note
        warnings.append(
            f"requested om4 ignored: 10GBASE-SR reach on OM4 is {dist(sr_reach)} < {dist(d)}."
        )
    if d <= c.channel_m:
        if link.inter_building:
            if req == "copper":
                warnings.append(
                    "requested copper overridden: inter-building runs use fibre (MEDIA.X1)."
                )
            return "OM4", "MEDIA.X1", warnings, note
        return "Cat6a", "MEDIA.R1", warnings, note
    if d <= sr_reach:
        return "OM4", "MEDIA.R2", warnings, note
    return "OS2", "MEDIA.R3", warnings, note


def _design_link(ctx: _Ctx, i: int, link: Link) -> PlanLink:
    c, optics = ctx.copper, ctx.optics
    d = link.distance_m
    if link.requested_media == "copper" and d > c.channel_m:
        raise PhysicalDistanceViolationError.for_link(
            link.a, link.b, d, field=f"links[{i}].requested_media"
        )
    sr = optics["10GBASE-SR"]
    media, rule, warnings, req_note = _pick_media(link, c, sr.reach_m)
    selection = None
    if media == "OS2":
        selection = select_os2_optic(
            d, plant=ctx.plant, optics=optics, min_margin_db=ctx.min_margin_db,
            field=f"links[{i}].distance_m",
        )
        optic = selection.chosen.optic
    else:
        optic = optics[MEDIA_OPTIC[media]]
    subject = f"Link {link.a} ↔ {link.b}"
    inputs = {
        "distance_m": d,
        "required_gbps": link.required_gbps,
        "inter_building": link.inter_building,
        "requested_media": link.requested_media,
    }
    if link.required_gbps > 10:
        warnings.append(
            f"required {fmt_num(link.required_gbps)} Gbps exceeds the 10G optics catalogue; "
            "plan parallel links or a higher-speed optic."
        )
    _media_decision(ctx, subject, media, rule, inputs, warnings, req_note, optic, link)
    _xcvr_decision(ctx, subject, media, rule, inputs, optic, selection, d)
    return PlanLink(a=link.a, b=link.b, media=media, optic=optic.name)


def _media_decision(ctx, subject, media, rule, inputs, warnings, req_note, optic, link) -> None:
    c, std, optics = ctx.copper, ctx.std, ctx.optics
    d = link.distance_m
    sr = optics["10GBASE-SR"]
    math: list[str] = []
    rej: list[Rejected] = []
    notes: list[str] = []
    if media == "Cat6a":
        math.append(
            f"{dist(d)} ≤ {dist(c.channel_m)} channel = {fmt_num(c.permanent_m)} m permanent link"
            f" + {fmt_num(c.patch_m)} m patch cords"
        )
        rej.append(_cat6_rejection(c, d))
        rej.append(rejected(
            "OM4 + 10GBASE-SR",
            f"fibre optics at both ends cost more (rank {sr.cost_rank} vs "
            f"{optics['10GBASE-T'].cost_rank}); copper already covers {dist(d)}",
        ))
        cf = (f"Would select OM4 + 10GBASE-SR if the run exceeded {dist(c.channel_m)} or "
              "joined two buildings.")
        standards = [std["ieee_802_3an"], std["tia_568_2_d"]]
    else:
        if d > c.channel_m:
            rej.append(rejected(
                "Cat6a + 10GBASE-T",
                f"{dist(d)} > {dist(c.channel_m)} copper channel limit (IEEE 802.3an)",
            ))
        else:
            rej.append(rejected(
                "Cat6a + 10GBASE-T",
                "inter-building run: copper between buildings is exposed to ground-potential "
                "difference, lightning and EMI",
            ))
            notes.append(
                f"Spec baseline MEDIA.R1 would choose Cat6a / 10GBASE-T for {dist(d)}; refined "
                "to fibre because the link joins two buildings (MEDIA.X1)."
            )
        standards = [std["ieee_802_3ae"], std["tia_568_3_d"]]
        if media == "OM4":
            if rule == "MEDIA.X1":
                math.append(f"{dist(d)} ≤ {dist(c.channel_m)} but inter_building = yes → fibre")
            else:
                math.append(
                    f"{dist(c.channel_m)} < {dist(d)} ≤ {dist(sr.reach_m)} "
                    "10GBASE-SR reach on OM4"
                )
            lr = optics["10GBASE-LR"]
            rej.append(rejected(
                "OS2 + 10GBASE-LR",
                f"single-mode optic costs more (rank {lr.cost_rank} vs {sr.cost_rank}); "
                f"OM4 already covers {dist(d)}",
            ))
            notes.append(
                "The spec calls 400 m the 'attenuation limit of OM4'. The real limit of "
                "10GBASE-SR over OM4 is modal dispersion (bandwidth-distance product), so the "
                "rationale states that cause (MEDIA.X4)."
            )
            cf = (f"Would select Cat6a + 10GBASE-T at ≤ {dist(c.channel_m)} inside one "
                  f"building, and OS2 single-mode above {dist(sr.reach_m)}.")
        else:  # OS2
            if d > sr.reach_m:
                math.append(f"{dist(d)} > {dist(sr.reach_m)} 10GBASE-SR reach on OM4")
                rej.append(rejected(
                    "OM4 + 10GBASE-SR",
                    f"{dist(d)} > {dist(sr.reach_m)} reach, a modal dispersion "
                    "(bandwidth-distance) limit at 850 nm",
                ))
            else:
                math.append(f"{dist(d)} ≤ {dist(sr.reach_m)}, single-mode by request")
                rej.append(rejected("OM4 + 10GBASE-SR", "single-mode explicitly requested"))
            math.append(f"optic {optic.name} chosen by power budget (see transceiver decision)")
            cf = f"Would select OM4 + 10GBASE-SR at ≤ {dist(sr.reach_m)}."
    if req_note:
        notes.append(req_note)
    ctx.add(
        domain="media", subject=subject, choice=MEDIA_LABEL[media], rule_id=rule,
        inputs=inputs, math=math, standards=standards, rejected=rej, counterfactual=cf,
        warnings=warnings, spec_note=" ".join(notes) or None,
    )


def _cat6_rejection(c: Copper, d: float) -> Rejected:
    if d > c.cat6_10g_m:
        reason = f"10GBASE-T on Cat6 is limited to {dist(c.cat6_10g_m)} < {dist(d)} (MEDIA.X3)"
    else:
        reason = (f"10GBASE-T on Cat6 is limited to {dist(c.cat6_10g_m)}; Cat6a keeps the full "
                  f"{dist(c.channel_m)} channel at 10G (MEDIA.X3)")
    return rejected("Cat6 + 10GBASE-T", reason)


def _xcvr_decision(ctx, subject, media, rule, inputs, optic, selection, d) -> None:
    std, optics = ctx.std, ctx.optics
    rej: list[Rejected] = []
    warnings: list[str] = []
    math: list[str] = []
    xin = {k: inputs[k] for k in ("distance_m", "required_gbps")}
    if media == "Cat6a":
        math.append(f"{dist(d)} ≤ {dist(optic.reach_m)} 10GBASE-T reach")
        for o in ("10GBASE-SR", "10GBASE-LR"):
            rej.append(rejected(o, f"fibre optic (needs {optics[o].media}); the medium is Cat6a"))
        cf = "Would select 10GBASE-SR if the medium were OM4 fibre."
        standards = [std["ieee_802_3an"]]
    elif media == "OM4":
        math.append(f"{dist(d)} ≤ {dist(optic.reach_m)} 10GBASE-SR reach on OM4")
        rej.append(rejected("10GBASE-T", "copper PHY; needs Cat6a, the medium is OM4 fibre"))
        rej.append(rejected(
            "10GBASE-LR", "1310 nm single-mode optic; it is not specified for OM4 multimode"
        ))
        cf = f"Would select an OS2 optic (10GBASE-LR or longer) above {dist(optic.reach_m)}."
        standards = [std["ieee_802_3ae"]]
    else:
        assert selection is not None
        xin["min_margin_db"] = selection.min_margin_db
        math, rej, warnings, cf = _budget_fields(selection, optics, d)
        standards = [std["ieee_802_3ae"] if optic.ieee else std["vendor_zr"], std["tia_568_3_d"]]
    ctx.add(
        domain="transceiver", subject=subject, choice=optic.name, rule_id=rule, inputs=xin,
        math=math, standards=standards, rejected=rej, counterfactual=cf, warnings=warnings,
    )


def _budget_fields(sel: Selection, optics: dict[str, Optic], d: float):
    mm = sel.min_margin_db
    chosen = sel.chosen
    math: list[str] = []
    rej = [
        rejected("10GBASE-T", f"copper PHY, {dist(optics['10GBASE-T'].reach_m)} reach"),
        rejected("10GBASE-SR", f"multimode optic, {dist(optics['10GBASE-SR'].reach_m)} reach on "
                               "OM4 (modal dispersion)"),
    ]
    warnings: list[str] = []
    for e in sel.evaluations:
        o = e.optic
        cil = fmt_num(o.cil_db or 0)
        ok = "≥" if e.margin_db >= mm else "<"
        math.append(f"{o.name} @ {o.wavelength_nm} nm: {e.loss.formula()}")
        math.append(
            f"{o.name} margin = {cil} − {e.loss.total_db:.2f} = {e.margin_db:.2f} dB {ok} "
            f"{fmt_num(mm)} dB; reach {dist(o.reach_m)} {'≥' if e.reach_ok else '<'} {dist(d)}"
        )
        if e is chosen:
            continue
        if not e.reach_ok:
            reason = (f"rated reach {dist(o.reach_m)} < {dist(d)}; loss at {o.wavelength_nm} nm "
                      f"would be {e.loss.total_db:.2f} dB vs {cil} dB budget")
        elif not e.meets_margin and o.cost_rank < chosen.optic.cost_rank:
            reason = (f"margin {e.margin_db:.2f} dB < {fmt_num(mm)} dB minimum operating margin "
                      f"(loss {e.loss.total_db:.2f} dB vs {cil} dB budget)")
            if e.fits:
                warnings.append(
                    f"{o.name} would work with only {e.margin_db:.2f} dB to spare "
                    f"(< {fmt_num(mm)} dB operating margin)."
                )
        else:
            reason = (f"also fits (margin {e.margin_db:.2f} dB) but costs more "
                      f"(rank {o.cost_rank} > {chosen.optic.cost_rank})")
            if not o.ieee:
                reason += "; non-IEEE vendor optic"
        rej.append(rejected(o.name, reason))
    if not chosen.optic.ieee:
        warnings.insert(0, f"{chosen.optic.name} is a non-IEEE vendor optic: both ends need "
                           "matching vendor optics and interoperability is not guaranteed.")
    if sel.fallback:
        warnings.append(
            f"{chosen.optic.name} margin {chosen.margin_db:.2f} dB is below the {fmt_num(mm)} dB "
            "operating margin; no optic meets it, so the link has little reserve for ageing "
            "and repairs."
        )
    cheaper = [e for e in sel.evaluations if e.optic.cost_rank < chosen.optic.cost_rank]
    if cheaper:
        o = cheaper[-1].optic
        cf = (f"Would select {o.name} if distance ≤ {dist(o.reach_m)} and loss ≤ "
              f"{(o.cil_db or 0) - mm:.2f} dB ({fmt_num(o.cil_db or 0)} dB budget − "
              f"{fmt_num(mm)} dB margin).")
    else:
        dearer = [e for e in sel.evaluations if e.optic.cost_rank > chosen.optic.cost_rank]
        nxt = dearer[0].optic.name if dearer else "no 10G optic"
        cf = (f"Would select {nxt} if distance > {dist(chosen.optic.reach_m)} or the loss rose "
              f"above {(chosen.optic.cil_db or 0) - mm:.2f} dB.")
    return math, rej, warnings, cf


# --- access cabling ---------------------------------------------------------------------


def _access_cabling(ctx: _Ctx, i: int, site: Site) -> None:
    run_m = site.access_run_max_m
    if run_m is None:
        return
    c, std = ctx.copper, ctx.std
    if run_m > c.channel_m:
        raise PhysicalDistanceViolationError(
            field=f"sites[{i}].access_run_max_m",
            value=run_m,
            rule_id="MEDIA.E1",
            message=(
                f"Access run at {site.id} is {fmt_num(run_m)} m. Copper to endpoints is limited "
                f"to a {fmt_num(c.channel_m)} m channel (IEEE 802.3an, TIA-568.2-D)."
            ),
            hint="Add a telecom room (IDF) with an access switch closer to the endpoints.",
        )
    warnings = []
    if run_m > c.permanent_m:
        warnings.append(
            f"longest access run {fmt_num(run_m)} m exceeds the {fmt_num(c.permanent_m)} m "
            f"permanent link; only {fmt_num(c.channel_m - run_m)} m left for patch cords "
            f"(channel {fmt_num(c.channel_m)} m)."
        )
    rej = [_cat6_rejection(c, run_m)]
    fibre_reason = "endpoints have copper RJ45 ports"
    if site.access_points:
        fibre_reason += f" and fibre carries no PoE for the {site.access_points} APs"
    rej.append(rejected("OM4 fibre to the desk", fibre_reason))
    standards = [std["tia_568_2_d"], std["ieee_802_3an"]]
    if site.access_points:
        standards.append(std["ieee_802_3at"])
    ctx.add(
        domain="media",
        subject=f"Access cabling at {site.id}",
        choice=MEDIA_LABEL["Cat6a"],
        rule_id="MEDIA.X2",
        inputs={"access_run_max_m": run_m, "access_points": site.access_points},
        math=[
            f"channel {fmt_num(c.channel_m)} m = {fmt_num(c.permanent_m)} m permanent link + "
            f"{fmt_num(c.patch_m)} m patch cords",
            f"longest run {fmt_num(run_m)} m ≤ {fmt_num(c.channel_m)} m channel",
        ],
        standards=standards,
        rejected=rej,
        counterfactual=(f"Runs over {fmt_num(c.channel_m)} m would need a closer telecom room "
                        "or fibre to a remote access switch."),
        warnings=warnings,
    )

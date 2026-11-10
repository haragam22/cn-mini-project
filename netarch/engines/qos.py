"""Latency budget and LLQ (technical.md §8.5). Pure: plan in, plan out."""

from __future__ import annotations

from netarch.engines.optics import load_data, value
from netarch.engines.ptcaps import pt_result
from netarch.explain.builder import decision_id, make_decision, rejected
from netarch.models.plan import NetworkPlan, QosPolicy


def latency_ms(distance_m: float) -> dict[str, float]:
    """§8.5 terms for one EVPL: propagation, serialisation, processing, total."""
    d = load_data("design.yaml")
    hops = value(d, "latency_hops")
    prop = distance_m / 1000 * value(d, "fibre_ms_per_km")
    ser = value(d, "frame_bytes") * 8 / value(d, "lab_link_bps") * 1000 * hops
    proc = hops * value(d, "per_hop_ms")
    return {"propagation": prop, "serialisation": ser, "processing": proc,
            "total": prop + ser + proc}


def _r(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def run(plan: NetworkPlan) -> NetworkPlan:
    req = plan.requirements
    target = req.latency_target_ms
    if target is None or not req.links:
        return plan
    std = load_data("standards.yaml")
    d = load_data("design.yaml")
    worst = max(req.links, key=lambda lk: lk.distance_m)
    t = latency_ms(worst.distance_m)
    budget = target - t["total"]
    trading = [(s.id, g.vlan) for s in req.sites for g in s.segments if g.role == "trading"]
    routers = [x for x in plan.devices if x.role == "router" and x.site in {s for s, _ in trading}]
    pct = value(d, "llq_priority_percent")
    devices = {x.hostname: x for x in plan.devices}
    policies: list[QosPolicy] = []
    for r in plan.devices:
        if r.role != "router":
            continue
        wan = next((i for i in r.interfaces if i.description.startswith("EVPL handoff")), None)
        if wan is None:
            continue
        trade_ifs = [i.name for i in r.interfaces
                     if i.kind == "sub" and (r.site, i.vlan) in set(trading)]
        policies.append(QosPolicy(name="WAN-EDGE", device=r.hostname, details={
            "kind": "llq", "class": "TRADING", "dscp": "ef", "priority_percent": pct,
            "interface": wan.name, "direction": "output"}))
        names = ["WAN-EDGE"]
        if trade_ifs:
            policies.append(QosPolicy(name="MARK-TRADING", device=r.hostname, details={
                "kind": "marking", "dscp": "ef", "interfaces": trade_ifs,
                "direction": "input"}))
            names.append("MARK-TRADING")
        ifs = [i.model_copy(update={"policy_out": "WAN-EDGE"}) if i.name == wan.name else
               i.model_copy(update={"policy_in": "MARK-TRADING"}) if i.name in trade_ifs else i
               for i in r.interfaces]
        devices[r.hostname] = r.model_copy(update={"interfaces": ifs, "qos": names})
    mqc = pt_result("mqc_llq")
    warnings = []
    if budget <= 0:
        warnings.append(f"the {target} ms target is exceeded before any queuing "
                        f"({_r(t['total'])} ms on the longest link).")
    if req.target_dialect == "pt" and mqc != "accepted":
        warnings.append(f"pt dialect omits the QoS block (PT matrix mqc_llq={mqc}); the full "
                        "dialect keeps it.")
    dec = make_decision(
        id=decision_id("QOS", 1 + sum(x.id.startswith("QOS-") for x in plan.decisions)),
        domain="qos", subject=f"Latency target {target} ms",
        choice=(f"LLQ: DSCP EF (trading) in a {pct}% priority queue on every WAN edge"
                if policies else "no QoS policy (no router WAN edge)"),
        rule_id="QOS.LAT",
        inputs={"latency_target_ms": target, "worst_link": f"{worst.a}↔{worst.b}",
                "distance_m": worst.distance_m, "trading_segments": len(trading),
                "routers_with_trading": len(routers)},
        math=[f"propagation = {worst.distance_m / 1000:g} km × "
              f"{value(d, 'fibre_ms_per_km')} = {_r(t['propagation'])} ms",
              f"serialisation = {value(d, 'frame_bytes')} B × 8 / "
              f"{value(d, 'lab_link_bps') / 1e9:g} Gbps × {value(d, 'latency_hops')} hops = "
              f"{_r(t['serialisation'])} ms",
              f"processing = {value(d, 'latency_hops')} × {value(d, 'per_hop_ms')} ms "
              f"(assumption) = {_r(t['processing'])} ms",
              f"total = {_r(t['total'])} ms ≈ {t['total']:.2f} ms",
              f"queuing budget = {target} − {_r(t['total'])} = {_r(budget)} ms"],
        standards=[std["rfc_3246"], std["rfc_2474"]],
        rejected=[rejected("best effort only", "queuing is the only term that can break the "
                           "target; a burst of bulk traffic would delay trading packets"),
                  rejected("more bandwidth", "does not bound queuing delay under bursts")],
        counterfactual="Without a latency target no QoS policy is generated.",
        warnings=warnings,
    )
    return plan.model_copy(update={
        "devices": list(devices.values()), "qos_policies": [*plan.qos_policies, *policies],
        "decisions": [*plan.decisions, dec],
        "warnings": [*plan.warnings, *(f"{dec.id}: {w}" for w in warnings)],
    })

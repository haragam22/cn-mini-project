# Code flow
> **Planned — no code yet.** Written from technical.md §2–3 and §10. Update each section as phases land; replace planned paths with real `file:function` references.

## Entry points
- `netarch/cli.py` — Typer app. No args → launches the Textual TUI (`netarch/tui/app.py`). Subcommands: `presets`, `validate`, `design`, `explain`, `plan`, `export`, `verify`, `checklist` (technical.md §10.1).
- Exit codes: 0 ok · 1 verification failed · 2 input invalid · 3 design constraint error.

## Pipeline (each stage a pure function: plan in, plan out)
1. **Input** — preset (`data/presets/*.json`) or custom JSON → validated by `models/requirements.py` (pydantic). All errors collected and reported with field/value/rule/hint (`errors.py`).
2. **L1** — `engines/optics.py` (loss/power budget math) + `engines/l1_media.py` (media + transceiver per link).
3. **Topology & L2** — `engines/topology.py` (tier), `engines/l2_switching.py` (VLANs, trunks, native 999, RSTP root, capacity checks).
4. **Addressing** — `engines/vlsm.py` (bitwise hierarchical allocator, summarisation, efficiency).
5. **L3+** — `engines/routing.py`, `engines/vpn.py`, `engines/qos.py`, `engines/security.py`; `configgen/interface_map.py` maps links to real port names.
6. **Plan** — `models/plan.py` NetworkPlan + `models/decisions.py` Decision records (rationale, standards, rejected alternatives, counterfactuals).
7. **Config generation** — `configgen/render.py` + Jinja templates, `full` and `pt` dialects.
8. **Verification** — `verify/selfcheck.py` (11 invariants, always), `verify/batfish_runner.py` (optional, Docker), `verify/checklist.py` (Packet Tracer steps).
9. **Export** — `export/writer.py`: per-device `.txt`, ZIP, `rationale.md`, `ip-plan.csv`, `plan.json`, `topology.mmd`, `secrets.txt`.

```
preset/JSON → validate → L1 → topology/L2 → VLSM → routing/VPN/QoS/ACL → NetworkPlan+Decisions
                                                                              ├→ configs (full|pt) → self-check / Batfish / PT checklist
                                                                              └→ exports
```

## Explainability
`explain/builder.py` builds Decision records inside each engine; `explain/render.py` turns them into text/Markdown for CLI, TUI and `rationale.md`.

## External services
- Batfish (Docker, localhost) via pybatfish — optional; 3 s connect timeout, graceful skip in the app.
- Packet Tracer — manual, user-operated; the tool only generates configs and checklists for it.

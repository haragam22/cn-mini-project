# Testing guide
> Commands become runnable once P0 creates the package and venv. Phases add detail here as they land.

## Automated
- **Gate suite** (what the Stop-hook runs): `.venv/Scripts/python -m pytest -q -m "not batfish"` — unit, property (hypothesis), golden files (syrupy), integration.
- **Coverage**: `.venv/Scripts/python -m pytest -q -m "not batfish" --cov=netarch --cov-report=term-missing` — targets ≥ 90 % `engines/`, ≥ 80 % overall, ≥ 95 % `vlsm.py` (P3).
- **Batfish suite** (needs Docker): start Batfish (exact command recorded in P0 / README), then `.venv/Scripts/python -m pytest -q -m batfish`. Required for the P6 gate.
- **Golden snapshots**: regenerate with `--snapshot-update` only when a config change is intended; review the diff.

## Your manual checks
Items tagged `(manual)` in implementation.md. Tick them in implementation.md when done, then set the phase Status to `done`.

### P0
- [ ] Fill the PT capability matrix (technical.md §12) in Packet Tracer on 2911 / 3560-24PS / 2960-24TT → `data/pt_capabilities.yaml`, no ☐ left.
- [ ] Run the Textual demo in Windows Terminal: tabs and table render.
- [ ] Create the GitHub repo `netarchitect`, push, confirm visibility and that it clones.

### P5
- [ ] Paste one generated config per role (router, L3 switch, L2 switch) into PT: zero `% Invalid input`.

### P7
- [ ] `netarch` in Windows Terminal at 120 × 35: no clipped panels.

### P8
- [ ] Build each preset in PT from the cabling table, load `pt` configs, run the checklist; save `.pkt` + screenshots under `verification/`.
- [ ] Global PT subset passes; note what is Batfish-only.
- [ ] Write `ai_audit_log.md` entries (≥ 2, target 4) from `audit/raw/`, with PT packet-flow before/after evidence.

### P9
- [ ] Record the 3–5 min demo (idea.md §9), upload unlisted, link in README; screenshots render on GitHub.
- [ ] Tag `v1.0.0`, GitHub release with the 3 ZIPs; tick the submission checklist (§11).

## Manual (live) testing
Per-feature walkthroughs (CLI commands with expected output, TUI flows) are added by each phase.

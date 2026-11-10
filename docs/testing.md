# Testing guide
> Commands become runnable once P0 creates the package and venv. Phases add detail here as they land.

## Automated
- **Gate suite** (what the Stop-hook runs): `.venv/Scripts/python -m pytest -q -m "not batfish"` — unit, property (hypothesis), golden files (syrupy), integration.
- **Coverage**: `.venv/Scripts/python -m pytest -q -m "not batfish" --cov=netarch --cov-report=term-missing` — targets ≥ 90 % `engines/`, ≥ 80 % overall, ≥ 95 % `vlsm.py` (P3).
- **Batfish suite** (needs Docker): start Batfish (exact command recorded in P0 / README), then `.venv/Scripts/python -m pytest -q -m batfish`. Required for the P6 gate.
- **Golden snapshots**: regenerate with `--snapshot-update` only when a config change is intended; review the diff.
- **Lint**: `.venv/Scripts/python -m ruff check .`
- **P0 suites**: `tests/test_smoke.py` (imports, `netarch --help`), `tests/test_data_constants.py` (every optics/media constant has a `source`, values = technical.md §5.3), `tests/test_pt_capabilities.py` (matrix rows = technical.md §12), `tests/test_textual_spike.py` (headless pilot), `tests/test_batfish_spike.py` (batfish marker; snapshot `tests/fixtures/batfish_spike/`: initIssues 0 errors, OSPF ESTABLISHED, traceroute permit/deny).

- **P2 suites**: `tests/test_optics.py` (splice count, §5.3 Metro worked examples to 0.01 dB, LR 10 km 1.5 dB, selection boundaries, 80 km fallback, 81 km `OpticalBudgetExceededError`), `tests/test_l1_media.py` (100/100.01/400/400.01 m, 10/10.01 km, Metro 15/22/35 km, E1, X1–X4), `tests/test_topology.py` (link counts, tier boundaries), `tests/test_l2_switching.py` (VLANs, trunk lists, native 999, RSTP root, capacity/PoE/density, `CapacityError`), `tests/test_explain_p2.py` (every decision complete and backed by its inputs, no OM4 "attenuation", renderers, `netarch explain`).
- **P3 suite**: `tests/test_vlsm.py` — wildcard/mask every prefix 0–32 vs `ipaddress`, host ranges incl. /31 /32, gateway rule 253 → /24 / 254 → /23, exact growth, exact fit vs +1 (shortfall 256), §7.6 message text, /30 root, reserved skipping + fragmentation, unsorted = sorted, free list vs `summarize_address_range`, hypothesis 1,800 examples (68–73 % allocate, ≥ 1,000; rest check shortfall), presets (summary = block and exact, rows vs oracle, reserved/VPC untouched, loopbacks, decisions, metrics), /31 vs /30 from the PT matrix, CLI exit 3. Coverage: `--cov=netarch.engines.vlsm` → 100 %. Branch mix: add `--hypothesis-show-statistics -k properties`.
- **P4 suite**: `tests/test_design_p4.py` — plan completeness (models, IP/mask in subnet, link media/optic/ports, OSPF per router, unique router-IDs, JSON round-trip), routing rules per preset (Campus RT.R1, Metro RT.R1 + failover costs 10/100 + timers 1/4, Global RT.R2/R3/R4 + area ranges + BGP/Null0/prefix-list), §8.5 latency 0.175/0.024/0.10 → 0.30 ms and 4.701 ms budget, no port twice / every port exists on its model, CapacityError, IOS-safe hostnames, tunnels mirror, crypto per dialect, every ACL ends with deny and is attached, policy contents, warnings (cloud ignored, IoT without collectors, no MGMT).
- **P5/P6 suite**: `tests/test_configgen_verify.py` — hygiene on 3 presets × 2 dialects (no `allowed vlan all`, native 1, mask in OSPF network, `enable password`; 2960 never `encapsulation dot1q`), 3560 encapsulation before mode trunk, skeleton order, PT-COMPAT header vs full, PT matrix accepted switches features on, profile-name injection, golden snapshots (`tests/__snapshots__/`, regenerate with `--snapshot-update` only for intended changes), export artefacts + ZIP (no secrets inside) + `--only`, CSV formula-injection guard, checklist, self-check all PASS 3 × 2, mutations hit C1–C11, Batfish skip/snapshot layout; `test_batfish_full_configs` is `@pytest.mark.batfish`.
- **P7 suite**: `tests/test_cli_tui.py` — every command and exit code via CliRunner (0/1/2/3, `--debug`), TUI headless at 120 × 35: preset → decisions → verify → export, broken JSON errors by field, what-if 95 → 105 → 450 → 12,000 → 36,000 m (Cat6a → OM4 → LR → ER → ZR), config viewer, keys.
- **Try it**: `.venv/Scripts/netarch` (TUI), `netarch verify --preset global`, `netarch export --preset metro --out ./output --zip`, `netarch explain --preset campus --domain addressing` (P3), `.venv/Scripts/netarch explain --preset campus` (also `--preset metro --id L1-04` for the 35 km ZR case, `--domain switching`, `--markdown`).

## Your manual checks
Items tagged `(manual)` in implementation.md. Tick them in implementation.md when done, then set the phase Status to `done`.

### P0
- [ ] Fill the PT capability matrix — step-by-step: docs/pt-matrix-guide.md (technical.md §12) in Packet Tracer on 2911 / 3560-24PS / 2960-24TT → `netarch/data/pt_capabilities.yaml`: set each row's `result` to `accepted` / `rejected` / `alternative` (with the accepted syntax in `alternative:`), none left `untested`.
- [ ] Run the Textual demo in Windows Terminal: `.venv/Scripts/python spikes/textual_demo.py` — two tabs (Optics, About), a 3-column table, "Add row" adds a row; Ctrl+Q quits.
- [x] Start Batfish (README command), run `.venv/Scripts/python -m pytest -q -m batfish`, and record the exact Docker command/ports that worked in README.
- [ ] Create the GitHub repo `netarchitect`, push, confirm visibility and that it clones.

### P6
- [ ] Start Docker Desktop + Batfish (README command), then `.venv/Scripts/python -m pytest -q -m batfish` — runs the P0 spike **and** `test_batfish_full_configs` on all 3 presets (full dialect). Not yet run on P4+ configs.

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

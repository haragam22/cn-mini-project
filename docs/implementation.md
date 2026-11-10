# NetArchitect — Implementation Plan

> Companion docs: [`idea.md`](idea.md) · [`technical.md`](technical.md)
> **Team:** solo · **Start:** 23 Oct 2026 · **Hard deadline:** 10 Nov 2026 · **Planned finish:** 9 Nov (1 day buffer)

## How to read this plan

- The work is split into **10 phases (P0–P9)** plus **2 continuous tracks** that run the whole time.
- Every phase has **prerequisites** (what must be true before starting), **tasks**, **deliverables**, and a **gate**: objective, checkable conditions. **A phase is not done until its gate passes.** Dates are targets; gates are rules.
- If a gate fails, fix it before moving on. Building on an unverified engine is how late-stage rewrites happen.
- §12 has the **cut line**: what to drop, in order, if the schedule slips.

## Timeline at a glance

| Phase | Name | Target dates | Rubric areas fed |
|---|---|---|---|
| P0 | Setup and risk spikes | 23–24 Oct | all (de-risking) |
| P1 | Input layer, models, presets | 25–26 Oct | 1 (15 pts) |
| P2 | L1/L2 engines and explain framework | 27–28 Oct | 2 (25 pts) |
| P3 | VLSM subnet engine | 29–31 Oct | 3, 4 |
| P4 | Routing, VPN, QoS, ACL design | 1–2 Nov | 2, 3 |
| P5 | Config generator (full + pt dialects) | 2–4 Nov | 3 (25 pts) |
| P6 | Verification layer | 4–5 Nov | 3, 5 |
| P7 | CLI and TUI | 5–7 Nov | presentation, 1 |
| P8 | Lab validation and audit evidence | 7–8 Nov | 5 (20 pts), deliverables |
| P9 | Docs, demo video, release | 9 Nov | deliverables |
| — | Buffer and submit | 10 Nov | — |
| T1 | **AI audit log** (continuous) | 23 Oct → 8 Nov | 5 (20 pts) |
| T2 | **Tests alongside code** (continuous) | 25 Oct → 9 Nov | 4 (15 pts) |

```
Oct 23 24 25 26 27 28 29 30 31 Nov 1  2  3  4  5  6  7  8  9  10
P0  ■■■■■
P1        ■■■■■
P2              ■■■■■
P3                    ■■■■■■■■
P4                             ■■■■■
P5                                ■■■■■■■■
P6                                      ■■■■■
P7                                         ■■■■■■■■
P8                                                  ■■■■■
P9                                                        ■■
T1  ═══════════════════════════════════════════════════════
T2        ═════════════════════════════════════════════════════
```

---

## Continuous tracks

### T1 — AI audit log (`ai_audit_log.md`)

**Why continuous:** the 20 points need *real* AI mistakes with evidence. They only exist if you capture them as they happen. Reconstructing them on 8 Nov is how logs end up fake.

**Practice:**
1. Whenever AI writes networking logic (masks, VLSM, trunks, OSPF, optics, IPsec), save the **verbatim prompt** and the **raw output** to `audit/raw/<date>-<topic>.md` before changing anything.
2. When you find a flaw, open an entry using the template below.
3. Deliberately prompt AI for the risky areas (list below) so genuine mistakes surface early.

**Entry template:**

```markdown
## AUDIT-0X: <one-line title>
- Date / tool / model:
- Area: (VLSM | trunking | OSPF | optics | IPsec | ACL | QoS)
### Prompt (verbatim)
### AI output (buggy code, verbatim)
### Symptom
### Diagnosis (networking theory: why it is wrong)
### Evidence
  - Unit test that fails: `tests/...::test_...`
  - Batfish: question + output excerpt
  - Packet Tracer: simulation-mode packet flow (screenshots: before / after)
### Fix (code diff)
### Regression test added
### Lesson
```

**Hunting list:** gateway off-by-one in host math · unsorted VLSM → misaligned subnet · `mask` vs `wildcard` in OSPF `network` · `~mask` without `& 0xFFFFFFFF` in Python (negative numbers) · trunk with no `allowed vlan` (all VLANs leak) · native VLAN 1 · missing `encapsulation dot1q` on 3560 · LR chosen for > 10 km · "OM4 attenuation" wording · OSPF over policy-based IPsec · missing MSS clamp on tunnels · ACL placed far from source / missing final deny.

**Track gate (checked at P8):** ≥ 2 complete entries (spec minimum), **target 4**, each with a failing test or Batfish result **and** a PT packet-flow before/after.

### T2 — Tests alongside code

Every engine function lands with its tests in the same commit. CI-style local command: `pytest -q --cov=netarch`. A phase gate that says "tests pass" means **all** tests, not just the new ones.

---

## P0 — Setup and risk spikes · 23–24 Oct

**Status**: manual

**Goal:** prove the three risky external dependencies work **before** writing engine code: Batfish, Packet Tracer command support, Textual on your terminal.

**Prerequisites**
- Packet Tracer 8.x installed on your laptop
- Docker Desktop installed (WSL2 backend)
- Python 3.11, git, GitHub account

**Tasks**
1. Create the GitHub repo `netarchitect`. Add the folder layout from technical.md §2, `pyproject.toml` with pinned versions, `.gitignore` (`output/`, `secrets.txt`, `.venv/`), MIT license, placeholder README.
2. Add the three docs to `docs/`.
3. **Batfish spike:** run the Batfish container. Hand-write two tiny IOS configs (two routers, one OSPF link, one ACL). Load them with pybatfish and run `initIssues`, `ospfSessionCompatibility`, `traceroute`. Record the exact Docker command, ports and pybatfish version that worked.
4. **PT capability spike:** fill in technical.md §12. Paste each feature into a scratch PT file on 2911 / 3560-24PS / 2960-24TT, and record accepted, rejected or alternative syntax in `data/pt_capabilities.yaml`. This decides /31 vs /30, IPsec algorithms, and QoS in the `pt` dialect.
5. **Optics constants:** confirm the ⚠ values in technical.md §5.3 against IEEE 802.3 Clause 52 tables / Cisco transceiver datasheet; write `data/optics.yaml` and `data/media.yaml` with a `source:` field per value.
6. **Textual spike:** a 20-line app with tabs + DataTable + button running in Windows Terminal.
7. Start T1: create `ai_audit_log.md` with the template and `audit/raw/`.

**Deliverables:** repo pushed; `pt_capabilities.yaml` complete; `optics.yaml` sourced; working Batfish command in README draft; Textual hello app.

**Done when** (gate P0):
- [x] `pybatfish` answers `initIssues` on the sample snapshot with **0 errors**, and `ospfSessionCompatibility` shows the session **established**.
- [ ] (manual) Every row in the PT capability matrix has a result (no ☐ left).
- [x] Every optics constant has a source citation.
- [ ] (manual) Textual demo renders tabs and a table in Windows Terminal.
- [ ] (manual) Repo is public/private as intended and cloneable.

**If the gate fails:** Batfish won't run → fix Docker/WSL now (the plan depends on it); worst case, keep Batfish as optional and rely on the self-check. PT rejects IPsec on 2911 → fall back to GRE-only in the `pt` dialect and document it.

---

## P1 — Input layer, models, presets · 25–26 Oct

**Status**: done

**Goal:** every input the tool will ever see is typed, validated, and produces precise errors.

**Prerequisites:** P0 gate passed.

**Tasks**
1. `models/requirements.py`: pydantic schema per technical.md §4.1, including cross-field validators (link endpoints exist, unique VLANs, dual_homed paths, overlap checks).
2. `errors.py`: full hierarchy (technical.md §13) with `field / value / rule_id / message / hint`.
3. `models/decisions.py` (Decision, Rejected) and `models/plan.py` (NetworkPlan). Built now because every engine writes into them.
4. Presets `campus.json`, `metro.json`, `global.json` with concrete numbers:
   - **Campus:** 3 buildings; A↔B 180 m, B↔C 320 m, A↔C 390 m, all inter-building; ~1,600 endpoints across STAFF/WIFI/LABS/SERVERS/MGMT; APs per building; root 10.0.0.0/16.
   - **Metro:** HQ, Remote-1 (22 km), Remote-2 (35 km), Colo (15 km); 450 users; TRADING VLAN; dual_homed; latency target 5 ms.
   - **Global:** 4 cities (one is HQ) + cloud VPC 172.31.0.0/16; 2,000 IoT spread across cities; IoT/USERS/SERVERS/MGMT per city.
5. `explain/builder.py` helpers and `explain/render.py` skeleton (fields → sentence).

**Deliverables:** models, errors, 3 presets, render skeleton, tests.

**Done when** (gate P1):
- [x] All 3 presets load and validate with **zero** errors.
- [x] ≥ 15 invalid-input tests, each asserting the **specific** error class and field (bad CIDR, host bits set, VLAN 1, VLAN 1003, duplicate VLAN, unknown link endpoint, negative distance, copper > 100 m → `PhysicalDistanceViolationError`, VPC overlap → `AddressOverlapError`, dual_homed with one link → `TopologyConstraintError`, …).
- [x] An input with 3 separate mistakes reports **all 3**.
- [x] `pytest` green.

---

## P2 — L1/L2 engines and explain framework · 27–28 Oct

**Status**: done

**Goal:** media, transceiver, topology tier and switching decisions, each a complete Decision record.

**Prerequisites:** P1 gate passed; `optics.yaml` sourced (P0).

**Tasks**
1. `engines/optics.py`: loss and power-budget math (technical.md §5.3), pure functions.
2. `engines/l1_media.py`: rules MEDIA.R1–R3, E1, X1–X4; separate media and transceiver decisions; rejected alternatives and counterfactuals.
3. `engines/topology.py`: TOP.R1–R3 with link-count math.
4. `engines/l2_switching.py`: VLAN set, trunk allowed lists, native 999, RSTP root placement, port/PoE/density checks (`CapacityError`).
5. `explain/render.py`: finish text and Markdown renderers; spec notes appear where we refine the spec.

**Done when** (gate P2):
- [x] Boundary tests pass: 100 / 100.01 / 400 / 400.01 m; 10 km → LR (1.5 dB margin) and 10.01 km → ER; Metro 15 / 22 / 35 km produce ER / ER / ZR + warning; 81 km → `OpticalBudgetExceededError`.
- [x] The three Metro worked examples in technical.md §5.3 are reproduced **to 0.01 dB** by tests.
- [x] Every decision has a non-empty rationale, ≥ 1 standard, rejected alternatives where alternatives exist, and the input numbers appear in the text (test asserts this).
- [x] No OM4 rationale contains the word "attenuation" as the limit cause (test).
- [x] `netarch explain --preset campus` (quick temporary script is fine) prints readable decisions for all links.

---

## P3 — VLSM subnet engine · 29–31 Oct

**Status**: done (2026-11-10; independent phase-reviewer PASS)

**Goal:** a provably correct bitwise allocator. This is the single most-tested component.

**Prerequisites:** P1 gate passed (segment and site models exist).

**Tasks**
1. `engines/vlsm.py` primitives (technical.md §7.1) using integer bit operations only.
2. Sizing rule with gateway + growth (§7.2), /31 or /30 per PT matrix, /32 loopbacks.
3. Hierarchical allocator (§7.3) with deterministic ordering, infra block, `AddressSpaceExhaustedError` with shortfall and smallest fitting root.
4. Summarisation + exactness check (§7.4).
5. Efficiency metrics (§7.5). Addressing Decisions (per site block, plus sizing rule explanation).
6. Hypothesis property suite vs the `ipaddress` oracle.

**Done when** (gate P3):
- [x] Wildcard tests for **every** prefix 0–32 match `ipaddress` `hostmask`.
- [x] Hypothesis: **≥ 1,000 examples** with no overlap, all aligned, all inside root, all usable ≥ needed.
- [x] Exhaustion: exact fit passes; +1 address raises with the **correct** shortfall number.
- [x] 253 hosts → /24 and 254 → /23 (gateway rule) tested.
- [x] For all 3 presets: each site's summary equals its block, and the summary contains no other site's address.
- [x] Coverage of `vlsm.py` ≥ 95 %.

---

## P4 — Routing, VPN, QoS, ACL design · 1–2 Nov

**Status**: done (2026-11-10; independent phase-reviewer PASS)

**Goal:** complete the NetworkPlan: every device, interface, IP, process, tunnel, policy and decision, before any config text exists.

**Prerequisites:** P2 and P3 gates passed.

**Tasks**
1. `engines/routing.py`: RT.R1–R4; subnet count shown in rationale; router-IDs from loopbacks; areas; reference bandwidth; passive defaults; Metro timers and costs for dual-homed failover; Global ABR ranges; eBGP to cloud with Null0 anchor and filtered redistribution.
2. `engines/vpn.py`: GRE-over-IPsec tunnel pairs, tunnel subnets, MTU/MSS, PSK generation.
3. `engines/qos.py`: latency budget (§8.5) as a Decision; LLQ policy for Metro.
4. `engines/security.py`: policy matrix → ACL entries placed near the source; VTY access-class.
5. `configgen/interface_map.py`: logical links → PT port names per `devices.yaml`.

**Done when** (gate P4):
- [x] `plan.json` for each preset contains: every device with model, every interface with IP/mask, every link with media + optic + ports, routing per device, tunnels (Global), ACLs, QoS (Metro).
- [x] Routing decisions: Campus → single-area OSPF, Metro → single-area OSPF + failover, Global → multi-area + eBGP + GRE-over-IPsec, each with rationale and rejected options.
- [x] Metro latency decision reproduces technical.md §8.5 (≈ 0.30 ms, 4.7 ms queuing budget).
- [x] No port is used twice on any device (test); every port exists on its model (test).

---

## P5 — Config generator · 2–4 Nov

**Status**: manual (2026-11-10; automated items verified, PT paste spot check is yours)

**Goal:** copy-paste-ready IOS for every device, in both dialects.

**Prerequisites:** P4 gate passed; `pt_capabilities.yaml` complete (P0).

**Tasks**
1. Jinja templates: `router.j2`, `l3switch.j2`, `l2switch.j2` + partials (base, ssh, vlans, stp, interfaces, ospf, bgp, crypto, qos, acl), in the order given by technical.md §9.3.
2. `configgen/render.py`: `full` and `pt` dialects; `! NETARCH-PT-COMPAT:` header listing every downgrade.
3. `export/writer.py`: per-device `.txt`, ZIP, `rationale.md`, `ip-plan.csv`, `plan.json`, `topology.mmd`, `secrets.txt`.
4. Golden-file (syrupy) snapshots for 3 presets × 2 dialects.

**Done when** (gate P5):
- [x] `netarch export` (temporary script fine) writes all artefacts for all 3 presets.
- [ ] (manual) Spot check: one device per role pasted into PT with **zero** "% Invalid input" lines.
- [x] No config contains `allowed vlan all`, native VLAN 1, a subnet mask inside an OSPF `network` statement, or a clear-text `enable password` (tests).
- [x] Golden snapshots committed; regenerating produces no diff.

---

## P6 — Verification layer · 4–5 Nov

**Status**: todo (2026-11-10; self-check + mutations verified; Batfish searchFilters/traceroutes/failover fork not written, never run — Docker was off)

**Goal:** the tool proves its own output is correct.

**Prerequisites:** P5 gate passed; Batfish spike working (P0).

**Tasks**
1. `verify/selfcheck.py`: the 11 invariants in technical.md §11.1.
2. `verify/batfish_runner.py`: snapshot builder (configs + host JSON), questions and assertions from §11.2, Metro failover fork, 3-second connection timeout and graceful skip, `batfish-report.md`.
3. `verify/checklist.py`: PT checklist (§11.3) with cabling table, load steps, commands and expected results.
4. Mark Batfish tests `@pytest.mark.batfish`.

**Done when** (gate P6):
- [x] Self-check: **all PASS** on 3 presets × 2 dialects.
- [x] Mutation test: deliberately corrupt a config (duplicate IP, missing VLAN on trunk, wrong wildcard) → self-check **FAILS** with the right check id each time.
- [ ] Batfish on all 3 presets (`full`): 0 parse errors, 0 undefined refs, 0 duplicate IPs, all OSPF/BGP/IPsec sessions up, summaries present, policy traceroutes match the matrix, Metro failover path moves via Colo.
- [x] With Docker stopped: `verify` completes, reports Batfish skipped, exit code reflects only the self-check.

---

## P7 — CLI and TUI · 5–7 Nov

**Status**: manual (2026-11-10; automated items verified, Windows Terminal 120 × 35 check is yours)

**Goal:** a polished, interactive terminal app in which the whole workflow runs without touching code.

**Prerequisites:** P6 gate passed (the TUI only displays what engines and verifiers already produce).

**Tasks**
1. `cli.py`: all Typer commands and exit codes (technical.md §10.1); Rich error panels; `--debug`.
2. TUI screens (§10.2): Home → Requirements (form + inline validation) → Design tabs (Summary, Decisions tree, IP Plan, Topology, Configs) → Verify → Export.
3. What-if: distance edits re-run L1 live (§10.3).
4. Export screen: checkboxes, dialect toggle, destination path, **Export** and **ZIP all**, list of written paths.
5. Stylesheet: consistent colours; PASS/FAIL always written as words, not just colour.

**Done when** (gate P7):
- [x] From `netarch` with no args: pick each preset → view decisions → verify → export `.txt` files → **without leaving the TUI**.
- [x] Load a broken custom JSON: errors appear beside the right fields; the app doesn't crash.
- [x] Distance what-if 95 → 105 → 450 → 12,000 → 36,000 m updates the decision live.
- [x] Every CLI command works and returns the documented exit code (tests via Typer's `CliRunner`).
- [ ] (manual) Runs in Windows Terminal at 120 × 35 without clipped panels.

---

## P8 — Lab validation and audit evidence · 7–8 Nov

**Status**: todo

**Goal:** the spec's verification deliverable plus the evidence behind the AI audit.

**Prerequisites:** P7 gate passed; T1 has ≥ 2 raw candidates.

**Tasks**
1. For each preset: build the PT topology from the generated cabling table, load the `pt` configs, run the checklist, and save `verification/<profile>/<profile>.pkt`, the exported configs, and screenshots of key `show` outputs and pings.
2. **Global:** load the PT-compatible subset (multi-area OSPF, GRE, IPsec, eBGP to `cloud-vgw` as far as the matrix allows). Document what is verified in PT vs only in Batfish.
3. For each audit entry: reproduce the AI bug in PT simulation mode (e.g., buggy trunk lets the guest VLAN reach MGMT, or a wrong wildcard leaves an OSPF neighbor missing), capture before/after packet flow, and attach the Batfish result.
4. Finalise `ai_audit_log.md`.

**Done when** (gate P8):
- [ ] (manual) 3 `.pkt` files + 3 exported config sets committed under `verification/` (**spec deliverable**).
- [ ] (manual) Every checklist command for Campus and Metro produces the expected result; Global's PT subset passes and the rest is covered by the Batfish report.
- [ ] (manual) `ai_audit_log.md`: ≥ 2 complete entries (target 4), each with prompt, buggy code, diagnosis, **PT packet-flow evidence**, fix and regression test.

---

## P8.5 — User simulation (≥ 1,000 users) and security hardening · 9 Nov

**Status**: todo

Built with the `user-sim` skill (workflow module added 2026-10-24). Simulate ≥ 1,000 users against the finished product; failures become reproducing tests and fixes; then clear the security backlog and run the security-breaker on the full project.

**Done when**:
- [ ] `sim/` harness simulates ≥ 1,000 seeded users with the documented input mix (`sim/users.md`).
- [ ] Pass bar met (user-sim skill reference; overrides in decisions.md): 0 crashes/hangs/unhandled exceptions, valid-input error rate < 1 %, 100 % of invalid inputs rejected with the documented error, p95 within the target stated in decisions.md.
- [ ] Every failure cluster has a reproducing test and a root-cause fix; `docs/user-sim-report.md` written.
- [ ] `docs/security/backlog.md` cleared (fixed with tests, or risk accepted by the user).
- [ ] security-breaker full-project run: 0 open critical/high findings.

---

## P9 — Docs, demo video, release · 9 Nov

**Status**: todo

**Goal:** a repo a stranger can clone, run and understand in 5 minutes.

**Prerequisites:** P8 gate passed.

**Tasks**
1. **README.md:** title + one-line pitch → **YouTube demo link (thumbnail)** → 4–6 screenshots (Home, Decisions tree, IP Plan, Verify results, Export, PT topology) → features → quickstart (install, Batfish Docker command, `netarch`) → architecture diagram → rubric mapping table → docs links → limitations → AI usage note.
2. **Demo video (3–5 min, unlisted on YouTube):** follow idea.md §9. Record at 1080p with a large terminal font.
3. Fresh-clone test on a clean folder/venv: install → `pytest` → `netarch` works.
4. Tag `v1.0.0`; GitHub release with the 3 ZIP exports attached.

**Done when** (gate P9):
- [ ] Fresh clone: install + tests + TUI work by following only the README.
- [ ] (manual) README video link plays; all screenshots render on GitHub.
- [ ] (manual) Submission checklist (§11) fully ticked.

---

## 10 Nov — Buffer and submit

Use only for fixes. **No new features.** Submit early in the day.

---

## 11. Submission checklist (spec §6)

- [ ] **Source repository:** clean codebase, CLI/TUI, explainability engine, `pytest` suite
- [ ] **`ai_audit_log.md`:** prompt, buggy AI code, technical analysis, final fix (≥ 2 entries)
- [ ] **Verification exports:** 3 config sets from the 3 presets, loaded into Packet Tracer (`verification/`)
- [ ] README with screenshots + YouTube demo link
- [ ] `pytest -q` green on a fresh clone; coverage reported
- [ ] No secrets committed (`secrets.txt` ignored)

---

## 12. Cut line (if the schedule slips, drop from the bottom up)

| Priority | Item | Rubric impact if cut |
|---|---|---|
| **Must** | P1–P6 core engines, configs, self-check, tests, 3 presets | everything depends on these |
| **Must** | `ai_audit_log.md` with 2 evidenced entries | 20 pts |
| **Must** | PT verification of 3 presets | spec deliverable |
| **Must** | Typer CLI with exports | interface requirement |
| Should | Batfish suite (beyond the P0 spike) | strengthens 3 and 5 |
| Should | Textual TUI | presentation / demo quality |
| Should | `full` vs `pt` dialect split | correctness of Global/QoS |
| Could | What-if live distance editing | demo polish |
| Could | Mermaid topology export | nice to have |
| Could | Audit entries 3–4 | above minimum |

If you cut the TUI, the Typer CLI with Rich tables still satisfies "CLI interface", and the demo video uses CLI commands.

---

## 13. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Batfish/Docker won't run on the laptop | Med | High | Found in P0; self-check covers correctness; saved report for demo |
| PT rejects needed syntax (IPsec, QoS, /31) | High | Med | P0 capability matrix → `pt` dialect downgrades, documented |
| VLSM subtle bug discovered late | Med | High | P3 property tests vs oracle before anything depends on it |
| TUI eats too much time | High | Med | Built last (P7); CLI fallback in cut line |
| AI audit entries thin or fabricated | Med | High (20 pts) | T1 continuous capture from day one |
| Global profile too big for PT | Med | Med | PT subset + Batfish for the rest, stated explicitly |
| Solo bandwidth / other coursework | High | High | Gates over dates; 1-day buffer; cut line |

---

## 14. Definition of done (whole project)

1. All phase gates P0–P9 ticked.
2. `pytest -q` green; coverage ≥ 80 % overall, ≥ 90 % on `engines/`.
3. `netarch verify --preset {campus,metro,global}` → self-check PASS; Batfish PASS (or explicitly skipped with a saved report).
4. Every decision in every preset has rationale + standard + rejected alternatives.
5. Spec deliverables (§11) present; README demo link live.

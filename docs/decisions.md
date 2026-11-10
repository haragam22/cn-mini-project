# Decisions
Append-only. Newest at bottom.

## 2026-10-22 — Batfish tests are excluded from the test gate
- **Context**: Workflow setup. technical.md §14.1 skips `@pytest.mark.batfish` tests when Docker is down; the workflow's test gate rejects any skipped test.
- **Decision**: The gate runs `pytest -m "not batfish"` (Batfish tests are deselected, not skipped). The Batfish suite runs separately with Docker up (docs/testing.md); the phase-reviewer checks its result for P6 gate items.
- **Why**: Keeps the gate deterministic and offline while still requiring the Batfish assertions where the plan's gates name them.
- **Alternatives**: Require Docker + Batfish for every gate run (rejected: slow, makes every unrelated change depend on Docker).

## 2026-10-22 — Human-only gate items use a `manual` phase status
- **Context**: Gates in P0, P5, P7, P8, P9 include Packet Tracer, visual, video and GitHub checks that automation can't perform.
- **Decision**: Those items are tagged `(manual)`. A phase whose automatable items are all verified gets Status `manual`; its manual checks are listed in docs/testing.md. Later phases continue unless they need the manual result, in which case the build stops with a question. The user sets `done` after doing the checks.
- **Why**: Lets automated work proceed (e.g. P1–P2 don't depend on the PT matrix) without pretending manual gates passed.
- **Alternatives**: Stop at every phase with a manual item (rejected: P0's PT matrix would block all work).

## 2026-10-22 — Automated builds capture their own caught mistakes for T1
- **Context**: T1 needs genuine AI mistakes with evidence.
- **Decision**: When generated networking code fails a test or the reviewer and is fixed, the prompt, buggy code, failing output and fix go to `audit/raw/`. The user selects and writes the final `ai_audit_log.md` entries and adds Packet Tracer evidence.
- **Why**: Real mistakes are captured as they happen (T1's own rule), and the graded write-up stays the user's.
- **Alternatives**: User-only T1 (rejected by user).

## 2026-10-23 — Python 3.12 instead of 3.11
- **Context**: technical.md §1 plans 3.11 and asks P0 to verify pybatfish supports the chosen minor. 3.11 is not installed on the dev machine (3.10, 3.12, 3.14 are).
- **Decision**: Use CPython 3.12 (`requires-python = ">=3.12,<3.13"`). The full stack installed and imported on 3.12.10; pybatfish 2026.9.17.3748 declares Requires-Python >=3.10 and classifiers 3.10–3.14.
- **Why**: Installed, supported by every stack package, no extra install needed. 3.12 keeps the stdlib `ipaddress` oracle unchanged.
- **Alternatives**: Install 3.11 (extra setup, no benefit); 3.14 (newest, higher risk of wheel gaps in the Textual/pydantic chain).

## 2026-10-23 — Exact dependency pins (P0)
- **Decision**: pydantic 2.14.1, typer 0.27.3, rich 15.0.0, textual 8.2.8, Jinja2 3.1.6, ciscoconfparse2 0.9.18, pybatfish 2026.9.17.3748, PyYAML 6.0.3; dev: pytest 9.1.1, hypothesis 6.152.7, pytest-cov 7.1.0, syrupy 6.1.1, ruff 0.17.2. Build backend: setuptools (pip's default; package data `netarch/data/*.yaml`).
- **Why**: technical.md §1 says versions are pinned in P0; these are the versions that actually installed and imported on 3.12.
- **Alternatives**: Ranges (rejected: plan asks for pinned versions); hatchling (another build tool, no benefit).

## 2026-10-23 — PyYAML as the YAML loader
- **Context**: technical.md §2 specifies `data/*.yaml` constant files but names no YAML library.
- **Decision**: PyYAML (`yaml.safe_load` only).
- **Why**: A loader is required by the specified file format; PyYAML is already a transitive dependency of both pybatfish and ciscoconfparse2, so pinning it adds no new package.
- **Alternatives**: ruamel.yaml (round-trip editing not needed); JSON data files (contradicts §2).

## 2026-10-23 — Data files live in `netarch/data/`
- **Context**: implementation.md P0 says `data/optics.yaml`; technical.md §2 places `data/` inside the `netarch/` package.
- **Decision**: Follow §2: `netarch/data/{media,optics,pt_capabilities}.yaml`, shipped as package data.
- **Why**: §2 is the layout source of truth; package data keeps the constants loadable after `pip install`.
- **Alternatives**: Top-level `data/` (not importable as package data).

## 2026-10-23 — Constant file shape: every value carries its own `source`
- **Decision**: In `media.yaml`/`optics.yaml` each constant is `{value, unit, source}`. Where an authoritative source differs from the technical.md working value, the working value is kept and the difference is written into `source` and raised as a question.
- **Why**: P0 gate "every optics constant has a source citation" becomes mechanically testable (`tests/test_data_constants.py`); design numbers change only by the user's call.
- **Alternatives**: One `source` per optic row (weaker: cannot tell which number a citation covers).

## 2026-10-23 — PT capability matrix starts as `result: untested`
- **Decision**: `pt_capabilities.yaml` holds every technical.md §12 row with `expected` and `result: untested`; allowed results are `untested | accepted | rejected | alternative` (+ `alternative:` syntax, `notes:`).
- **Why**: Results come only from pasting into Packet Tracer (manual gate item); nothing is invented.
- **Alternatives**: Pre-filling expected values as results (rejected: fabricated evidence).

## 2026-10-23 — P1: validation API reports every failure as a typed error
- **Decision**: `collect_errors(data) -> list[NetArchError]` runs pydantic field rules, then cross-field checks over the raw input (so they still run when an unrelated field is broken). `load_requirements` raises the single error itself when there is one, else `InputValidationError` whose `.errors` lists all (each keeps its own class: `PhysicalDistanceViolationError`, `AddressOverlapError`, ...). Field paths look like `sites[0].segments[1].vlan`. Pydantic errors map to `rule_id = INPUT.<pydantic type>`.
- **Why**: §4.1 requires all failures at once, and gate P1 asserts a specific class + field per error.
- **Alternatives**: one pydantic `model_validator` (stops cross-field checks when any field fails); always raise an aggregate (loses the specific class for single errors).

## 2026-10-23 — P1: schema vocabularies and small rules not spelled out in §4.1
- **Decision**: `profile_type` ∈ campus/metro/global; `kind` ∈ building/hq/remote/colo/city; `role` ∈ users/wireless/management/servers/labs/iot/trading; `resiliency` ∈ dual_uplink/dual_homed; `target_dialect` ∈ pt/full (default pt); `requested_media` ∈ copper/om4/os2/null; `cloud = {vpc_cidr}`. Unknown fields are rejected (`extra="forbid"`). `access_points` defaults 0, `access_run_max_m` optional, `inter_building` defaults false. Numbers are strict (no "300" strings, no 2.5 hosts). A link from a site to itself is rejected. "Remote site" for dual_homed = `kind: remote`.
- **Overlap reading of §4.1**: reserved and VPC ranges must be strict CIDRs inside RFC 1918 (else `AddressOverlapError`, rule ADDR.RFC1918 — the error class §4.1 names for that row); reserved ranges must not overlap each other; the VPC must not overlap the root or any reserved range. Reserved ranges may sit inside the root (the §4.1 example does). Overlap against actual allocations is P3's job.
- **Why**: values taken from the §4.1 example, §6–§8 and the three presets; typos must not be dropped silently.
- **Alternatives**: free-form strings (no validation); a separate error class for non-RFC 1918 (not in §13).

## 2026-10-23 — P1: CIDR parsing is integer math in `models/requirements.py`
- **Decision**: `parse_ipv4/parse_cidr/overlaps/contains/in_rfc1918` use bit math; `ipaddress` is used only in tests (hypothesis oracle).
- **Why**: CLAUDE.md rule (`ipaddress` is a test oracle only). P3's VLSM primitives may reuse or move these.
- **Alternatives**: `ipaddress` in production code (forbidden by the project rule).

## 2026-10-23 — P1: preset numbers the plan leaves open (provisional, see QUESTIONS in P1 report)
- **Campus**: bldg-a STAFF 200 / WIFI 220 / SERVERS 40 / MGMT 20; bldg-b STAFF 180 / WIFI 200 / LABS 120 / MGMT 20; bldg-c STAFF 220 / WIFI 240 / LABS 100 / MGMT 20 (= 1,580 ≈ 1,600). VLANs STAFF 10, WIFI 20, LABS 30, SERVERS 40, MGMT 99. APs 8/8/10 (≤ 30 clients per AP, under the 40 density constant). Access runs 85/80/90 m. growth 20 % (MGMT 0 %).
- **Metro**: root 10.0.0.0/16; HQ STAFF 250 + TRADING 60 + SERVERS 30 + MGMT 10; remote-1 STAFF 80; remote-2 STAFF 60 (users 250+60+80+60 = 450); colo TRADING 20 (servers) + MGMT 10. TRADING VLAN 50. Backup links remote-1↔colo 20 km, remote-2↔colo 30 km (not given by the plan). All links 10 Gbps.
- **Global**: root 10.0.0.0/16; sites delhi (kind hq), mumbai, bangalore, singapore (kind city); IoT 500 per city (= 2,000), USERS 200/100, SERVERS 40/10, MGMT 10; VLANs USERS 10, SERVERS 40, IOT 60, MGMT 99. `links: []` because inter-city paths are GRE-over-IPsec over the Internet (§8.3) and real city distances exceed the 120 km `distance_m` cap.
- **Why**: the plan gives totals only; these splits satisfy them and stay well inside a /16.
- **Alternatives**: user-supplied splits (asked in the P1 report).

## 2026-10-23 — `pt` dialect behaviour is data-driven from the PT capability matrix
- **Context**: /31 vs /30 (P3), IPsec hash/DH group (P4/P5) and QoS MQC support (P5) depend on Packet Tracer results the user fills in `netarch/data/pt_capabilities.yaml`.
- **Decision**: Engines and templates read the matrix at run time. Any row still `untested` uses the conservative fallback: /30 point-to-point links, `hash sha` + DH group 5 + `esp-sha-hmac`, QoS block omitted in `pt` (listed in the `! NETARCH-PT-COMPAT:` header). Filling the matrix changes output without code changes.
- **Why**: P3–P5 can be built and tested before the manual PT work; the final output still follows real PT results.
- **Alternatives**: Block P3–P5 until the matrix is filled (rejected by user).

## 2026-10-23 — Project-wide workflow answers (user)
- QoS per-hop processing 0.05 ms (§8.5) accepted as an assumption; stated as such in the rationale.
- Batfish container is started automatically by any phase or run that needs it (Docker Desktop must be open).
- If the independent phase-reviewer agent is blocked, the orchestrator reviews inline and labels the verdict "not independent" in the report.
- Build continues attended in the session phase by phase; the user commits via `/quiz` at milestones (scheduler keeps skipping dirty repos).
- The cut line (implementation.md §12) is never applied automatically; ask first.
- Build all automatable work through P9 in one go, pausing only for genuinely new questions.
- GitHub repo `haragam22/cn-mini-project`: private now, public at P9 before submission. User pushes.
- Global preset uses real city names: HQ Delhi; Mumbai, Bangalore, Singapore. Campus total 1,580 kept.

## 2026-10-23 — P2: constants added to `netarch/data/` (all value/unit/source)
- **Decision**: `media.yaml` gains `copper.*` (100 m channel, 90 m permanent link, 10 m patch, Cat6 10G 55 m — technical.md §5.1/§5.2). New `devices.yaml` (2960-24TT 24 access + 2 uplink ports, 3560-24PS ports — §9.1; 30 W per AP — §6.3/802.3at; 40 clients/AP — §6.3), `topology.yaml` (TOP thresholds 500 / 4 / 3 / 5,000 and native VLAN 999 — §6.1/§6.2), `standards.yaml` (§15 citation strings, file named in §2). `tests/test_data_constants.py` covers the new files.
- **Why**: §2 says constants live in data files, never in code; every number stays traceable to technical.md.
- **Alternatives**: constants in engine modules (contradicts §2).

## 2026-10-23 — P2: L1 engine details technical.md leaves open (provisional, see P2 report questions)
- **Decision**: `requested_media`: `os2` always honoured (LR/ER/ZR by budget, spec_note when ≤ 400 m); `om4` honoured within 400 m, beyond it ignored with a warning and the rules apply; `copper` > 100 m → `PhysicalDistanceViolationError` (MEDIA.E1, field `links[i].requested_media`, same as P1); inter-building copper ≤ 100 m is overridden to OM4 by MEDIA.X1 with a warning. `access_run_max_m` > 100 m → `PhysicalDistanceViolationError` (MEDIA.E1, field `sites[i].access_run_max_m`). `required_gbps` > 10 → warning (catalogue is 10G only). Budget fallback picks the cheapest optic with reach ok and margin ≥ 0; the budget error's shortfall = loss + min margin − CIL of the optic with the best margin. One MEDIA.X2 access-cabling Decision per site that has `access_run_max_m`.
- **Why**: §5 defines the distance rules but not these input combinations; idea.md says the inter-building flag "forces fibre".
- **Alternatives**: raise on every conflicting request (blocks valid designs); silently ignore requests (violates "never silent").

## 2026-10-23 — P2: topology tier details (provisional)
- **Decision**: distribution blocks = number of sites; endpoints = sum of segment `hosts` (growth excluded). 1 block with > 500 and ≤ 5,000 endpoints (a gap between TOP.R1 and TOP.R2) → TOP.R2 single block. Hub = the `kind: hq` site, else the first site. Topology decisions cite IEEE 802.1w (routed inter-building links keep each RSTP domain inside one building) because §15 lists no topology standard. Fewer input links than the chosen pattern needs → warning, not error.
- **Why**: §6.1 gives the rules and link math only.
- **Alternatives**: treat the gap as R1 (one switch block for > 500 endpoints) or R3 (dedicated core for one building).

## 2026-10-23 — P2: L2 switching details (provisional)
- **Decision**: rule ids `L2.VLAN`, `L2.TRUNK`, `L2.RSTP`, `L2.CAP` (§6 names none); four Decisions per site. Trunk allowed list = the site's segment VLANs exactly; native 999 is not in the allowed list. Wired endpoints = hosts of roles users/servers/labs/trading/iot (wireless clients use APs; MGMT addresses belong to network devices); growth included per segment as ceil(hosts × (1 + growth_pct/100)) (updated 2026-10-24, see below). Access switch = 24 access + 2 uplink ports (2960-24TT, §9.1), both uplinks used, so n = ceil((wired + APs) / 24) satisfies §6.3's `wired + APs + uplinks ≤ ports × switches`. PoE demand = APs × 30 W is always reported and drives a physical 802.3at (PoE+) recommendation plus the lab-mapping limitation (updated 2026-10-24, see below); it is additionally checked (`CapacityError`) when a budget is supplied (`run(plan, poe_budget_w=...)`). Results go to `plan.segments` and Decision `inputs` only; NetworkPlan gains no new fields.
- **Why**: §6.2–6.3 give the formulas but no PoE switch budget, endpoint classification or rule ids.
- **Alternatives**: exclude growth from port counts (superseded 2026-10-24); add trunk/STP fields to NetworkPlan now (contract change, deferred to P5 if needed).

## 2026-10-23 — P2: rationale rendering and explain entry point
- **Decision**: `render.py` keeps the P1 lead ("For X, chose Y (rule R) given k=v"), appends "(22 km)" to metre inputs ≥ 1,000, then one fixed `WHY[(domain, rule)]` sentence (tested to contain no measured values), math, rejected, counterfactual, warnings, standards. `spec_note` is shown by `render_text`/`render_markdown`, not inside `rationale` (so the OM4 spec wording "attenuation" never appears as the cause). `netarch explain` is a minimal Typer command (P7 adds Rich panels); `engines.design_l1_l2` is the temporary pipeline.
- **Why**: §4.2 "engines never write prose"; the gate needs input numbers in the text and a quick explain entry point.
- **Alternatives**: per-engine prose (violates §4.2); a throwaway script instead of a CLI command.

## 2026-10-23 — Native VLAN 999 is not in the trunk allowed list
- **Context**: P2 builder asked whether 999 should appear in `switchport trunk allowed vlan`.
- **Decision**: Keep it out; settled by the docs: technical.md §6.2 (allowed = exact planned set, native 999) and §11.3's expected `show interfaces trunk` output "allowed 10,20,99 · native 999".
- **Why**: Native VLAN 999 is an unused black-hole VLAN; it carries no planned traffic.

## 2026-10-24 — P2: PoE recommendation for APs (user answer (a), docs/QUESTIONS.md P2)
- **Decision**: for a site with APs, the `L2.CAP` Decision recommends physical 802.3at (PoE+) access switching with PoE budget ≥ APs × 30 W, the watts computed from the inputs (input `poe_required_w`; campus bldg-a: 8 × 30 = 240 W). No commercial switch model or budget beyond that number is named. Its rationale also states the lab mapping limitation (§6.4): the 3560-24PS is 802.3af (15.4 W per port) and the 2960-24TT has no PoE, so the lab cannot power 30 W APs (logical config identical). The lab facts are sourced constants in `devices.yaml` (`distribution_switch.poe_standard`, `distribution_switch.poe_per_port_w`, `access_switch.poe_per_port_w`). The "PoE budget not in the catalogue" warning is removed. An explicit `poe_budget_w` is still checked and raises `CapacityError` (`L2.CAP.POE`) when exceeded.
- **Why**: technical.md §6.3 (APs × 30 W, 802.3at) and §6.4 (state the physical recommendation and the lab mapping); the docs give no PoE switch budget.
- **Alternatives**: (b) check strictly against the lab switches (CapacityError on every campus building); keep the warning-only behaviour.

## 2026-10-24 — P2: access port counts include growth (user answer, docs/QUESTIONS.md P2)
- **Decision**: wired endpoints per segment = ceil(hosts × (1 + growth_pct/100)) in exact decimal arithmetic (§7.2's sizing rounding without the +1 gateway); roles wireless and management stay excluded; access switches n = ceil((wired + APs) / 24). The `L2.CAP` math shows each segment's growth term. Campus: bldg-a 288 wired + 8 APs → 13 switches, bldg-c 384 + 10 → 17.
- **Why**: the access layer is sized for the same planned growth as the address plan.
- **Alternatives**: current hosts only (previous provisional rule).

## 2026-11-10 — P3: VLSM details §7 leaves open
- **Infra block contents**: one /30-or-/31 per input link (`link:a--b`), plus for `profile_type: global` one GRE tunnel per city from the HQ hub (`tunnel:hub--city`) and `tunnel:hub--cloud-vgw` when `cloud` is set (§8.3); one /32 loopback per site (one router / L3 switch per site = router-ID). P4 must use these names rather than allocate its own. The cloud side's own addresses come from the VPC, not the root.
- **/31 vs /30**: `full` dialect → /31. `pt` → /31 only if **both** PT rows `routed_port_slash31_3560` and `router_interface_slash31` are `accepted`, else /30 (both today: untested). Lookup in `engines/ptcaps.py` (shared with P4/P5).
- **Gateway** = first usable host of each segment.
- **Reserved ranges** are pre-occupied space: each block goes to the lowest aligned free position (first fit, same result as the §7.3 cursor when nothing is reserved). Exhaustion: requested = Σ rounded site + infra blocks; available = root − reserved inside the root; shortfall = requested − available; if shortfall ≤ 0 but nothing fits, the message says reserved ranges fragment the root. Smallest fitting root = smallest block holding requested + reserved; "No IPv4 root is that large" when none does (huge host counts).
- **Sort keys**: blocks sort by size DESC then key ASC; site keys are `(id, 0)` and infra `("infra", 1)`, so a site called "infra" cannot collide. Segment keys are `(name, vlan)`.
- **Growth** uses exact decimals (`Fraction(str(growth_pct))`), so 10 hosts at 10 % = 11 (+1 gateway = 12), not 12 from float error.
- **"/30 root with 2 hosts" (§14.2)** read with the gateway rule: 1 host + gateway fills a /30 exactly; 2 hosts need a /29 (short by 4).
- **Metrics**: sizing waste = Σ(usable − needed); growth headroom = Σ(needed − hosts − 1); site/infra block rounding reported separately; free list = maximal aligned blocks.
- **Decisions**: `L3-nn`, domain addressing — ADDR.SIZE, ADDR.P2P, one ADDR.SITE per site, ADDR.INFRA, ADDR.EFF; error rule ADDR.E1. New standards: RFC 950/1878/4632/3021/1918.
- **Why**: §7 gives the algorithm but not these edges; P4 needs stable link/tunnel/loopback addresses.
- **Alternatives**: tunnels allocated in P4 from free space (breaks one contiguous infra block); /31 whenever either PT row is accepted (unsafe for campus 3560 links).

## 2026-11-10 — P4–P7 built under deadline (user: "skip the quizzes, complete it first")
- **Quiz gate**: user asked to remove it; `.git/hooks/pre-commit` renamed to `pre-commit.quiz-disabled` (rename back to restore).
- **Lab mapping (`configgen/interface_map.py`)**: per site one L3 device + one 2960 access switch + one PC per segment (§6.3 "representative lab"). Campus: 3560 `dist-<site>` with SVIs, routed inter-building ports on Gi0/1–2 then Fa0/24 downward; access uplinks Fa0/1(–2) ↔ acc Gi0/1(–2) (two only for `dual_uplink`). Metro/Global: 2911 `rtr-<site>`, router-on-a-stick Gi0/0.<vlan> to `acc-<site>`. Metro EVPLs ride an `evpl-carrier` 2960: each link = one EVC (dot1Q 101 + link index) on Gi0/1.<evc>; carrier ports are trunks with exactly that router's EVCs (§8.3: one handoff carries several EVCs; PT needs a switch for that). Global Internet = `inet-sw` 2960, VLAN 900, RFC 5737 203.0.113.0/24 (hub .1, then cities, cloud-vgw last). Hostnames/VLAN names are reduced to `[A-Za-z0-9-]` and de-duplicated (no config injection).
- **Routing**: RT.R2 when `profile_type == global` (Internet WAN) or subnets ≥ 50; else RT.R1 (Metro's carrier EVPL is a private L2 WAN, so single area per §8.3). Multi-area: hub site (kind hq) LAN + all transit + loopbacks in area 0, other sites area 1..n, `area n range <site block>` on their router. Transit = routed physical ports, EVPL sub-interfaces, OSPF tunnels: `ip ospf network point-to-point`, `no passive-interface`; everything else passive. `dual_homed`: EVPL timers 1/4 s, cost 10 on links touching the hub, 100 otherwise. Global hub: BGP 65001 ↔ cloud-vgw 64512 over the cloud tunnel (hub = first host, cloud = last host), `network <org summary>` + Null0 static, `redistribute bgp … route-map BGP-TO-OSPF` (prefix-list VPC-ONLY). `cloud` on campus/metro is ignored with a warning.
- **VPN**: tunnel numbers follow the P3 infra order; same `Tunnel<i>` on both ends; crypto map `CMAP` on the Internet interface, one entry per peer, crypto ACL `GRE-<PEER>` = `permit gre host local host peer`. PSK refs `psk:<hub>--<site>`, keys generated at export (`render.make_secrets`, `secrets.token_hex`); tests use fixed secrets for golden files.
- **QoS**: only when `latency_target_ms` is set; worst case = longest input link; terms per §8.5 with constants in `data/design.yaml` (1 Gbps lab serialisation, 2 hops, 0.05 ms/hop assumption). LLQ `WAN-EDGE` output on every router's EVPL handoff; `MARK-TRADING` (class-default → set dscp ef) input on trading sub-interfaces.
- **ACLs**: WIFI-IN-<vlan> inbound on each wireless gateway (deny → every MGMT, permit tcp 80/443 + udp 53 → every SERVERS, deny rest to SERVERS, permit WIFI any, explicit deny). Metro TRADING-PROTECT is **outbound at the colo trading gateway** (spec_note in SEC decision: "near the source" would need the rule on every segment). Trading port default tcp 443 (§8.6 says "configured ports"). IOT-IN-<vlan>: tcp 8883/443 + udp 53/123 to the hub's SERVERS only. CLOUD-OUT outbound on the hub's cloud tunnel. VTY-MGMT standard ACL on every device when a management segment exists.
- **Dialect flags** (`configgen/render.py`): `pt` keeps a feature only if its PT matrix row is `accepted`: ACL `log` (svi_extended_acl_log), MQC (mqc_llq), tunnel mtu/mss (tunnel_adjust_mss_ip_mtu), SHA-256/group 14 (ipsec_sha256_group14), plus /31 from P3. Every omission is a `! NETARCH-PT-COMPAT:` header line. Other rows (expected "accepted") are emitted as-is.
- **Config order**: §9.3, except crypto and QoS definitions are emitted **before** the interfaces (IOS rejects `service-policy` for an undefined policy-map when pasting). `crypto key generate rsa general-keys modulus 2048` is emitted as a command.
- **Self-check** (`verify/selfcheck.py`) uses ciscoconfparse2 for interface/`router ospf` blocks and regex for globals; one FAIL row per violation, one PASS row per clean check id.
- **secrets.txt** is created owner-only (0600 via os.open + chmod; on Windows only the read-only bit maps). From an automated security review finding.
- **Batfish runner**: 3 s TCP probe of port 9996; unreachable → `NOT CONNECTED (skipped)`, verify exit code from self-check only. Not run against the P4+ configs yet (Docker was not running on 2026-11-10).
- **CLI**: non-TTY output uses a 200-column console so tables are never truncated in pipes/tests.
- **TUI**: one screen with tabs (Design summary, Decisions tree, IP Plan, What-if, Configs, Verify, Export) instead of separate Home/Requirements screens; preset buttons + JSON path at the top; errors listed by field. Requirements are not edited as a form (only link distances via What-if).
- **Why**: deadline day; these are the smallest choices that satisfy the §8–§11 rules and the P4–P7 gates.
- **Alternatives**: direct router-to-router cables for Metro (2911 has only 3 Gi ports; HQ needs 3 links + LAN); full Requirements form in the TUI (time).

## 2026-11-10 — Fixes from the P4–P7 phase-reviewer
- `pt` dialect now omits the hub's prefix-list/route-map/`redistribute bgp` unless PT row `prefix_list_route_map_redistribution` is accepted (COMPAT line says only the hub reaches the VPC). Supersedes "other rows are emitted as-is" for this row.
- `line vty 0 15` (all VTY lines get SSH + access-class), not 0 4.
- `netarch export` maps OSError (unwritable `--out`) to an Export error panel, exit 2 (input).
- TUI keeps one secrets set per loaded plan, so viewer, verify and export show the same keys.
- Self-check C10 also checks tunnel source = own public IP and matching PSKs.
- Batfish: host JSON carries the gateway; `parseWarning`; hub route check (other areas' site blocks present, their segment subnets absent); `netarch verify --report` writes `batfish-report.md` when Batfish ran.
- Known, not fixed: QOS.LAT assumes 1 Gbps serialisation while the lab EVPL carrier 2960 ports run 100 Mbps (0.12 ms/hop, still far under 5 ms); C8 does not compare areas across a link.

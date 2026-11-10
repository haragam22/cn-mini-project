# Questions for the user
Unchecked items block build-all and scheduled runs. Answer under the item, then tick it.
Format: `- [ ] (Phase N) question — why it matters, options` followed by an `**Answer**:` line.

- [x] (Phase 0) Batfish spike never ran: approve Docker for the agent, or run Batfish yourself? — Gate item 1 (initIssues 0 errors, OSPF session established) needs a live Batfish server. `docker version` was refused by the permission system ("This command requires approval"), and `pytest -m batfish` then errored with `ConnectionRefusedError: [WinError 10061]` on localhost. Options: (a) allow `docker` commands in permissions so the next run starts `docker run --name batfish -v batfish-data:/data -p 9996:9996 -p 9997:9997 batfish/allinone` and runs the suite; (b) you start the container, run `.venv/Scripts/python -m pytest -q -m batfish` (tests are in `tests/test_batfish_spike.py`), and paste the result here. Not yet confirmed: the image name and ports, the traceroute disposition `DELIVERED_TO_SUBNET` for 10.2.2.10, and the expected 2 OSPF rows. The working command still has to go into README.md.
  **Answer**: Allow it. Docker commands (version/info/run/ps/exec...) are now in the scheduled allowlist; start Batfish with the command above, run the batfish suite, record the working command in README. (user, 2026-10-23)
- [x] (Phase 0) OS2 attenuation at 1310 nm (LR): keep 0.35 dB/km or switch to 0.4? — technical.md uses 0.35 (a typical cabled G.652.D figure). IEEE 802.3 Clause 52 (Table 52-14 note c) derives LR's 6.2 dB channel insertion loss from 0.4 dB/km, and TIA-568.3-D allows up to 0.5 outside plant. At 0.4 the 10 km LR check has exactly 1.0 dB margin and still passes. The P2 worked examples ("1.5 dB margin") assume 0.35. The value was kept and the difference is noted in `netarch/data/media.yaml`.
  **Answer**: Keep 0.35 dB/km (P2 worked examples depend on it); record IEEE 0.4 in the source note. (user, 2026-10-23)
- [x] (Phase 0) OS2 attenuation at 1550 nm (ER/ZR): keep 0.25 dB/km? — The IEEE ER budget implies 0.225 and the TIA outside-plant maximum is 0.5. 0.25 is the more conservative typical figure, and the Metro worked examples in §5.3 depend on it. Kept for now.
  **Answer**: Keep 0.25 dB/km. (user, 2026-10-23)
- [x] (Phase 0) ZR budget: keep 23 dB? — Cisco's datasheet gives Tx min 0 dBm and Rx min −24 dBm (a 24 dB difference), and resellers quote 23 dB guaranteed. 23 is the conservative choice and the 35 km example (12.45 dB margin) depends on it. Kept for now.
  **Answer**: Keep 23 dB (conservative). (user, 2026-10-23)
- [x] (Phase 0) Reel length 4 km: OK to record it as a design assumption with no external source? — No standard specifies it. `media.yaml` cites it as "design assumption (technical.md §5.3)". The "every constant has a source" gate item counts this as sourced only if you accept that.
  **Answer**: Yes, record as a design assumption; counts as sourced. (user, 2026-10-23)
- [x] (Phase 0) Is the optics citation level good enough? — The ER 11 dB figure comes from IEEE 802.3 reflector emails quoting Table 52-24, and LR 6.2 dB from an 802.3dj presentation. Nobody read the standard itself. Options: accept these as is, or check them against your copy of IEEE 802.3 Clause 52 and update the `source` strings.
  **Answer**: Accept current citations for now; user may verify against Clause 52 before submission. (user, 2026-10-23)
- [x] (Phase 0) technical.md §11.2/§14.1 say Batfish tests are "skipped when Docker is down". Should that wording be updated? — In practice, under the 2026-10-22 decision, they are deselected from the gate with `-m "not batfish"`, and run without a server they error. Options: (a) reword technical.md to "deselected from the gate; run separately"; (b) add a fixture that skips when Docker is down (conflicts with the test-gate no-skip rule). (a) is recommended.
  **Answer**: (a) Reword technical.md to: deselected from the gate (-m "not batfish"), run separately with Docker up. (user, 2026-10-23)
- [x] (Phase 0) Confirm PyYAML 6.0.3 as the YAML loader — The docs specify `data/*.yaml` files but name no loader. PyYAML is already a transitive dependency of pybatfish and ciscoconfparse2, and the builder pinned it directly (decisions.md, 2026-10-23). Alternatives: ruamel.yaml, or switch the data files to JSON (stdlib only).
  **Answer**: Yes, PyYAML 6.0.3 confirmed. (user, 2026-10-23)

- [x] (Phase P1) Global preset links: leave `links: []` and let P4 build hub-and-spoke GRE-over-IPsec tunnels from site kinds? — Real inter-city distances exceed §4.1's `distance_m` ≤ 120,000 cap. Alternative: add a WAN/VPN link type with no distance (schema change).
  **Answer**: Keep links empty; P4 builds hub-and-spoke GRE-over-IPsec tunnels from site kinds (§8.3). No schema change. (user, 2026-10-23)
- [x] (Phase P1) Metro backup link distances: remote-1↔colo 20 km and remote-2↔colo 30 km (provisional)? — The plan gives no remote↔Colo distances, but dual_homed needs them; they decide the P2 optic (ER for both).
  **Answer**: Keep remote-1↔colo 20 km and remote-2↔colo 30 km. (user, 2026-10-23)
- [x] (Phase P1) Preset details: confirm per-segment host counts, VLAN ids (STAFF 10, WIFI 20, LABS 30, SERVERS 40, TRADING 50, IOT 60, MGMT 99), APs 8/8/10, metro/global root 10.0.0.0/16, site ids (hq, remote-1, remote-2, colo, city-1..3; real city names?). Full splits in decisions.md.
  **Answer**: Keep all splits, VLAN ids, APs, roots. Use real city names: HQ Delhi; cities Mumbai, Bangalore, Singapore. Campus total stays 1,580 (~1,600). (user, 2026-10-23)
- [x] (Phase P1) Reject VLAN 999 for segments? — §6.2 reserves 999 as the unused native VLAN; §4.1 doesn't forbid it. Not added.
  **Answer**: Yes, reject VLAN 999 for segments (reserved unused native VLAN, §6.2). (user, 2026-10-23)
- [x] (Phase P1) Reserved/VPC range outside RFC 1918: raise `AddressOverlapError` (as the §4.1 row reads; implemented) or `InputValidationError`?
  **Answer**: Keep AddressOverlapError (as the §4.1 row reads). (user, 2026-10-23)
- [x] (Phase P2) PoE for APs (§6.3 says APs × 30 W, 802.3at) — the lab 3560-24PS is 802.3af (15.4 W/port) and the 2960-24TT has no PoE, and no PoE budget is in the docs. Options: (a) per §6.4, recommend a physical 802.3at (PoE+) access switch sized to APs × 30 W, and state the lab mapping limitation (3560-24PS, 802.3af) in the rationale; (b) check strictly against the lab switches → CapacityError on every campus building.
  **Answer**: (a) Recommend a physical 802.3at (PoE+) access switch sized to APs × 30 W; state the lab mapping limitation (3560-24PS 802.3af) in the rationale, per §6.4. (user, 2026-10-24)
- [x] (Phase P2) Access port counts: include growth_pct (like VLSM sizing does) or use current hosts only? MGMT is excluded either way.
  **Answer**: Include growth_pct in access port counts (MGMT still excluded). (user, 2026-10-24)
- [x] (Phase P2) Topology gap in §6.1: 1 building with > 500 endpoints is covered by no rule. Use a two-tier collapsed core with several access switches (labelled TOP.R2 single block)?
  **Answer**: Yes: two-tier collapsed core with several access switches (TOP.R2 single block); three-tier only per R3. (user, 2026-10-24)
- [x] (Phase P2) requested_media handling: os2 is always honoured; om4 is honoured up to 400 m, else ignored with a warning; copper > 100 m → E1 error; a copper request on an inter-building link is overridden to OM4 (X1) with a warning (idea.md: inter-building forces fibre). OK?
  **Answer**: Keep requested_media handling as built. (user, 2026-10-24)

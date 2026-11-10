# NetArchitect

Terminal app that acts as a junior network architect: describe an organisation, it designs the
network, explains every decision, writes Cisco IOS configs, and verifies them.
CIC-307 Computer Networks mini-project.

> Screenshots and the demo video link are added with the Packet Tracer lab (P8/P9).

## What it does

1. **Validate** a preset or custom JSON (every bad field reported at once).
2. **Design**: L1 media + optical power budget, topology tier, VLANs/trunks/RSTP, bitwise VLSM
   with per-site summarisation, OSPF (single/multi-area), Metro dual-homed failover, eBGP to a
   cloud VPC, GRE-over-IPsec, LLQ for a latency target, ACLs placed near the source.
3. **Explain** every decision: inputs, math, rejected options, counterfactual, standards cited.
4. **Generate** Cisco IOS for every device in two dialects: `full` (real IOS / Batfish) and `pt`
   (Packet Tracer; every downgrade listed in a `! NETARCH-PT-COMPAT:` header).
5. **Verify**: 11-invariant self-check, Batfish (optional), Packet Tracer checklist.

## Quickstart

```
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e .[dev]
.venv/Scripts/netarch                       # Textual TUI (d design · v verify · e export · q quit)
.venv/Scripts/netarch presets
.venv/Scripts/netarch design   --preset campus
.venv/Scripts/netarch explain  --preset metro --domain routing
.venv/Scripts/netarch plan     --preset global          # VLSM table with wildcards
.venv/Scripts/netarch export   --preset campus --out ./output --zip --dialect pt
.venv/Scripts/netarch verify   --preset global          # self-check + Batfish (if running)
.venv/Scripts/netarch checklist --preset metro          # Packet Tracer build + test steps
```

Custom designs: `--input my-org.json` (schema: docs/technical.md §4.1; presets in
`netarch/presets/`). Exit codes: 0 ok · 1 verification failed · 2 input invalid · 3 design
constraint (distance, optical budget, address exhaustion, capacity).

Exports: `configs/<hostname>.txt`, `rationale.md`, `ip-plan.csv`, `plan.json`,
`pt-checklist.md`, `topology.mmd`, `secrets.txt` (generated passwords/PSKs — git-ignored, never
in the ZIP).

## Presets

| Preset | Sites | Highlights |
|---|---|---|
| campus | 3 buildings, 1,580 users | OM4 inter-building, 3560 SVIs, routed /30 triangle, single-area OSPF, WIFI ACLs |
| metro | HQ, 2 remotes, colo (15–35 km) | OS2 ER/ZR optics by power budget, EVPL sub-interfaces, dual-homed failover, LLQ for < 5 ms |
| global | Delhi (HQ), Mumbai, Bangalore, Singapore + cloud VPC | multi-area OSPF with ABR summaries, GRE-over-IPsec hub-and-spoke, eBGP 65001 ↔ 64512 |

## Tests

`.venv/Scripts/python -m pytest -q -m "not batfish"` (unit, hypothesis property suite vs the
`ipaddress` oracle, golden configs, CLI/TUI). Coverage:
`--cov=netarch --cov-report=term-missing` (99 % at P7). Details: docs/testing.md.

## Batfish (optional verification)

Pinned client: `pybatfish==2026.9.17.3748`.

Verified on this machine on 2026-10-23 (Windows 11, Docker Desktop 29.6.1, WSL2 backend):

```
docker run -d --name batfish -v batfish-data:/data -p 9996:9996 -p 9997:9997 batfish/allinone
```

- Image: `batfish/allinone:latest`, digest `sha256:54cb0ed94fd9a3c1ca0985f73e5be479e955cee9b9f6a6799b66be3364fd8e5c` (Batfish server `2026.08.27.3685`).
- Ports: 9996 (pybatfish v2 API) and 9997 (legacy coordinator) on localhost.
- Client: `pybatfish==2026.9.17.3748`, `Session(host="localhost")`.
- Later runs: `docker start batfish`. The server accepts connections a few seconds after start.

Then run the Batfish suite: `.venv/Scripts/python -m pytest -q -m batfish`
(spike snapshot: `tests/fixtures/batfish_spike/`).

## License

MIT

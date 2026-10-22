# NetArchitect — The Idea

> **Course:** CIC-307 Computer Networks · Mini-Project · 100 points
> **Deadline:** 10 November 2026 · **Format:** Individual
> **One line:** A terminal app that acts like a junior network architect. You describe an organisation and it designs the network, explains every decision, writes the Cisco configs, and checks that they work.

---

## 1. The problem

Designing even a small enterprise network involves dozens of linked decisions:

- Which cable or fibre for each run, and which transceiver?
- How to split an address block into subnets without overlap or waste
- Which VLANs exist, which links trunk them, and where spanning tree is rooted
- Which routing protocol to use, how many areas, and whether BGP is needed
- How to secure sites over the Internet, and what traffic to filter

Each decision follows from physics, standards and arithmetic: cable attenuation and dispersion, IEEE 802.3 reach limits, binary subnet math, OSPF scaling limits. People still make these choices by gut feeling, copy configs from old projects, and find the mistakes only after deployment.

Generative AI has made this worse in one specific way. It writes configs that **look right** but break subtly: masks off by one bit, trunks that allow every VLAN, LR optics on a 35 km link. Someone has to be able to catch those mistakes.

## 2. What NetArchitect does

```
 Requirements  ──►  Design engines  ──►  Explained decisions  ──►  Device configs  ──►  Verification
 (preset/JSON)      (L1 · L2 · L3)       (why + why-not)          (.txt per device)     (self-check + Batfish
                                                                                          + Packet Tracer)
```

1. **Takes requirements:** pick one of three presets (Campus, Metro, Global) or load a custom JSON. Examples: "3 buildings, 180 m and 320 m apart, 1,600 endpoints, 10.0.0.0/16, PoE access points."
2. **Designs the network** with rule engines:
   - **Physical layer:** copper vs multimode vs single-mode, the exact transceiver, and an optical power budget check.
   - **Layer 2:** topology tier, VLANs, trunks, RSTP root placement.
   - **Layer 3:** bitwise VLSM allocation, routing protocol and area design, VPN, QoS, ACL policy.
3. **Explains every decision** in plain engineering language with the numbers that drove it, the standard or RFC behind it, the options it **rejected and why**, and what would change the answer.
4. **Generates configs:** copy-paste-ready Cisco IOS for every router and switch (interfaces, SVIs, trunks, STP, OSPF/BGP, IPsec, ACLs), each downloadable as a `.txt`.
5. **Verifies its own output:**
   - a built-in self-check (overlaps, VLAN/trunk consistency, wildcard masks)
   - **Batfish**, an industry config analyser, which checks that OSPF/BGP sessions form, routes exist, ACLs behave, and hosts can reach each other
   - a generated **Packet Tracer checklist** of commands and expected results for the final proof.

All of this runs in a **pretty, interactive terminal UI**: menus, tabs, tables, colour-coded verdicts and export buttons. A scriptable CLI sits underneath for tests and automation.

## 3. The three scenarios

| | Profile 1: Campus LAN | Profile 2: Metro MAN | Profile 3: Global WAN |
|---|---|---|---|
| **Scale** | 3 buildings, < 400 m apart | HQ + 2 remote sites, 15–35 km | 4 cities + a cloud VPC |
| **Users / devices** | 1,600 endpoints, PoE APs | 450 users, FinTech colocation | 2,000 IoT devices / scanners |
| **Physical** | Cat6a in buildings, OM4 multimode between them | OS2 single-mode, LR vs ER by power budget | Carrier/Internet links (media out of scope) |
| **Layer 2** | 802.1Q VLANs, RSTP | EVPL carrier circuits as 802.1Q sub-interfaces | Per-city VLANs incl. isolated IoT VLAN |
| **Layer 3** | Single-area OSPF | Single-area OSPF, dual-homed failover, sub-5 ms QoS | Multi-area OSPF, eBGP to cloud, GRE-over-IPsec, summarisation |
| **Main lesson** | Copper vs fibre physics, VLAN design | Optical budgets, latency and failover | Routing hierarchy, VPN design, summarisation |

The three profiles are deliberately **small → medium → large**, so the same rule engines are tested at three scales.

## 4. Why "explainable" is the core

The spec makes explanation mandatory and gives it 25 points. A plain tool would print *"OS2 SMF selected."* NetArchitect prints a full decision record:

> **Decision L1-03 · Media for HQ ↔ Remote-1 (22 km)**
> **Selected:** OS2 single-mode fibre with **10GBASE-ER** optics.
> **Why:** 22 km is far beyond multimode reach. 10GBASE-SR over OM4 is limited to 400 m by **modal dispersion** at 850 nm, not attenuation. Over single-mode at 1550 nm, the estimated link loss is 7.0 dB (22 km × 0.25 dB/km + 2 connectors × 0.5 dB + 5 splices × 0.1 dB). That's within ER's ≈ 11 dB channel budget, with 4.0 dB to spare.
> **Rejected:** Cat6a (100 m channel limit, IEEE 802.3an). OM4 + SR (400 m reach). OS2 + **LR** (rated reach 10 km < 22 km; at 1310 nm the loss would also be ≈ 9.2 dB, above LR's ≈ 6.2 dB budget).
> **Would change if:** distance ≤ 10 km with loss inside LR's budget (→ LR), or ER margin drops below 1 dB (→ ZR, DWDM or an intermediate site).
> **Standards:** IEEE 802.3 Clause 52, TIA-568.3-D.

Every decision object carries **choice, inputs used, rule, rationale, standards, rejected alternatives, and counterfactual**. That's what separates real explainability from print statements.

## 5. Where we go beyond the spec

The spec's rule table is the baseline, and NetArchitect implements it faithfully: same thresholds, same `PhysicalDistanceViolationError`. Where the spec is technically loose, the tool keeps the spec behaviour **and** explains the correct engineering. Each item below is a documented refinement and a viva talking point:

| Spec says | Engineering reality | What NetArchitect does |
|---|---|---|
| "400 m **attenuation** limit of OM4" | The 400 m limit for 10GBASE-SR is a **modal dispersion** (bandwidth-distance) limit. | Uses the correct cause in every rationale and names the discrepancy in docs. |
| "> 400 m → OS2 SMF (LR/ER)" | LR is rated for 10 km and ER for 40 km, so distance alone doesn't decide. | Computes an **optical power budget** and picks the cheapest optic that fits with margin, or errors. |
| "≤ 100 m → Cat6a" | 100 m is a *channel* (90 m permanent link + 10 m patch). Runs **between buildings** should be fibre even when short, because of ground-potential difference and lightning. | Inter-building flag forces fibre and explains why. |
| "< 50 subnets → OSPF Area 0" | A useful heuristic. The real reasons are LSDB size and SPF recomputation scope. | Implements the threshold and explains the *why*. |
| "IPsec VPN + multi-area OSPF" | OSPF can't run over plain policy-based IPsec (it uses multicast hellos). Cloud gateways speak BGP, not OSPF. | **GRE-over-IPsec** for city-to-city OSPF, **eBGP** to the cloud VPC. |
| "Sub-5 ms QoS" | 35 km of fibre adds only ~0.175 ms, so distance is not the problem. **Queuing** is. | Computes the latency budget and generates LLQ priority queuing for trading traffic. |
| OSPF default cost | Default reference bandwidth of 100 Mbps makes 1G and 10G links cost the same. | Sets `auto-cost reference-bandwidth` so 10G links are preferred, and explains it. |

## 6. The AI-audit angle (20 points)

The spec treats the student as **Lead Network Architect and Validator** of AI-generated code. NetArchitect is built *with* AI, and every AI mistake caught during development is logged in `ai_audit_log.md` with:

- the verbatim prompt
- the buggy code
- the networking diagnosis
- evidence (Batfish output and/or a Packet Tracer packet-flow simulation)
- the fix and the regression test added.

Likely real catches include off-by-two host counts, unsorted VLSM causing misaligned subnets, trunks without an allowed-VLAN list, masks used where OSPF expects wildcards, LR optics for a 35 km link, OSPF over policy-based IPsec, and a missing `switchport trunk encapsulation dot1q` on a 3560.

The verification layer exists partly *for* this. Batfish and Packet Tracer turn "I think the AI was wrong" into **evidence**.

## 7. Scope

**In scope**
- 3 presets plus validated custom JSON input
- L1/L2/L3 decision engines with full explanations
- Bitwise VLSM allocator (hierarchical, /31 point-to-point, /32 loopbacks, summarisation)
- Cisco IOS config generation: routers, L3/L2 switches, SVIs, trunks, RSTP, OSPF, BGP, GRE/IPsec, QoS, ACLs
- Per-device `.txt` export, ZIP export, rationale log, IP plan, PT checklist
- Self-check plus Batfish verification
- Interactive TUI plus scriptable CLI
- pytest suite with property-based tests
- `ai_audit_log.md`, README with screenshots and a YouTube demo link

**Out of scope (deliberately)**
- Driving Packet Tracer programmatically (no usable API, and `.pkt` files are encrypted)
- Vendors other than Cisco IOS
- Wireless RF planning (AP placement, channel plans)
- Real cost quotes (any bill of materials is indicative)
- A web frontend (earns no rubric points)
- LLM-made design decisions. Any AI feature may only convert English to JSON input; the rule engines decide.

## 8. Rubric mapping

| Rubric area | Points | Where it is earned |
|---|---|---|
| Parameter engine & presets | 15 | 3 presets, pydantic validation, typed error hierarchy, boundary handling |
| Explainable decision engine | 25 | Decision records with rationale, standards, rejected options, counterfactuals, for media, transceiver, topology tier, routing |
| Subnet engine & configs | 25 | Bitwise VLSM, zero overlap proven by tests + Batfish; IOS configs for switches, routers, SVIs, ACLs |
| Automated unit testing | 15 | Distance violations, address exhaustion, wildcard masks on edge subnets (/0, /8, /30, /31, /32), property-based tests |
| AI code audit & defense | 20 | ≥ 2 required, target 4–5 entries, each backed by Batfish and Packet Tracer packet-flow evidence |

## 9. Demo story (for the video)

1. Launch `netarch`, the TUI home screen, and pick **Campus**.
2. Walk the **Decisions** tab: fibre between buildings, with the "why not copper" explanation.
3. **IP Plan** tab: the VLSM table and utilisation figures.
4. Change one distance in a custom profile to 120 m on copper → `PhysicalDistanceViolationError` shown cleanly.
5. Switch to **Metro**: the 35 km link escalates from LR to ER with the power-budget arithmetic on screen.
6. **Verify**: self-check passes and Batfish shows OSPF sessions up and traceroutes succeeding.
7. **Export**: download per-device `.txt` files, then load them into Packet Tracer and ping across buildings.
8. Close on one AI-audit entry: AI's buggy trunk config, the PT simulation showing the leak, and the fix.

## 10. Glossary

| Term | Meaning |
|---|---|
| VLSM | Variable Length Subnet Masking: subnets of different sizes from one block |
| SVI | Switched Virtual Interface: a VLAN's gateway on a Layer 3 switch |
| RSTP | Rapid Spanning Tree (802.1w): loop prevention with fast convergence |
| EVPL | Ethernet Virtual Private Line: carrier point-to-point Ethernet, VLAN-tagged |
| LLQ | Low-Latency Queuing: a strict-priority queue for delay-sensitive traffic |
| ABR | Area Border Router: an OSPF router joining Area 0 to another area |
| Batfish | Open-source tool that models a network from its configs and answers questions about it |
| Power budget | Transmitter power minus receiver sensitivity: the loss a fibre link can tolerate |

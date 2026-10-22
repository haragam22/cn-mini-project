# NetArchitect (cn-mini-project)
Terminal app that acts as a junior network architect: describe an organisation, it designs the network, explains every decision, writes Cisco IOS configs, and verifies them. CIC-307 Computer Networks mini-project, individual, **hard deadline 10 Nov 2026**.

## Stack
Python (3.11 per plan; final version pinned in P0) · pydantic v2 · Typer + Rich · Textual · Jinja2 · pybatfish + Batfish (Docker) · pytest, hypothesis, pytest-cov, syrupy · ruff.
Package: `netarch/` (layout in docs/technical.md §2). Entry point: `netarch`.

## Commands
- Install: `py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -e .[dev]` (version per P0)
- Run: `netarch` (TUI) · `netarch --help` (CLI)
- Test gate: `.claude/test-command` (excludes Batfish; see docs/testing.md)
- Batfish suite: Docker + Batfish up, then `.venv/Scripts/python -m pytest -q -m batfish`

## Docs (read on demand)
- docs/idea.md — problem, scope, rubric, demo script
- docs/technical.md — design source of truth: rules, math, data model, templates, verification
- docs/implementation.md — phases P0–P9 + tracks T1/T2, gates = Done when, cut line §12
- docs/decisions.md — decisions and why
- docs/flow.md — pipeline and code flow
- docs/testing.md — automated suites, Batfish run, your manual checks
- docs/QUESTIONS.md — open questions for the user

## Project rules
- Every engine is a pure function (plan in, plan out). Rules and numbers come from technical.md exactly; refinements are explained in Decisions, never silent.
- `ipaddress` is a **test oracle only**; VLSM uses integer bit math (§7.1).
- Tests land with the code (T2). Batfish tests carry `@pytest.mark.batfish` and are excluded from the gate, run separately.
- T1 audit capture: when your own generated networking code fails a test or the phase-reviewer and you fix it, save the verbatim prompt, the buggy code, the failing test output and the fix to `audit/raw/<date>-<topic>.md`. Never write or edit `ai_audit_log.md` entries; the user writes those from the raw files.
- Gate items tagged `(manual)` are the user's (Packet Tracer, visuals, video, GitHub). Phase Status `manual` = everything else verified.
- Never push; the user creates the GitHub repo and pushes.

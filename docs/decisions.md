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

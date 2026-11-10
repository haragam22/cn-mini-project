# Status / resume point
Updated 2026-11-10 (deadline day — see implementation.md §12 cut line; applying it needs the user's OK). Read this first when resuming. Phase detail: implementation.md. Why things are the way they are: decisions.md.

## Phases
| Phase | Status | Notes |
|---|---|---|
| P0 Setup & spikes | manual | Automated items verified (Batfish spike 4/4 vs live server; every optics constant sourced). **User:** PT matrix (docs/pt-matrix-guide.md), Textual check in Windows Terminal, push to GitHub. |
| P1 Inputs, models, presets | done | 37 invalid-input cases, 3-mistake aggregation, presets campus 1,580 / metro 450 users / global Delhi·Mumbai·Bangalore·Singapore. Review: **inline, not independent** (reviewer agent was blocked by auto mode at the time). |
| P2 L1/L2 engines + explain | done | Metro worked examples exact to 0.01 dB; PoE+ recommendation + lab note; port counts include growth. Review: **inline, not independent**. |
| P3 VLSM | done | Built 2026-11-10: `engines/vlsm.py` + `engines/ptcaps.py`, `AddressingPlan` in plan.py, `tests/test_vlsm.py` (112 tests, hypothesis 1,800 ex., vlsm.py 100 % coverage). Wired into `engines.design` and `netarch explain`. pt → /30 until both /31 PT rows are accepted. Independent phase-reviewer: **PASS** (6/6 gate items). |
| P4 Routing/VPN/QoS/ACL | done | Built 2026-11-10. Independent phase-reviewer **PASS** (4/4). |
| P5 Config generator | manual | Templates + `configgen/render.py` + `export/writer.py`, golden snapshots (6). **User:** paste one config per role into PT. |
| P6 Verification | todo (partial) | Self-check C1–C11 all PASS 3 × 2, mutations incl. PSK/tunnel source. Batfish runner has parse/initIssues/parseWarning/undefined refs/duplicate IPs/OSPF/BGP/IPsec/hub summaries/ACL line reachability + `batfish-report.md`. **Still to write:** `searchFilters` (IoT → non-collector), per-policy `traceroute`s, Metro failover `fork_snapshot`. **Never run on P4+ configs** (Docker off). |
| P7 CLI/TUI | manual | All commands + exit codes (export write errors → panel, exit 2), Textual TUI. **User:** Windows Terminal 120 × 35 check; **decide** whether the single field-labelled errors panel is acceptable vs per-field form (reviewer gap). |
| P8 Lab validation | todo (manual) | PT builds of 3 presets + `ai_audit_log.md` entries (raw candidates in audit/raw/, 2 now). |
| P8.5 User simulation | todo | ≥ 1,000 simulated users (`user-sim` skill) + clear docs/security/backlog.md + full-project security-breaker run. |
| P9 Docs/release | in progress | In-depth README + 8 real TUI screenshots (2026-11-10). **User:** demo video, PT screenshots, v1.0.0 release. |

## Pending before/at resume
1. security-breaker ran on P0–P7 (2026-11-10): 6 high all fixed with tests (docs/security/p0-p7.md); open critical/high 0; backlog F11 (dnspython pin), F14 (ZIP holds config secrets); QUESTIONS.md: public root allowed?
2. Optionally re-run `phase-reviewer` on P1 and P2 for an independent verdict (agents are now allowed in settings).
3. Next: user commits staged work; Batfish run with Docker + the 3 missing Batfish checks (searchFilters, policy traceroutes, Metro failover fork); P8 PT builds + ai_audit_log.md; P8.5 user-sim; P9 video + release.

## Repo state
- Commits: `0a13a44` plan, `ca5bd55` P3–P7 (user, 2026-11-10). **Staged, not committed:** security fixes (docs/security/p0-p7.md), in-depth README + 8 TUI screenshots (`docs/screenshots/`, `tools/screenshots.py`). Commit (quiz gate disabled), then `git push -u origin main` (remote `haragam22/cn-mini-project` exists but is empty).
- Gate: `.claude/test-command` → 584 passed, 7 Batfish deselected, 0 skipped (at P7 + security fixes). Coverage 99 % overall.
- Quiz pre-commit hook disabled at user request: `.git/hooks/pre-commit.quiz-disabled` (rename back to restore). Batfish suite: `-m batfish` with Docker up (README command).
- T1 audit candidates: audit/raw/ (1 so far).

# AI Audit Log

Mandatory deliverable (spec §4). Each entry records a real mistake made by an AI tool while
building NetArchitect, with evidence and the fix. Raw captures live in `audit/raw/`.

Entry template:

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

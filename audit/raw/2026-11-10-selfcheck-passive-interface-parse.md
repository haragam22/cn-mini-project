# 2026-11-10 — Self-check C8 flagged every OSPF transit interface as "not covered"

## Prompt context
Verbatim user prompt for this session: "after this which phases are left, we need to submit it
urgent skip all the quizes and lets complete it first". The agent then built P4–P7; the bug is in
the generated self-check (technical.md §11.1 invariant 8: OSPF `network` statements must cover
every transit interface).

## Buggy version (netarch/verify/selfcheck.py, C8)
```python
active = {ln.split(None, 1)[1] for ln in lines if ln.startswith("no passive-interface ")}
```

## Failing output (all 3 presets × 2 dialects)
```
campus pt [('C8', 'dist-bldg-a', 'transit interface passive-interface GigabitEthernet0/2 not covered by a network statement'), ...]
metro pt [('C8', 'rtr-colo', 'transit interface passive-interface GigabitEthernet0/1.105 not covered by a network statement'), ...]
global pt [('C8', 'rtr-bangalore', 'transit interface passive-interface Tunnel2 not covered by a network statement'), ...]
```

## Diagnosis
`no passive-interface Gi0/1` split once on whitespace gives `passive-interface Gi0/1`, not the
interface name, so the lookup of the interface's IP always failed and every OSPF adjacency
interface looked uncovered. The configs were correct (`network 10.0.16.0 0.0.0.3 area 0` covers
Gi0/1 10.0.16.1/30); the verifier misread the `router ospf` sub-command.

## Fix
```python
active = {ln.split()[-1] for ln in lines if ln.startswith("no passive-interface ")}
```

## Regression tests
tests/test_configgen_verify.py::test_selfcheck_all_pass (3 presets × 2 dialects all PASS) and
::test_mutation_wrong_wildcard (C8 still fails when a wildcard is wrong).

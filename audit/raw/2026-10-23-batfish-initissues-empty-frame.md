# 2026-10-23 — Batfish spike: initIssues test crashed on an issue-free snapshot

## Prompt context
P0 Batfish spike (implementation.md P0 task 3, gate item 1). The agent was asked to finish P0:
start `batfish/allinone`, run `.venv/Scripts/python -m pytest -q -m batfish`, and fix any wrong
spike configs/tests at the root cause using real Batfish output, without weakening the
"initIssues 0 errors" and "OSPF session ESTABLISHED" assertions. The verbatim prompt that
generated the original test (earlier P0 build session) was not available to this run.

## Buggy version (tests/test_batfish_spike.py)
```python
def test_init_issues_has_zero_errors(bf):
    issues = bf.q.initIssues().answer().frame()
    errors = issues[issues["Type"].str.contains("error", case=False)]
    assert errors.empty, errors.to_string()
```

## Failing output (Batfish 2026.08.27.3685, pybatfish 2026.9.17.3748)
```
E           AttributeError: Can only use .str accessor with string values, not floating. Did you mean: 'std'?
.venv\Lib\site-packages\pandas\core\strings\accessor.py:248: AttributeError
FAILED tests/test_batfish_spike.py::test_init_issues_has_zero_errors - Attrib...
1 failed, 3 passed, 38 deselected in 10.15s
```
Actual Batfish answer: `initIssues rows: 0`, every column (Nodes, Source_Lines, Type, Details,
Line_Text, Parser_Context) dtype `float64`. The configs were correct; the test assumed the
`Type` column is always string-typed, which pandas does not do for an empty frame.

## Fix
```python
    # An issue-free snapshot yields an empty, all-float64 frame; cast before .str.
    errors = issues[issues["Type"].astype(str).str.contains("error", case=False)]
```
Assertion unchanged (no error-type issues allowed). Result: `4 passed, 38 deselected`.
The other expectations were confirmed by real output and needed no change: 2 OSPF rows, both
`ESTABLISHED`; traceroute tcp/22 -> `DELIVERED_TO_SUBNET`, tcp/23 -> `DENIED_OUT`.

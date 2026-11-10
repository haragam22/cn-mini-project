"""P0: pt_capabilities.yaml holds exactly the technical.md §12 rows, each with a result field.

Filling the results in Packet Tracer is a (manual) gate item; this test guards the file's shape.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_RESULTS = {"untested", "accepted", "rejected", "alternative"}
DEVICES = {"2911", "3560", "2960"}


def matrix_rows():
    """Parse the §12 markdown table from technical.md -> list of (feature, expected)."""
    text = (ROOT / "docs" / "technical.md").read_text(encoding="utf-8")
    section = text.split("## 12.", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("Feature", "") or set(cells[0]) <= {"-"}:
            continue
        rows.append((cells[0], cells[2]))
    return rows


def features():
    doc = yaml.safe_load((ROOT / "netarch" / "data" / "pt_capabilities.yaml").read_text("utf-8"))
    return doc["features"]


def test_matrix_parses_all_rows():
    assert len(matrix_rows()) == 17


def test_yaml_has_every_matrix_row_with_expected_value():
    def plain(s):  # markdown code spans are formatting, not content
        return s.replace("`", "")

    expected = [(plain(f), re.sub(r"^/31 uncertain$", "uncertain", e)) for f, e in matrix_rows()]
    got = [(plain(f["feature"]), f["expected"]) for f in features()]
    assert got == expected


def test_every_row_has_valid_result_and_devices():
    rows = features()
    assert len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        assert r["result"] in ALLOWED_RESULTS, r["id"]
        assert r["devices"] and set(r["devices"]) <= DEVICES, r["id"]
        if r["result"] == "alternative":
            assert r["alternative"], f"{r['id']}: alternative result needs the accepted syntax"

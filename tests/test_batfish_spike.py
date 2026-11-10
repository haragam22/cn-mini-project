"""P0 Batfish spike (technical.md §11.2). Needs Docker + Batfish on localhost.

Run: .venv/Scripts/python -m pytest -q -m batfish
Snapshot: two routers, one OSPF /30 link, one extended ACL on r2's LAN.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.batfish

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "batfish_spike"


@pytest.fixture(scope="module")
def bf():
    from pybatfish.client.session import Session

    session = Session(host="localhost")
    session.set_network("netarch-p0-spike")
    session.init_snapshot(str(SNAPSHOT), name="spike", overwrite=True)
    return session


def test_init_issues_has_zero_errors(bf):
    issues = bf.q.initIssues().answer().frame()
    # An issue-free snapshot yields an empty, all-float64 frame; cast before .str.
    errors = issues[issues["Type"].astype(str).str.contains("error", case=False)]
    assert errors.empty, errors.to_string()


def test_both_configs_parse(bf):
    status = bf.q.fileParseStatus().answer().frame()
    assert len(status) == 2
    assert set(status["Status"]) == {"PASSED"}, status.to_string()


def test_ospf_session_established(bf):
    sessions = bf.q.ospfSessionCompatibility().answer().frame()
    assert len(sessions) == 2, sessions.to_string()  # one row per direction
    assert set(sessions["Session_Status"]) == {"ESTABLISHED"}, sessions.to_string()


def test_traceroute_permit_and_acl_deny(bf):
    from pybatfish.datamodel.flow import HeaderConstraints

    def disposition(dst_port):
        frame = (
            bf.q.traceroute(
                startLocation="r1[GigabitEthernet0/1]",
                headers=HeaderConstraints(
                    srcIps="10.1.1.10",
                    dstIps="10.2.2.10",
                    ipProtocols=["tcp"],
                    dstPorts=str(dst_port),
                ),
            )
            .answer()
            .frame()
        )
        return {trace.disposition for trace in frame.iloc[0]["Traces"]}

    assert disposition(22) == {"DELIVERED_TO_SUBNET"}
    assert disposition(23) == {"DENIED_OUT"}

"""P0 smoke: the package imports and the `netarch` CLI answers --help."""

import importlib

import pytest
from typer.testing import CliRunner

MODULES = [
    "netarch",
    "netarch.cli",
    "netarch.errors",
    "netarch.models.requirements",
    "netarch.models.decisions",
    "netarch.models.plan",
    "netarch.engines.l1_media",
    "netarch.engines.optics",
    "netarch.engines.topology",
    "netarch.engines.l2_switching",
    "netarch.engines.vlsm",
    "netarch.engines.routing",
    "netarch.engines.vpn",
    "netarch.engines.qos",
    "netarch.engines.security",
    "netarch.explain.builder",
    "netarch.explain.render",
    "netarch.configgen.interface_map",
    "netarch.configgen.render",
    "netarch.verify.selfcheck",
    "netarch.verify.batfish_runner",
    "netarch.verify.checklist",
    "netarch.export.writer",
    "netarch.tui.app",
]


@pytest.mark.parametrize("name", MODULES)
def test_skeleton_module_imports(name):
    importlib.import_module(name)


def test_cli_help_exits_zero():
    from netarch.cli import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "netarch" in result.output.lower() or "usage" in result.output.lower()

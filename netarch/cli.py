"""NetArchitect CLI (Typer), technical.md §10.1.

Exit codes: 0 ok · 1 verification failed · 2 input invalid · 3 design constraint error.
Errors print as a Rich panel (field, value, rule, hint), never a stack trace unless --debug.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netarch.errors import InputValidationError, NetArchError
from netarch.explain.render import render_report
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import Requirements, load_preset, load_requirements_file

PRESETS = ("campus", "metro", "global")

app = typer.Typer(
    name="netarch",
    help="netarch: NetArchitect, a junior network architect in your terminal.",
    invoke_without_command=True,
)
_state = {"debug": False}


def _console(err: bool = False) -> Console:
    stream = sys.stderr if err else sys.stdout
    wide = None if stream.isatty() else 200  # pipes/files: never truncate table cells
    # markup off: user strings such as "[/]" must print literally, never parse (security F1)
    return Console(stderr=err, highlight=False, soft_wrap=True, width=wide, markup=False)


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


@app.callback()
def main(
    ctx: typer.Context,
    debug: Annotated[bool, typer.Option("--debug", help="show stack traces")] = False,
) -> None:
    """netarch: design, explain, configure and verify a network. No command → TUI."""
    _utf8()
    _state["debug"] = debug
    if ctx.invoked_subcommand is None:  # pragma: no cover - interactive
        from netarch.tui.app import run_tui

        run_tui()


def _fail(e: NetArchError, kind: str, code: int) -> typer.Exit:
    if _state["debug"]:
        raise e
    errs = e.errors if isinstance(e, InputValidationError) else [e]
    body = "\n\n".join(f"{x.field} = {x.value!r}\nrule {x.rule_id}: {x.message}\n"
                       f"hint: {x.hint}" for x in errs)
    _console(err=True).print(Panel(body, title=f"{kind} error", border_style="red"))
    return typer.Exit(code)


def _load(preset: str | None, input: str | None) -> Requirements:
    if (preset is None) == (input is None):
        _console(err=True).print("Give exactly one of --preset or --input.")
        raise typer.Exit(2)
    if preset is not None and preset not in PRESETS:
        _console(err=True).print(f"Unknown preset {preset!r}; choose {', '.join(PRESETS)}.")
        raise typer.Exit(2)
    try:
        return load_preset(preset) if preset else load_requirements_file(input or "")
    except InputValidationError as e:
        raise _fail(e, "Input", 2) from None
    except NetArchError as e:
        raise _fail(e, "Input", 2) from None


def _design(req: Requirements) -> NetworkPlan:
    from netarch.engines import design

    try:
        return design(req)
    except NetArchError as e:
        raise _fail(e, "Design", 3) from None


Preset = Annotated[str | None, typer.Option(help="campus | metro | global")]
Input = Annotated[str | None, typer.Option("--input", help="custom JSON file")]
Dialect = Annotated[str, typer.Option(help="pt (Packet Tracer) | full (real IOS / Batfish)")]


@app.command()
def presets() -> None:
    """List the built-in presets."""
    t = Table("preset", "type", "sites", "hosts", "root")
    for name in PRESETS:
        r = load_preset(name)
        t.add_row(name, r.profile_type, str(len(r.sites)),
                  str(sum(g.hosts for s in r.sites for g in s.segments)), r.address_space.root)
    _console().print(t)


@app.command()
def validate(preset: Preset = None, input: Input = None) -> None:
    """Validate an input only (exit 2 with every bad field)."""
    r = _load(preset, input)
    _console().print(f"VALID: {r.profile_name} ({r.profile_type}), {len(r.sites)} sites")


@app.command("design")
def design_cmd(
    preset: Preset = None, input: Input = None,
    as_json: Annotated[bool, typer.Option("--json", help="print plan.json")] = False,
) -> None:
    """Run the whole design and print a summary (or the full plan as JSON)."""
    plan = _design(_load(preset, input))
    if as_json:
        typer.echo(plan.model_dump_json(indent=2))
        return
    c = _console()
    t = Table("hostname", "model", "role", "site", title="Devices")
    for d in plan.devices:
        t.add_row(d.hostname, d.model, d.role, d.site)
    c.print(t)
    k = Table("id", "domain", "choice", title="Key decisions")
    for d in plan.decisions:
        if d.domain in ("topology", "addressing", "routing", "vpn", "qos", "security"):
            k.add_row(d.id, d.domain, d.choice)
    c.print(k)
    for w in plan.warnings:
        c.print(f"WARNING {w}")


@app.command()
def explain(
    preset: Preset = None, input: Input = None,
    id: Annotated[str | None, typer.Option("--id", help="show one decision, e.g. L1-03")] = None,
    domain: Annotated[str | None, typer.Option(help="filter by domain, e.g. media")] = None,
    markdown: Annotated[bool, typer.Option(help="Markdown instead of plain text")] = False,
) -> None:
    """Print the explained design decisions."""
    plan = _design(_load(preset, input))
    decisions = [d for d in plan.decisions
                 if (id is None or d.id == id) and (domain is None or d.domain == domain)]
    if not decisions:
        typer.echo("No decisions match.", err=True)
        raise typer.Exit(2)
    typer.echo(render_report(decisions, "markdown" if markdown else "text"), nl=False)


@app.command()
def plan(preset: Preset = None, input: Input = None) -> None:
    """Print the VLSM addressing table (with wildcards)."""
    p = _design(_load(preset, input))
    ap = p.addressing
    t = Table("kind", "site", "name", "vlan", "subnet", "mask", "wildcard", "gateway", "usable",
              "hosts", "used %", title=f"IP plan {ap.root} (org summary {ap.org_summary})")
    for r in ap.subnets:
        t.add_row(r.kind, r.site or "", r.name, str(r.vlan or ""), r.cidr, r.mask, r.wildcard,
                  r.gateway or "", str(r.usable), str(r.requested), f"{r.utilisation_pct:g}")
    _console().print(t)


@app.command()
def export(
    preset: Preset = None, input: Input = None,
    out: Annotated[str, typer.Option(help="output directory")] = "./output",
    zip_: Annotated[bool, typer.Option("--zip", help="also write the ZIP bundle")] = False,
    dialect: Dialect = "pt",
    only: Annotated[str | None, typer.Option(help="comma list: configs,rationale,ip-plan,"
                                             "plan,checklist,topology,secrets")] = None,
) -> None:
    """Write configs (.txt), rationale.md, ip-plan.csv, plan.json, checklist, topology."""
    from netarch.export.writer import write_all

    if dialect not in ("pt", "full"):
        _console(err=True).print("--dialect must be pt or full.")
        raise typer.Exit(2)
    p = _design(_load(preset, input))
    try:
        paths = write_all(p, Path(out), dialect=dialect, make_zip=zip_,
                          only=tuple(x.strip() for x in only.split(",")) if only else None)
    except ValueError as e:
        _console(err=True).print(str(e))
        raise typer.Exit(2) from None
    except OSError as e:
        if _state["debug"]:
            raise
        _console(err=True).print(Panel(f"--out = {out!r}\ncannot write: {e}\n"
                                       "hint: choose a writable directory.",
                                       title="Export error", border_style="red"))
        raise typer.Exit(2) from None
    for x in paths:
        typer.echo(str(x))
    if any(x.name == "secrets.txt" for x in paths):
        _console(err=True).print("WARNING secrets.txt holds generated passwords/PSKs; keep it "
                                 "out of version control.")


@app.command()
def verify(
    preset: Preset = None, input: Input = None, dialect: Dialect = "pt",
    no_batfish: Annotated[bool, typer.Option("--no-batfish")] = False,
    batfish_host: Annotated[str, typer.Option("--batfish-host")] = "localhost",
    report: Annotated[str, typer.Option(help="where to save batfish-report.md")] =
        "./output/batfish-report.md",
) -> None:
    """Self-check (11 invariants) + Batfish (full dialect, skipped if not reachable)."""
    from netarch.configgen.render import make_secrets, render_all
    from netarch.verify.batfish_runner import run_batfish
    from netarch.verify.selfcheck import all_pass, run_selfcheck

    p = _design(_load(preset, input))
    sec = make_secrets(p)
    results = run_selfcheck(p, render_all(p, dialect, sec))
    t = Table("check", "device", "result", "detail", title=f"Self-check ({dialect})")
    for r in results:
        t.add_row(r.id, r.device, r.status, r.message)
    c = _console()
    c.print(t)
    ok = all_pass(results)
    if no_batfish:
        c.print("BATFISH: skipped (--no-batfish)")
    else:
        bf = run_batfish(p, render_all(p, "full", sec), host=batfish_host)
        c.print(f"BATFISH: {bf.status}")
        if not bf.skipped:
            Path(report).parent.mkdir(parents=True, exist_ok=True)
            Path(report).write_text(bf.report_md(), encoding="utf-8")
            c.print(f"report: {report}")
        for name, status, detail in bf.checks:
            c.print(f"  {status} {name} {detail}")
        ok = ok and (bf.skipped or bf.status == "PASS")
    c.print("SELF-CHECK: " + ("PASS" if all_pass(results) else "FAIL"))
    raise typer.Exit(0 if ok else 1)


@app.command()
def checklist(preset: Preset = None, input: Input = None) -> None:
    """Print the Packet Tracer checklist (devices, cabling, load steps, show commands)."""
    from netarch.verify.checklist import build_checklist

    typer.echo(build_checklist(_design(_load(preset, input))), nl=False)



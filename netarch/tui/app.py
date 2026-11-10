"""Textual TUI (technical.md §10.2–10.3): preset/custom input → design tabs → verify → export.

The TUI only displays what the engines and verifiers produce; all logic lives in netarch/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

from netarch.configgen.render import make_secrets
from netarch.errors import InputValidationError, NetArchError
from netarch.explain.render import render_text
from netarch.models.plan import NetworkPlan
from netarch.models.requirements import load_preset, load_requirements

PRESETS = ("campus", "metro", "global")


def error_lines(e: NetArchError) -> list[str]:
    errs = e.errors if isinstance(e, InputValidationError) else [e]
    return [f"✗ {x.field}: {x.message}  (hint: {x.hint})" for x in errs]


class NetArchApp(App):
    TITLE = "NetArchitect"
    CSS = """
    #bar { height: auto; }
    #errors { color: $error; height: auto; }
    .row { height: auto; }
    Input { width: 40; }
    #whatif-out, #summary, #config-view, #export-out { height: auto; }
    """
    BINDINGS = [("d", "tab('design')", "Design"), ("v", "tab('verify')", "Verify"),
                ("e", "tab('export')", "Export"), ("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.raw: dict[str, Any] | None = None
        self.plan: NetworkPlan | None = None
        self.secrets: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="bar", classes="row"):
            for p in PRESETS:
                yield Button(p.capitalize(), id=f"preset-{p}")
            yield Input(placeholder="custom JSON path", id="json-path")
            yield Button("Load JSON", id="load-json")
        yield Static("", id="errors")
        with TabbedContent(initial="design", id="tabs"):
            with TabPane("Design", id="design"), VerticalScroll():
                yield Static("Pick a preset or load a JSON file.", id="summary")
            with TabPane("Decisions", id="decisions"):
                yield Tree("Decisions", id="tree")
            with TabPane("IP Plan", id="ipplan"):
                yield DataTable(id="iptable")
            with TabPane("What-if", id="whatif"), VerticalScroll():
                yield Select([], id="link-select", prompt="link")
                yield Input(placeholder="distance in metres", id="distance")
                yield Button("Apply", id="apply-distance")
                yield Static("", id="whatif-out")
            with TabPane("Configs", id="configs"), VerticalScroll():
                yield Select([], id="device-select", prompt="device")
                yield Static("", id="config-view")
            with TabPane("Verify", id="verify"), VerticalScroll():
                yield Button("Run self-check", id="run-verify")
                yield DataTable(id="verify-table")
                yield Static("", id="verify-status")
            with TabPane("Export", id="export"), VerticalScroll():
                yield Input(value="./output", id="export-path")
                yield Select([("pt", "pt"), ("full", "full")], value="pt", id="dialect",
                             allow_blank=False)
                yield Checkbox("ZIP all", id="zip")
                yield Button("Export", id="do-export")
                yield Static("", id="export-out")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#iptable", DataTable).add_columns(
            "kind", "site", "name", "vlan", "subnet", "mask", "wildcard", "gateway", "usable",
            "hosts")
        self.query_one("#verify-table", DataTable).add_columns("check", "device", "result",
                                                              "detail")

    def action_tab(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    # --- loading -------------------------------------------------------------------------

    def load_raw(self, raw: dict[str, Any]) -> bool:
        from netarch.engines import design

        err = self.query_one("#errors", Static)
        try:
            req = load_requirements(raw)
            plan = design(req)
        except NetArchError as e:
            err.update("\n".join(error_lines(e)))
            return False
        err.update("")
        self.raw, self.plan = raw, plan
        self.secrets = make_secrets(plan)  # viewer, verify and export show the same keys
        self.show_plan()
        return True

    def load_json(self, path: str) -> bool:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.query_one("#errors", Static).update(f"✗ file: cannot read {path!r}: {e}")
            return False
        return self.load_raw(raw)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("preset-"):
            self.load_raw(load_preset(bid.removeprefix("preset-")).model_dump(mode="json"))
        elif bid == "load-json":
            self.load_json(self.query_one("#json-path", Input).value.strip())
        elif bid == "apply-distance":
            self.apply_distance()
        elif bid == "run-verify":
            self.run_verify()
        elif bid == "do-export":
            self.do_export()

    # --- views ---------------------------------------------------------------------------

    def show_plan(self) -> None:
        p = self.plan
        assert p is not None
        lines = [f"{p.requirements.profile_name} ({p.requirements.profile_type}) — "
                 f"{len(p.devices)} devices, {len(p.decisions)} decisions", ""]
        lines += [f"{d.hostname:<16} {d.model:<10} {d.role}" for d in p.devices]
        lines += ["", "Key choices:"]
        lines += [f"  {d.id} {d.choice}" for d in p.decisions
                  if d.domain in ("topology", "routing", "vpn", "qos")]
        lines += [f"WARNING {w}" for w in p.warnings]
        self.query_one("#summary", Static).update("\n".join(lines))
        tree = self.query_one("#tree", Tree)
        tree.clear()
        doms: dict[str, Any] = {}
        for d in p.decisions:
            node = doms.get(d.domain) or tree.root.add(d.domain, expand=False)
            doms[d.domain] = node
            leaf = node.add(f"{d.id} {d.subject}: {d.choice}")
            for line in render_text(d).splitlines()[1:]:
                leaf.add_leaf(line)
        tree.root.expand()
        t = self.query_one("#iptable", DataTable)
        t.clear()
        for r in p.addressing.subnets:
            t.add_row(r.kind, r.site or "", r.name, str(r.vlan or ""), r.cidr, r.mask,
                      r.wildcard, r.gateway or "", str(r.usable), str(r.requested))
        links = [(f"{lk.a} ↔ {lk.b}", str(i)) for i, lk in enumerate(p.requirements.links)]
        self.query_one("#link-select", Select).set_options(links)
        self.query_one("#device-select", Select).set_options(
            [(d.hostname, d.hostname) for d in p.devices])

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "device-select" and self.plan and isinstance(event.value, str):
            from netarch.configgen.render import render_device

            d = self.plan.device(event.value)
            self.query_one("#config-view", Static).update(
                render_device(self.plan, d, "pt", self.secrets))

    def apply_distance(self) -> None:
        sel = self.query_one("#link-select", Select).value
        text = self.query_one("#distance", Input).value.strip()
        out = self.query_one("#whatif-out", Static)
        if self.raw is None or not isinstance(sel, str):
            out.update("Load a design with links first.")
            return
        try:
            dist = float(text)
        except ValueError:
            out.update(f"✗ distance: {text!r} is not a number")
            return
        raw = json.loads(json.dumps(self.raw))
        lk = raw["links"][int(sel)]
        lk["distance_m"] = dist
        ok = self.load_raw(raw)
        self.query_one("#link-select", Select).value = sel  # reload resets the options
        if not ok:
            out.update("✗ " + str(self.query_one("#errors", Static).render()))
            return
        subj = (lk["a"], lk["b"])
        ds = [d for d in self.plan.decisions if d.domain in ("media", "transceiver")
              and subj[0] in d.subject and subj[1] in d.subject]
        out.update("\n\n".join(render_text(d) for d in ds) or "no link decision")

    def run_verify(self) -> None:
        from netarch.configgen.render import render_all
        from netarch.verify.selfcheck import all_pass, run_selfcheck

        if self.plan is None:
            return
        res = run_selfcheck(self.plan, render_all(self.plan, "pt", self.secrets))
        t = self.query_one("#verify-table", DataTable)
        t.clear()
        for r in res:
            t.add_row(r.id, r.device, ("✓ " if r.status == "PASS" else "✗ ") + r.status,
                      r.message)
        self.query_one("#verify-status", Static).update(
            "SELF-CHECK: " + ("PASS" if all_pass(res) else "FAIL")
            + "   BATFISH: run `netarch verify` with Docker up (not run here)")

    def do_export(self) -> None:
        from netarch.export.writer import write_all

        if self.plan is None:
            return
        dest = self.query_one("#export-path", Input).value.strip() or "./output"
        dialect = str(self.query_one("#dialect", Select).value)
        z = self.query_one("#zip", Checkbox).value
        try:
            paths = write_all(self.plan, Path(dest), dialect=dialect, make_zip=z,
                              secrets=self.secrets)
        except OSError as e:
            self.query_one("#export-out", Static).update(f"✗ export failed: {e}")
            return
        self.query_one("#export-out", Static).update("\n".join(map(str, paths)))


def run_tui() -> None:  # pragma: no cover - interactive
    NetArchApp().run()

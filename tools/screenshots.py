"""Capture README screenshots of the Textual TUI (headless, SVG).

Run: .venv/Scripts/python tools/screenshots.py   → docs/screenshots/*.svg
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from textual.widgets import Input, Select, Tree

from netarch.tui.app import NetArchApp

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
SIZE = (140, 42)


async def capture() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []
    app = NetArchApp()
    async with app.run_test(size=SIZE) as pilot:

        async def shot(name: str) -> None:
            await pilot.pause()
            shots.append(Path(app.save_screenshot(filename=f"{name}.svg", path=str(OUT))))

        await shot("01-home")
        await pilot.click("#preset-metro")
        await shot("02-design-summary-metro")
        app.action_tab("decisions")
        tree = app.query_one("#tree", Tree)
        for node in tree.root.children:
            if str(node.label) in ("routing", "qos"):
                node.expand()
                if node.children:
                    node.children[0].expand()
        await shot("03-decisions-metro")
        app.action_tab("ipplan")
        await shot("04-ip-plan-metro")
        app.action_tab("whatif")
        app.query_one("#link-select", Select).value = "1"
        app.query_one("#distance", Input).value = "36000"
        app.apply_distance()
        await shot("05-what-if-36km")
        await pilot.click("#preset-global")
        app.action_tab("configs")
        app.query_one("#device-select", Select).value = "rtr-delhi"
        await shot("06-config-viewer-global")
        app.action_tab("verify")
        app.run_verify()
        await shot("07-verify-global")
        app.action_tab("export")
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:  # relative path: no local user dirs shown
            os.chdir(tmp)
            try:
                app.query_one("#export-path", Input).value = "output"
                app.do_export()
                await shot("08-export-global")
            finally:
                os.chdir(cwd)
    return shots


if __name__ == "__main__":
    for p in asyncio.run(capture()):
        print(p)

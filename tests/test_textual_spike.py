"""P0 Textual spike: the demo app mounts tabs, a DataTable and a button (headless pilot)."""

import asyncio
import importlib.util
from pathlib import Path

from textual.widgets import Button, DataTable, TabbedContent

DEMO = Path(__file__).resolve().parents[1] / "spikes" / "textual_demo.py"


def load_demo():
    spec = importlib.util.spec_from_file_location("textual_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_renders_tabs_table_and_button():
    async def run():
        app = load_demo().DemoApp()
        async with app.run_test() as pilot:
            tabs = app.query_one(TabbedContent)
            assert tabs.tab_count == 2
            table = app.query_one(DataTable)
            assert table.row_count >= 3
            assert len(table.columns) == 3
            assert app.query_one(Button)
            tabs.active = "about"
            await pilot.pause()
            assert tabs.active == "about"

    asyncio.run(run())


def test_demo_button_adds_a_row():
    async def run():
        app = load_demo().DemoApp()
        async with app.run_test() as pilot:
            table = app.query_one(DataTable)
            before = table.row_count
            await pilot.click("#add")
            await pilot.pause()
            assert table.row_count == before + 1

    asyncio.run(run())

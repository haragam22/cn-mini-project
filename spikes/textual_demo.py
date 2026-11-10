"""P0 Textual spike: tabs + DataTable + button. Run: .venv/Scripts/python spikes/textual_demo.py"""

from textual.app import App, ComposeResult
from textual.widgets import Button, DataTable, Footer, Header, Static, TabbedContent, TabPane

ROWS = [("LR", "10 km", "6.2 dB"), ("ER", "40 km", "11 dB"), ("ZR", "80 km", "23 dB")]


class DemoApp(App):
    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="optics"):
            with TabPane("Optics", id="optics"):
                yield DataTable(id="table")
                yield Button("Add row", id="add")
            with TabPane("About", id="about"):
                yield Static("NetArchitect P0 Textual spike")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Optic", "Reach", "Budget")
        table.add_rows(ROWS)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.query_one(DataTable).add_row("SR", "400 m", "n/a")


if __name__ == "__main__":
    DemoApp().run()

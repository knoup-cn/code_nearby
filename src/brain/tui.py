"""TUI (Text User Interface) mode for Brain."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from brain import config
from brain.operations.config import clear_config


class ConfirmDialog(ModalScreen):
    """Confirmation dialog."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.message)
            yield Button("✓ Confirm", id="confirm", variant="error")
            yield Button("✗ Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_dismiss(self) -> None:
        """Handle Escape key."""
        self.dismiss(False)


class BrainApp(App):
    """Brain knowledge base TUI."""

    CSS = """
    Screen {
        align: center top;
    }

    #main {
        width: 80;
        height: 1fr;
        border: thick $primary;
        padding: 2 4;
        background: $surface;
        margin-top: 1;
    }

    #title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 2;
    }

    #status {
        text-align: center;
        padding: 1;
        background: $panel;
        border: round $panel;
        margin-bottom: 3;
    }

    #status:hover {
        background: $panel-lighten-1;
    }

    .section {
        text-style: bold;
        color: $accent;
        margin-top: 2;
        margin-bottom: 1;
    }

    Label {
        margin-bottom: 1;
    }

    Input {
        margin-bottom: 2;
    }

    Button {
        margin-top: 1;
        width: 100%;
    }

    #dialog {
        width: 50;
        height: auto;
        background: $panel;
        border: thick $error;
        padding: 2;
    }

    .ok { color: $success; }
    .err { color: $error; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "blur", "Unfocus"),
    ]
    status = reactive("Loading...")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with ScrollableContainer(id="main"):
            yield Static("🧠 Brain Knowledge Base", id="title")
            yield Label(self.status, id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def watch_status(self, new_status: str) -> None:
        """Update status label when reactive variable changes."""
        try:
            label = self.query_one("#status", Label)
            label.update(new_status)
        except Exception:
            pass

    def action_blur(self) -> None:
        """Remove focus from current widget."""
        self.screen.set_focus(None)

    def _refresh(self) -> None:
        """Refresh UI showing knowledge base status."""
        container = self.query_one("#main", ScrollableContainer)
        # Remove dynamic content only (keep title and status)
        for widget in list(container.children)[2:]:
            widget.remove()

        self._show_dashboard(container)
        self._update_status()

    def _show_dashboard(self, container: ScrollableContainer) -> None:
        """Show knowledge base dashboard."""
        kb_path = config.get_kb_path()

        container.mount(
            Static("📁 Knowledge Base", classes="section"),
            Label(str(kb_path)),
            Static("", classes="section"),
            Static("💡 Run 'brain analyze <project>' to build a search index.", classes="section"),
            Static("   'brain search <query>' to query the index."),
            Button("⚙️ Change KB Path", id="change_path"),
            Button("🔄 Reset to Default", id="reset", variant="error"),
        )

    def _update_status(self) -> None:
        """Update status bar."""
        kb_path = config.get_kb_path()
        self.status = f"KB: {kb_path.name} ({kb_path})"

    def _set_status(self, msg: str, error: bool = False) -> None:
        """Set status message with styling."""
        self.status = msg
        label = self.query_one("#status", Label)
        label.set_class(error, "err")
        label.set_class(not error, "ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "change_path":
            self._handle_change_path()
        elif btn_id == "reset":
            self.push_screen(
                ConfirmDialog("⚠️ Reset KB path to default (~/.brain)?"),
                self._handle_reset,
            )

    def _handle_change_path(self) -> None:
        """Prompt for a new KB path."""
        self.push_screen(
            _PathInputDialog(),
            lambda new_path: self._apply_new_path(new_path),
        )

    def _apply_new_path(self, new_path: str | None) -> None:
        """Apply the new KB path."""
        if not new_path:
            return
        path = Path(new_path.strip()).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._set_status(f"✗ Cannot create directory: {e}", True)
            return
        config.save_config({"local_path": str(path)})
        self._refresh()
        self._set_status(f"✓ KB path updated: {path}")

    def _handle_reset(self, confirmed: bool) -> None:
        """Reset KB path to default."""
        if not confirmed:
            return
        clear_config()
        self._refresh()
        self._set_status("✓ Reset to default")


class _PathInputDialog(ModalScreen):
    """Dialog to input a new KB path."""

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Enter new knowledge base path:")
            yield Input(placeholder=str(Path.home() / ".brain"), id="kb_path_input")
            yield Button("✓ Save", id="save", variant="primary")
            yield Button("✗ Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            value = self.query_one("#kb_path_input", Input).value.strip()
            self.dismiss(value if value else None)
        else:
            self.dismiss(None)

    def action_dismiss(self) -> None:
        """Handle Escape key."""
        self.dismiss(None)


def run() -> None:
    """Launch TUI interface."""
    BrainApp().run()

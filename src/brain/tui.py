"""TUI (Text User Interface) mode for Brain."""
from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from brain import operations


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
    status = reactive("Not initialized")

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
        """Refresh UI based on configuration state."""
        cfg = operations.get_status()
        container = self.query_one("#main", ScrollableContainer)
        # Remove dynamic content only (keep title and status)
        for widget in list(container.children)[2:]:
            widget.remove()

        if cfg:
            self._show_configured(container, cfg)
        else:
            self._show_init_form(container)

        self._update_status()

    def _show_init_form(self, container: ScrollableContainer) -> None:
        """Show initialization form."""
        default_kb_path = str(Path.home() / "brain-vault")

        container.mount(
            Label("Initialize your knowledge base"),
            Static("📁 Knowledge Base Local Path", classes="section"),
            Input(placeholder=default_kb_path, value=default_kb_path, id="local_path"),
            Static("📦 Knowledge Base Git Repository", classes="section"),
            Input(placeholder="https://github.com/user/repo.git", id="git_repo"),
            Button("🚀 Initialize", id="init", variant="primary"),
        )

    def _show_configured(self, container: ScrollableContainer, cfg: dict) -> None:
        """Show configured state."""
        local_path = cfg.get("local_path", "N/A")
        git_repo = cfg.get("git_repo", "N/A")

        container.mount(
            Static("📁 Knowledge Base Local Path", classes="section"),
            Label(local_path),
            Static("📦 Knowledge Base Git Repository", classes="section"),
            Label(git_repo),
            Button("⚙️ Reconfigure", id="reconfig"),
            Button("❌ Clear", id="clear", variant="error"),
        )

    def _update_status(self) -> None:
        """Update status bar."""
        cfg = operations.get_status()
        if not cfg:
            self.status = "Not initialized"
        else:
            local_path = cfg.get("local_path", "")
            vault = Path(local_path).name if local_path else "N/A"
            git = "synced" if cfg.get("git_repo") else "not synced"
            self.status = f"{vault} ({git})"

    def _set_status(self, msg: str, error: bool = False) -> None:
        """Set status message with styling."""
        self.status = msg
        label = self.query_one("#status", Label)
        label.set_class(error, "err")
        label.set_class(not error, "ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "init":
            self._handle_init()
        elif btn_id == "reconfig":
            operations.clear_config()
            self._refresh()
            self._set_status("Ready to reconfigure")
        elif btn_id == "clear":
            self.push_screen(ConfirmDialog("⚠️ Clear all?"), self._handle_clear)

    def _handle_init(self) -> None:
        """Handle initialization."""
        local_input = self.query_one("#local_path", Input)
        git_input = self.query_one("#git_repo", Input)

        local_path = local_input.value.strip()
        kb_git_repo = git_input.value.strip() or None

        if not local_path:
            self._set_status("✗ Knowledge base local path required", True)
            return

        kb_path = Path(local_path).expanduser().resolve()

        if operations.needs_overwrite(kb_path):
            self.push_screen(
                ConfirmDialog("⚠️ Directory not empty. Overwrite?"),
                lambda confirmed: self._complete_init(kb_git_repo, kb_path, confirmed),
            )
        else:
            self._complete_init(kb_git_repo, kb_path, overwrite=False)

    def _complete_init(self, git_repo: str | None, kb_path: Path, overwrite: bool) -> None:
        """Complete initialization after confirmation."""
        if operations.needs_overwrite(kb_path) and not overwrite:
            self._set_status("Initialization cancelled")
            return

        success, msg = operations.init_config(git_repo, kb_path, overwrite)

        if success:
            self._refresh()
        else:
            self._set_status(f"✗ {msg}", True)

    def _handle_clear(self, confirmed: bool) -> None:
        """Handle clear configuration."""
        if confirmed:
            operations.clear_config()
            self._refresh()
            self._set_status("✓ Cleared")


def run() -> None:
    """Launch TUI interface."""
    BrainApp().run()

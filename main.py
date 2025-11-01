# main.py
import os
from textual import events, on
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Button, Input, Label, Static
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen

from db import init_db, get_db
from models import BGPSession
from device import sync_cisco_xr, sync_nokia_sros, detect_device_type
from sqlalchemy.exc import IntegrityError
from logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_USERNAME = os.getenv("BGP_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("BGP_PASSWORD", "")


# ──────────────────────────────────────────────────────────────
#  Add‑Session Modal – now uses device_fqdn
# ──────────────────────────────────────────────────────────────
class AddSessionModal(ModalScreen):
    CSS = """
    AddSessionModal .modal {
        width: 75;
        height: 38;
        border: thick $primary;
        align: center middle;
    }
    AddSessionModal VerticalScroll { padding: 1 2; height: 1fr; }
    AddSessionModal Input { margin: 0 0 1 0; width: 100%; }
    AddSessionModal .title { text-style: bold; margin: 1 0; text-align: center; }
    """

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Label("Add BGP Session", classes="title")
            with VerticalScroll():
                yield Input(placeholder="Neighbor IP (e.g. 10.1.1.1)", id="neighbor_ip")
                yield Input(placeholder="Remote AS (e.g. 65001)", id="remote_as")
                yield Input(
                    placeholder="Device FQDN (e.g. r1.core.example.com)",
                    id="device_fqdn",
                )
                yield Input(placeholder="Local AS (e.g. 65000)", id="local_as")
                yield Input(placeholder="Local IP (e.g. 192.168.1.1)", id="local_ip")
                yield Input(placeholder="Description (optional)", id="description")
                yield Label("")  # spacer
                with Horizontal():
                    yield Button("Save", id="save")
                    yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        logger.debug("Add modal cancelled")
        self.dismiss()

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        data = {
            "neighbor_ip": self.query_one("#neighbor_ip").value.strip(),
            "remote_as": self.query_one("#remote_as").value.strip(),
            "device_fqdn": self.query_one("#device_fqdn").value.strip(),
            "local_as": self.query_one("#local_as").value.strip(),
            "local_ip": self.query_one("#local_ip").value.strip(),
            "description": self.query_one("#description").value.strip(),
        }
        logger.info(
            f"Add modal saved: {data['neighbor_ip']} AS{data['remote_as']} @ {data['device_fqdn']}"
        )
        self.dismiss(data)


# ──────────────────────────────────────────────────────────────
#  Main App
# ──────────────────────────────────────────────────────────────
class BGPTUI(App):
    CSS = """
    .title { text-style: bold; margin: 1; text-align: center; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        ("a", "add_session", "Add"),
        ("s", "sync_all", "Sync All"),
        ("r", "refresh", "Refresh"),
        ("d", "delete_selected", "Delete"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Container():
            yield Static("BGP Session Manager", classes="title")
            yield DataTable(id="bgp_table")
            with Horizontal():
                yield Button("Add Session", id="add")
                yield Button("Sync All", id="sync")
                yield Button("Refresh", id="refresh")
                yield Button("Delete", id="delete")

    def on_mount(self) -> None:
        logger.info("TUI started")
        table = self.query_one(DataTable)
        table.add_columns(
            "ID",
            "Neighbor IP",
            "Remote AS",
            "Local AS",
            "Local IP",
            "Description",
            "Device FQDN",  # ← now shows FQDN
            "Type",
            "Status",
            "State",
            "Last Updated",
        )
        init_db()
        self.refresh_table()

    def refresh_table(self) -> None:
        logger.debug("Refreshing table view")
        with get_db() as db:
            sessions = db.query(BGPSession).all()

        table = self.query_one(DataTable)
        table.clear()
        for s in sessions:
            color = {"Up": "green", "Down": "red"}.get(s.status, "yellow")
            table.add_row(
                s.id,
                s.neighbor_ip,
                str(s.remote_as),
                str(s.local_as) if s.local_as else "-",
                s.local_ip or "-",
                s.description or "-",
                s.device_fqdn,  # ← FQDN
                s.device_type.replace("_", " ").title(),
                f"[{color}]{s.status}[/]",
                s.session_state,
                s.last_updated.strftime("%Y-%m-%d %H:%M"),
            )
        logger.info(f"Table refreshed: {len(sessions)} sessions")

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------
    @on(Button.Pressed, "#add")
    def btn_add(self) -> None:
        self.push_screen(AddSessionModal(), self.handle_add_session)

    @on(Button.Pressed, "#refresh")
    def btn_refresh(self) -> None:
        self.refresh_table()

    @on(Button.Pressed, "#delete")
    def btn_delete(self) -> None:
        self.action_delete_selected()

    def action_add_session(self) -> None:
        self.btn_add()

    def action_sync_all(self) -> None:
        logger.info("Sync All initiated by user")
        self.run_worker(self.sync_all_sessions, thread=True)

    def action_refresh(self) -> None:
        self.btn_refresh()

    def action_delete_selected(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is None:
            self.notify("No row selected", severity="warning")
            return

        row = table.get_row_at(table.cursor_row)
        session_id = row[0]
        logger.info(f"Deleting session ID {session_id}")

        with get_db() as db:
            sess = db.get(BGPSession, session_id)
            if sess:
                db.delete(sess)
                db.commit()
                logger.info(f"Deleted session {sess.neighbor_ip}")
            else:
                logger.error(f"Session ID {session_id} not found")

        self.refresh_table()
        self.notify("Session deleted")

    # ------------------------------------------------------------------
    # Add handler – saves device_fqdn
    # ------------------------------------------------------------------
    def handle_add_session(self, result: dict | None) -> None:
        if not result:
            return

        if not all([result["neighbor_ip"], result["remote_as"], result["device_fqdn"]]):
            self.notify(
                "Neighbor IP, Remote AS, and Device FQDN are required", severity="error"
            )
            return

        try:
            remote_as = int(result["remote_as"])
        except ValueError:
            self.notify("Remote AS must be an integer", severity="error")
            return

        try:
            local_as = int(result["local_as"]) if result["local_as"] else 0
        except ValueError:
            self.notify("Local AS must be an integer", severity="error")
            return

        try:
            with get_db() as db:
                new_s = BGPSession(
                    neighbor_ip=result["neighbor_ip"],
                    remote_as=remote_as,
                    local_as=local_as,
                    local_ip=result["local_ip"],
                    description=result["description"],
                    device_fqdn=result["device_fqdn"],  # ← FQDN
                    device_type="unknown",
                    status="Unknown",
                )
                db.add(new_s)
                db.commit()
                logger.info(
                    f"Added new session: {result['neighbor_ip']} AS{remote_as} @ {result['device_fqdn']}"
                )
        except IntegrityError:
            db.rollback()
            self.notify("Neighbor IP already exists", severity="error")
            return

        self.refresh_table()
        self.notify("Session added")

    # ------------------------------------------------------------------
    # Sync – uses device_fqdn (Netmiko resolves DNS)
    # ------------------------------------------------------------------
    async def sync_all_sessions(self) -> None:
        logger.info("Starting background sync")
        self.notify("Starting sync…")

        with get_db() as db:
            devices = db.query(BGPSession.device_fqdn).distinct().all()

        for (device_fqdn,) in devices:
            username = os.getenv("BGP_USERNAME", DEFAULT_USERNAME)
            if not username:
                username = self.ask(f"Username for {device_fqdn}: ")

            password = os.getenv("BGP_PASSWORD", DEFAULT_PASSWORD)
            if not password:
                password = self.ask(f"Password for {device_fqdn}: ", password=True)

            try:
                dev_type = detect_device_type(device_fqdn, username, password)
                logger.info(f"Syncing {device_fqdn} as {dev_type}")
                if dev_type == "cisco_xr":
                    sync_cisco_xr(device_fqdn, username, password, get_db)
                elif dev_type == "nokia_sros":
                    sync_nokia_sros(device_fqdn, username, password, get_db)
                self.notify(f"Synced {device_fqdn}")
            except Exception as e:
                msg = f"Sync failed {device_fqdn}: {e}"
                logger.error(msg, exc_info=True)
                self.notify(msg, severity="error")

        self.refresh_table()
        self.notify("Sync complete")

    def ask(self, prompt: str, password: bool = False) -> str:
        from getpass import getpass

        return getpass(prompt) if password else input(prompt)


if __name__ == "__main__":
    BGPTUI().run()

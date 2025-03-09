import asyncio
import dataclasses
import datetime
import math
import os
from enum import IntEnum
from pathlib import Path
from typing import Callable, Awaitable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Header, Log, ProgressBar, Label, Switch, DataTable, ContentSwitcher, Button
from textual.widgets._data_table import RowKey, ColumnKey


class ScanStateStatus(IntEnum):
    waiting = 1
    connected = 2
    receiving = 3
    done = 4
    lost = 5
    error = 6


@dataclasses.dataclass
class ScanState:
    status: ScanStateStatus = ScanStateStatus.waiting

    id: str | None = None
    directory: Path | None = None
    log_path: Path | None = None
    start_time: float = dataclasses.field(default_factory=lambda: datetime.datetime.now().timestamp())
    end_time: float | None = None
    gps_origin: tuple[float, float, float] | None = None

    webrtc_rtt: float | None = None
    webrtc_turn: bool | None = None
    last_client_frame_epoch_time: float | None = None
    client_gps_fix: str | None = None
    client_sat_num: int | None = None

    frames_received: int = 0
    frames_corrupted: int = 0
    images_integrated: int = 0


class SkymapScanTui(App):
    TITLE = "SkyMap Controller"
    CSS = """
    #progress {
        align: center middle;
        height: 3;
    }
    
    #status_label {
        width: auto;
        margin-right: 1;
        margin-left: 1;
    }
    
    #active_label {
        height: 3;
        content-align: center middle;
        width: auto;
    }
    
    Switch {
        height: auto;
        width: auto;
    }
    
    .action {
        align: center middle;
        dock: right;
        height: auto;
        width: auto;
    }
    
    #buttons {
        height: 3;
        width: auto;
    }
    
    Log {
        margin-top: 1;
    }
    """

    def __init__(
        self,
        *args,
        scan_instance: Callable[[ScanState], Awaitable[None]],
        **kwargs,
    ):
        self.scan_state: ScanState | None = None
        self.create_scan_instance = scan_instance
        self.scan_instance_task: Awaitable[None] | None = None
        self.log_offset = 0
        self.log_inode: str | None = None
        self.unknown_cell = Text("-", style="dim italic grey")

        self.sess_row_keys: list[RowKey] | None = None
        self.sess_col_keys: list[ColumnKey] | None = None
        self.conn_col_keys: list[ColumnKey] | None = None
        self.conn_row_keys: list[RowKey] | None = None
        self.recon_col_keys: list[ColumnKey] | None = None
        self.recon_row_keys: list[RowKey] | None = None

        super().__init__(*args, **kwargs)

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Header(show_clock=True)
            with Horizontal(id="progress"):
                yield ProgressBar(total=int(ScanStateStatus.done), show_eta=False, show_percentage=False)
                yield Label("status", variant="primary", id="status_label")
                yield Horizontal(Label("scanning", id="active_label"), Switch(id="action"), classes="action")
            with Horizontal(id="buttons"):
                yield Button("Session", id="dt-session")
                yield Button("Connection", id="dt-connection")
                yield Button("Reconstruction", id="dt-reconstruction")
            with ContentSwitcher(initial="dt-session"):
                yield DataTable(id="dt-session")
                yield DataTable(id="dt-connection")
                yield DataTable(id="dt-reconstruction")
            yield Log(max_lines=1000)

    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.query(Button).filter("#dt-session").first().focus()

        layout = [("key", 25), ("value", 100)]

        session_rows = ["ID", "Output Path", "Start Time", "End Time", "Origin (lat, lon, alt [m])"]
        dt_session = self.query_one("#dt-session", DataTable)
        self.sess_col_keys = [dt_session.add_column(n, width=w) for n, w in layout]
        self.sess_row_keys = [dt_session.add_row(row, self.unknown_cell) for row in session_rows]

        conn_rows = ["RTT", "TURN relay", "GPS fix Type", "GPS satellites", "Client Last Seen"]
        dt_connection = self.query_one("#dt-connection", DataTable)
        self.conn_col_keys = [dt_connection.add_column(n, width=w) for n, w in layout]
        self.conn_row_keys = [dt_connection.add_row(row, self.unknown_cell) for row in conn_rows]

        recon_rows = ["Frames Received", "Frames Corrupted", "Images Integrated"]
        dt_reconstruction = self.query_one("#dt-reconstruction", DataTable)
        self.recon_col_keys = [dt_reconstruction.add_column(n, width=w) for n, w in layout]
        self.recon_row_keys = [dt_reconstruction.add_row(row, self.unknown_cell) for row in recon_rows]

        self.set_interval(1, self.update)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.query_one(ContentSwitcher).current = event.button.id

    async def on_switch_changed(self, event: Switch.Changed):
        if event.switch.value and self.scan_instance_task is not None:
            self.exit(return_code=1, message="Scan instance is already running")
            return
        if not event.switch.value and self.scan_instance_task is None:
            self.exit(return_code=1, message="Scan instance is not running")
            return
        if event.switch.value:
            log = self.query_one(Log)
            log.clear()
            self.scan_state = ScanState()
            self.scan_instance_task = asyncio.create_task(self.create_scan_instance(self.scan_state))
        else:
            try:
                self.scan_instance_task.cancel()
                await asyncio.wait_for(self.scan_instance_task, timeout=10)
            except asyncio.TimeoutError:
                self.exit(return_code=1, message="Scan instance could not be cancelled")
                return
            finally:
                self.scan_instance_task = None

    def update(self):
        status_label = self.query_one(Label)
        if self.scan_state is None:
            status_label.update("not started")
            status_label.classes = ["disabled"]
            return
        status_label.update(self.scan_state.status.name)
        progress_bar = self.query_one(ProgressBar)
        if self.scan_state.status > ScanStateStatus.done:
            progress_bar.progress = 0
            status_label.classes = ["error"]
        else:
            progress_bar.progress = self.scan_state.status.value
            status_label.classes = ["primary"]

        dt_session = self.query_one("#dt-session", DataTable)
        if self.scan_state.id is not None:
            dt_session.update_cell(self.sess_row_keys[0], self.sess_col_keys[1], self.scan_state.id)
        else:
            dt_session.update_cell(self.sess_row_keys[0], self.sess_col_keys[1], self.unknown_cell)
        if self.scan_state.directory is not None:
            dt_session.update_cell(
                self.sess_row_keys[1],
                self.sess_col_keys[1],
                self.scan_state.directory,
            )
        else:
            dt_session.update_cell(self.sess_row_keys[1], self.sess_col_keys[1], self.unknown_cell)
        if self.scan_state.start_time is not None:
            dt_session.update_cell(
                self.sess_row_keys[2],
                self.sess_col_keys[1],
                datetime.datetime.fromtimestamp(self.scan_state.start_time).strftime("%Y-%m-%d %H:%M:%S"),
            )
        else:
            dt_session.update_cell(self.sess_row_keys[2], self.sess_col_keys[1], self.unknown_cell)
        if self.scan_state.end_time is not None:
            dt_session.update_cell(
                self.sess_row_keys[3],
                self.sess_col_keys[1],
                datetime.datetime.fromtimestamp(self.scan_state.end_time).strftime("%Y-%m-%d %H:%M:%S"),
            )
        else:
            dt_session.update_cell(self.sess_row_keys[3], self.sess_col_keys[1], self.unknown_cell)
        if self.scan_state.gps_origin is not None:
            dt_session.update_cell(
                self.sess_row_keys[4],
                self.sess_col_keys[1],
                f"({self.scan_state.gps_origin[0]:.4f}, {self.scan_state.gps_origin[1]:.4f}, {self.scan_state.gps_origin[2]:.4f})",
            )
        else:
            dt_session.update_cell(self.sess_row_keys[4], self.sess_col_keys[1], self.unknown_cell)

        dt_conn = self.query_one("#dt-connection", DataTable)
        if self.scan_state.webrtc_rtt is not None:
            dt_conn.update_cell(self.conn_row_keys[0], self.conn_col_keys[1], f"{self.scan_state.webrtc_rtt:.2f} ms")
        else:
            dt_conn.update_cell(self.conn_row_keys[0], self.conn_col_keys[1], self.unknown_cell)
        if self.scan_state.webrtc_turn is not None:
            dt_conn.update_cell(
                self.conn_row_keys[1],
                self.conn_col_keys[1],
                "🗸" if self.scan_state.webrtc_turn else "❌",
            )
        else:
            dt_conn.update_cell(self.conn_row_keys[1], self.conn_col_keys[1], self.unknown_cell)
        if self.scan_state.client_gps_fix is not None:
            dt_conn.update_cell(self.conn_row_keys[2], self.conn_col_keys[1], Text(self.scan_state.client_gps_fix))
        else:
            dt_conn.update_cell(self.conn_row_keys[2], self.conn_col_keys[1], self.unknown_cell)
        if self.scan_state.client_sat_num is not None:
            dt_conn.update_cell(self.conn_row_keys[3], self.conn_col_keys[1], str(self.scan_state.client_sat_num))
        else:
            dt_conn.update_cell(self.conn_row_keys[3], self.conn_col_keys[1], self.unknown_cell)
        if self.scan_state.last_client_frame_epoch_time is not None:
            dt_conn.update_cell(
                self.conn_row_keys[4],
                self.conn_col_keys[1],
                f"{math.ceil(datetime.datetime.now().timestamp() - self.scan_state.last_client_frame_epoch_time)} seconds ago",
            )
        else:
            dt_conn.update_cell(self.conn_row_keys[4], self.conn_col_keys[1], self.unknown_cell)

        dt_reconstruction = self.query_one("#dt-reconstruction", DataTable)
        dt_reconstruction.update_cell(
            self.recon_row_keys[0], self.recon_col_keys[1], str(self.scan_state.frames_received)
        )
        dt_reconstruction.update_cell(
            self.recon_row_keys[1], self.recon_col_keys[1], str(self.scan_state.frames_corrupted)
        )
        dt_reconstruction.update_cell(
            self.recon_row_keys[2], self.recon_col_keys[1], str(self.scan_state.images_integrated)
        )

        log = self.query_one(Log)
        if self.scan_state is None or self.scan_state.log_path is None:
            log.disabled = True
            log.clear()
            return
        try:
            log.disabled = False
            fileinfo = os.stat(self.scan_state.log_path)
            if self.log_inode != fileinfo.st_ino:
                self.log_inode = fileinfo.st_ino
                self.log_offset = 0
            with open(self.scan_state.log_path, "r") as file:
                file.seek(self.log_offset)
                logs = file.read()
                self.log_offset = file.tell()
                log.write(logs, scroll_end=True)
        except:
            return


if __name__ == "__main__":

    async def scan_instance(scan_state: ScanState):
        pass

    app = SkymapScanTui(scan_instance=scan_instance)
    app.run()

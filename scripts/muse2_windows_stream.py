"""Windows용 Muse 2 BrainFlow 스트리밍 GUI.

Bluetooth로 페어링한 Muse 2 헤드셋에 연결해 EEG 데이터를 수집하고 CSV 파일로
저장하는 간단한 그래픽 인터페이스를 제공합니다. Raspberry Pi에서 사용하던 워크
플로우를 Windows에서도 손쉽게 재현할 수 있도록, BrainFlow 설정과 연결 과정을
GUI에서 직접 제어할 수 있게 했습니다.

2024년 요구 사항에 맞춰 BlueMuse 오픈 소스 도구의 원격 제어 기능을 통합해,
Windows Bluetooth 설정에서 Muse 2를 직접 추가할 수 없을 때 BlueMuse를 실행하고
헤드셋을 검색/연결하는 워크플로우도 지원합니다.
"""

from __future__ import annotations

import csv
import json
import queue
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib import error, request

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from brainflow.board_shim import BoardIds, BoardShim, BrainFlowError, BrainFlowInputParams


class BlueMuseError(RuntimeError):
    """BlueMuse 원격 제어 도중 발생한 문제."""


@dataclass
class BlueMuseDevice:
    """BlueMuse가 보고한 Muse 디바이스 상태."""

    address: str
    name: str
    paired: bool
    connected: bool

    def label(self) -> str:
        flags: list[str] = []
        if self.connected:
            flags.append("connected")
        if self.paired and not self.connected:
            flags.append("paired")
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"{self.name or self.address}{suffix}"


class BlueMuseClient:
    """간단한 BlueMuse REST 원격 제어 클라이언트."""

    _DEFAULT_ENDPOINTS = {
        "status": "/status",
        "devices": "/devices",
        "start_scan": "/devices/scan/start",
        "stop_scan": "/devices/scan/stop",
        "connect": "/devices/connect",
        "disconnect": "/devices/disconnect",
        "disconnect_all": "/devices/disconnect_all",
    }

    def __init__(self, base_url: str = "http://127.0.0.1:5000") -> None:
        self._base_url = base_url.rstrip("/") or "http://127.0.0.1:5000"
        self._endpoints = dict(self._DEFAULT_ENDPOINTS)

    @property
    def base_url(self) -> str:
        return self._base_url

    def set_base_url(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/") or "http://127.0.0.1:5000"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, payload: Optional[dict] = None, timeout: float = 5.0):
        url = f"{self._base_url}{path}" if path.startswith("/") else f"{self._base_url}/{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, method=method.upper())
        if data is not None:
            req.add_header("Content-Type", "application/json")

        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
                if not raw:
                    return None
                if "json" in content_type.lower():
                    return json.loads(raw)
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except error.HTTPError as err:
            raise BlueMuseError(f"{method.upper()} {path} 실패 ({err.code}): {err.reason}") from err
        except error.URLError as err:
            raise BlueMuseError(
                f"BlueMuse 원격 API({self._base_url})에 연결할 수 없습니다: {err.reason}"
            ) from err

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------
    def status(self) -> dict:
        response = self._request("GET", self._endpoints["status"])
        if response is None:
            raise BlueMuseError("BlueMuse 상태 응답이 비어 있습니다.")
        if isinstance(response, str):
            return {"message": response}
        if isinstance(response, dict):
            return response
        raise BlueMuseError(f"알 수 없는 상태 응답 형식: {type(response).__name__}")

    def list_devices(self) -> list[BlueMuseDevice]:
        response = self._request("GET", self._endpoints["devices"])
        if isinstance(response, dict):
            devices = response.get("devices") or response.get("result") or response.get("data") or []
        elif isinstance(response, list):
            devices = response
        elif response is None:
            devices = []
        else:
            raise BlueMuseError(f"알 수 없는 장치 목록 응답 형식: {type(response).__name__}")

        parsed: list[BlueMuseDevice] = []
        for entry in devices:
            if not isinstance(entry, dict):
                continue
            address = (
                str(entry.get("mac"))
                or str(entry.get("address"))
                or str(entry.get("device_id"))
                or str(entry.get("identifier"))
            )
            if not address or address == "None":
                continue
            name = (
                str(entry.get("name"))
                or str(entry.get("alias"))
                or str(entry.get("label"))
                or "Muse"
            )
            connected_raw = (
                entry.get("connected")
                or entry.get("is_connected")
                or entry.get("connection_state")
                or entry.get("status")
            )
            if isinstance(connected_raw, bool):
                connected = connected_raw
            else:
                connected_text = str(connected_raw or "").lower()
                connected = connected_text in {"true", "1", "connected", "yes", "online"}
                if not connected and connected_text.startswith("connected"):
                    connected = True

            paired_raw = (
                entry.get("paired")
                or entry.get("bonded")
                or entry.get("is_paired")
                or entry.get("pairing_state")
            )
            if isinstance(paired_raw, bool):
                paired = paired_raw
            else:
                paired_text = str(paired_raw or "").lower()
                paired = paired_text in {"true", "1", "paired", "yes", "bonded"}

            parsed.append(BlueMuseDevice(address=address, name=name, paired=paired, connected=connected))

        parsed.sort(key=lambda item: (not item.connected, item.name))
        return parsed

    def start_scan(self) -> None:
        self._request("POST", self._endpoints["start_scan"])

    def stop_scan(self) -> None:
        self._request("POST", self._endpoints["stop_scan"])

    def connect(self, address: str) -> None:
        self._request("POST", self._endpoints["connect"], {"address": address})

    def disconnect(self, address: str) -> None:
        self._request("POST", self._endpoints["disconnect"], {"address": address})

    def disconnect_all(self) -> None:
        self._request("POST", self._endpoints["disconnect_all"])


# ----------------------------------------------------------------------
# BrainFlow helpers
# ----------------------------------------------------------------------


def build_params(
    mac_address: Optional[str],
    serial_port: Optional[str],
    ip_address: Optional[str],
    ip_port: Optional[int],
    timeout: Optional[int],
) -> BrainFlowInputParams:
    """Create :class:`BrainFlowInputParams` with Windows friendly defaults."""

    params = BrainFlowInputParams()

    if mac_address:
        params.mac_address = mac_address

    # On Windows the Muse BLE driver often expects the MAC address to be set in
    # the ``serial_port`` field as well.  We expose an explicit switch so users
    # can decide whether both fields should be populated.
    if serial_port:
        params.serial_port = serial_port
    elif mac_address and sys.platform.startswith("win"):
        params.serial_port = mac_address

    if ip_address:
        params.ip_address = ip_address
    if ip_port:
        params.ip_port = ip_port
    if timeout:
        params.timeout = timeout

    return params


def collect_data(
    params: BrainFlowInputParams,
    board_id: int,
    duration: float,
    chunk_size: int,
    extra_wait: float,
) -> list[list[float]]:
    """Connect to the headset, stream for ``duration`` seconds and return data."""

    BoardShim.enable_dev_board_logger()

    board = BoardShim(board_id, params)
    try:
        board.prepare_session()
        board.start_stream(chunk_size)
        time.sleep(duration)
        data = board.get_board_data()
    finally:
        try:
            board.stop_stream()
        except BrainFlowError:
            # The stream may already be stopped if the board disconnected; the
            # next step still needs to release the session.
            pass
        board.release_session()

    if extra_wait > 0:
        time.sleep(extra_wait)

    return data.tolist()


def write_csv(path: Path, rows: Iterable[Iterable[float]], headers: Sequence[str]) -> None:
    """Persist the BrainFlow data matrix to a CSV file."""

    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


class Muse2StreamApp(tk.Tk):
    """간단한 Muse 2 BrainFlow GUI 애플리케이션."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Muse 2 BrainFlow 수집기")
        self.resizable(False, False)

        self._worker: Optional[threading.Thread] = None
        self._messages: queue.Queue[tuple[str, object]] = queue.Queue()

        self._mac_var = tk.StringVar()
        self._serial_var = tk.StringVar()
        self._ip_var = tk.StringVar()
        self._port_var = tk.StringVar()
        self._timeout_var = tk.StringVar(value="15")
        self._duration_var = tk.StringVar(value="20.0")
        self._chunk_var = tk.StringVar(value="4500")
        self._wait_var = tk.StringVar(value="0.0")
        self._output_var = tk.StringVar(value=str(Path("muse_capture.csv").resolve()))
        self._show_summary = tk.BooleanVar(value=False)

        # BlueMuse 관련 상태
        self._bluemuse_client = BlueMuseClient()
        self._bluemuse_path_var = tk.StringVar()
        self._bluemuse_url_var = tk.StringVar(value=self._bluemuse_client.base_url)
        self._device_list: list[BlueMuseDevice] = []
        self._device_listbox: Optional[tk.Listbox] = None

        self._bluemuse_url_var.trace_add("write", self._on_bluemuse_url_change)

        self._build_layout()
        self._poll_messages()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        main = ttk.Frame(self, padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        labels = {
            "MAC 주소 (필수)": self._mac_var,
            "Serial Port": self._serial_var,
            "IP 주소": self._ip_var,
            "IP 포트": self._port_var,
            "타임아웃 (초)": self._timeout_var,
            "녹화 시간 (초)": self._duration_var,
            "BrainFlow 버퍼": self._chunk_var,
            "추가 대기 (초)": self._wait_var,
        }

        row_index = 0
        for label_text, variable in labels.items():
            ttk.Label(main, text=label_text).grid(row=row_index, column=0, sticky="e", padx=(0, 8), pady=4)
            entry = ttk.Entry(main, textvariable=variable, width=32)
            entry.grid(row=row_index, column=1, sticky="w", pady=4)
            if variable is self._mac_var:
                entry.focus()
            row_index += 1

        row_index = self._build_bluemuse_controls(main, row_index)

        ttk.Label(main, text="출력 CSV 파일").grid(row=row_index, column=0, sticky="e", padx=(0, 8), pady=4)
        output_frame = ttk.Frame(main)
        output_frame.grid(row=row_index, column=1, sticky="w", pady=4)
        output_entry = ttk.Entry(output_frame, textvariable=self._output_var, width=28)
        output_entry.grid(row=0, column=0, pady=0, padx=(0, 4))
        ttk.Button(output_frame, text="찾아보기", command=self._choose_output).grid(row=0, column=1, pady=0)
        row_index += 1

        ttk.Checkbutton(main, text="채널 요약 출력", variable=self._show_summary).grid(
            row=row_index, column=0, columnspan=2, sticky="w", pady=(4, 8)
        )
        row_index += 1

        self._start_button = ttk.Button(main, text="녹화 시작", command=self._on_start)
        self._start_button.grid(row=row_index, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        row_index += 1

        self._log = tk.Text(main, height=12, width=60, state="disabled")
        self._log.grid(row=row_index, column=0, columnspan=2, sticky="nsew")

    def _build_bluemuse_controls(self, parent: ttk.Frame, row: int) -> int:
        frame = ttk.LabelFrame(parent, text="BlueMuse 연동")
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="실행 파일 경로").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        path_entry = ttk.Entry(frame, textvariable=self._bluemuse_path_var, width=32)
        path_entry.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="찾아보기", command=self._choose_bluemuse_exe).grid(row=0, column=2, padx=(4, 0), pady=4)

        ttk.Label(frame, text="원격 제어 주소").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        url_entry = ttk.Entry(frame, textvariable=self._bluemuse_url_var, width=32)
        url_entry.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="상태 확인", command=self._on_bluemuse_status).grid(row=1, column=2, padx=(4, 0), pady=4)

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        for col in range(5):
            button_row.columnconfigure(col, weight=1)

        ttk.Button(button_row, text="BlueMuse 실행", command=self._on_launch_bluemuse).grid(row=0, column=0, padx=2)
        ttk.Button(button_row, text="스캔 시작", command=self._on_start_scan).grid(row=0, column=1, padx=2)
        ttk.Button(button_row, text="스캔 중지", command=self._on_stop_scan).grid(row=0, column=2, padx=2)
        ttk.Button(button_row, text="목록 새로고침", command=self._on_refresh_devices).grid(row=0, column=3, padx=2)
        ttk.Button(button_row, text="모두 해제", command=self._on_disconnect_all).grid(row=0, column=4, padx=2)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=3, column=0, columnspan=3, sticky="ew")
        list_frame.columnconfigure(0, weight=1)

        self._device_listbox = tk.Listbox(list_frame, height=6, exportselection=False)
        self._device_listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._device_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._device_listbox.configure(yscrollcommand=scrollbar.set)
        self._device_listbox.bind("<Double-Button-1>", lambda _event: self._apply_selected_mac())

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)

        ttk.Button(actions, text="선택 연결", command=self._on_connect_selected).grid(row=0, column=0, padx=2)
        ttk.Button(actions, text="선택 해제", command=self._on_disconnect_selected).grid(row=0, column=1, padx=2)
        ttk.Button(actions, text="MAC 입력", command=self._apply_selected_mac).grid(row=0, column=2, padx=2)

        return row + 1

    def _choose_output(self) -> None:
        initial = Path(self._output_var.get()).expanduser()
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="CSV 파일 선택",
            initialfile=initial.name,
            initialdir=str(initial.parent),
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filename:
            self._output_var.set(filename)

    def _choose_bluemuse_exe(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="BlueMuse 실행 파일 선택",
            filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*.*")],
        )
        if filename:
            self._bluemuse_path_var.set(filename)

    def _log_message(self, message: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", f"{message}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _on_bluemuse_url_change(self, *_args: object) -> None:
        self._bluemuse_client.set_base_url(self._bluemuse_url_var.get().strip())

    # ------------------------------------------------------------------
    # Event handling - BlueMuse
    # ------------------------------------------------------------------
    def _get_selected_device(self) -> Optional[BlueMuseDevice]:
        if not self._device_listbox:
            return None
        selection = self._device_listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self._device_list):
            return None
        return self._device_list[index]

    def _apply_selected_mac(self) -> None:
        device = self._get_selected_device()
        if not device:
            messagebox.showinfo("선택 필요", "목록에서 Muse 장치를 선택하세요.", parent=self)
            return
        self._mac_var.set(device.address)
        self._log_message(f"선택한 장치 MAC 주소({device.address})를 입력란에 반영했습니다.")

    def _on_launch_bluemuse(self) -> None:
        def action() -> str:
            path = Path(self._bluemuse_path_var.get()).expanduser()
            if not path.is_file():
                raise BlueMuseError("BlueMuse 실행 파일 경로가 올바르지 않습니다.")
            try:
                subprocess.Popen([str(path)])
            except OSError as err:
                raise BlueMuseError(f"BlueMuse 실행 실패: {err}") from err
            return "BlueMuse 실행을 시도했습니다. Windows 작업 표시줄에서 실행 상태를 확인하세요."

        self._run_bluemuse_action(action)

    def _on_bluemuse_status(self) -> None:
        def action() -> str:
            status = self._bluemuse_client.status()
            message = status.get("message") if isinstance(status, dict) else None
            if message:
                return f"BlueMuse 상태: {message}"
            return f"BlueMuse 상태 응답: {status}"

        self._run_bluemuse_action(action)

    def _on_start_scan(self) -> None:
        def action() -> str:
            self._bluemuse_client.start_scan()
            return "헤드셋 검색을 시작했습니다."

        self._run_bluemuse_action(action, refresh=True)

    def _on_stop_scan(self) -> None:
        def action() -> str:
            self._bluemuse_client.stop_scan()
            return "헤드셋 검색을 중단했습니다."

        self._run_bluemuse_action(action)

    def _on_refresh_devices(self) -> None:
        self._run_bluemuse_refresh()

    def _on_connect_selected(self) -> None:
        device = self._get_selected_device()
        if not device:
            messagebox.showinfo("선택 필요", "연결할 Muse 장치를 선택하세요.", parent=self)
            return

        def action() -> str:
            self._bluemuse_client.connect(device.address)
            return f"{device.name}({device.address}) 연결을 요청했습니다."

        self._run_bluemuse_action(action, refresh=True)

    def _on_disconnect_selected(self) -> None:
        device = self._get_selected_device()
        if not device:
            messagebox.showinfo("선택 필요", "해제할 Muse 장치를 선택하세요.", parent=self)
            return

        def action() -> str:
            self._bluemuse_client.disconnect(device.address)
            return f"{device.name}({device.address}) 연결 해제를 요청했습니다."

        self._run_bluemuse_action(action, refresh=True)

    def _on_disconnect_all(self) -> None:
        if not messagebox.askyesno(
            "모두 해제",
            "모든 Muse 연결을 해제하시겠습니까?",
            parent=self,
        ):
            return

        def action() -> str:
            self._bluemuse_client.disconnect_all()
            return "모든 Muse 연결 해제를 요청했습니다."

        self._run_bluemuse_action(action, refresh=True)

    def _run_bluemuse_action(self, action, refresh: bool = False) -> None:
        def worker() -> None:
            try:
                result = action()
            except BlueMuseError as err:
                self._messages.put(("error", {"message": str(err), "source": "bluemuse"}))
                return
            except Exception as err:  # pylint: disable=broad-except
                self._messages.put(
                    (
                        "error",
                        {
                            "message": f"BlueMuse 처리 중 예외 발생: {err}",
                            "source": "bluemuse",
                        },
                    )
                )
                return

            if result:
                self._messages.put(("log", str(result)))

            if refresh:
                self._run_bluemuse_refresh(background=True)

        threading.Thread(target=worker, daemon=True).start()

    def _run_bluemuse_refresh(self, background: bool = False) -> None:
        def worker() -> None:
            try:
                devices = self._bluemuse_client.list_devices()
            except BlueMuseError as err:
                self._messages.put(("error", {"message": str(err), "source": "bluemuse"}))
                return
            except Exception as err:  # pylint: disable=broad-except
                self._messages.put(
                    (
                        "error",
                        {
                            "message": f"장치 목록을 불러오지 못했습니다: {err}",
                            "source": "bluemuse",
                        },
                    )
                )
                return

            self._messages.put(("devices", devices))
            if devices:
                self._messages.put(("log", f"{len(devices)}개의 Muse 장치 상태를 불러왔습니다."))
            else:
                self._messages.put(("log", "Muse 장치가 발견되지 않았습니다."))

        if background:
            threading.Thread(target=worker, daemon=True).start()
        else:
            worker()

    def _update_device_list(self, devices: Sequence[BlueMuseDevice]) -> None:
        self._device_list = list(devices)
        if not self._device_listbox:
            return
        self._device_listbox.delete(0, "end")
        for device in self._device_list:
            self._device_listbox.insert("end", f"{device.address} - {device.label()}")

    # ------------------------------------------------------------------
    # Event handling - BrainFlow 수집
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("진행 중", "이미 녹화를 진행 중입니다.")
            return

        mac = self._mac_var.get().strip()
        if not mac:
            messagebox.showerror("MAC 주소 필요", "Muse 2의 Bluetooth MAC 주소를 입력하세요.")
            return

        try:
            timeout = int(self._timeout_var.get())
        except ValueError:
            messagebox.showerror("잘못된 값", "타임아웃은 정수로 입력해야 합니다.")
            return

        try:
            duration = float(self._duration_var.get())
        except ValueError:
            messagebox.showerror("잘못된 값", "녹화 시간은 숫자로 입력해야 합니다.")
            return

        try:
            chunk_size = int(self._chunk_var.get())
        except ValueError:
            messagebox.showerror("잘못된 값", "BrainFlow 버퍼는 정수로 입력해야 합니다.")
            return

        try:
            extra_wait = float(self._wait_var.get())
        except ValueError:
            messagebox.showerror("잘못된 값", "추가 대기 시간은 숫자로 입력해야 합니다.")
            return

        serial = self._serial_var.get().strip() or None
        ip_address = self._ip_var.get().strip() or None
        ip_port_raw = self._port_var.get().strip()
        if ip_port_raw:
            try:
                ip_port = int(ip_port_raw)
            except ValueError:
                messagebox.showerror("잘못된 값", "IP 포트는 정수로 입력해야 합니다.")
                return
        else:
            ip_port = None

        output_path = Path(self._output_var.get()).expanduser()

        params = build_params(
            mac_address=mac,
            serial_port=serial,
            ip_address=ip_address,
            ip_port=ip_port,
            timeout=timeout,
        )

        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        self._start_button.state(["disabled"])

        self._worker = threading.Thread(
            target=self._run_capture,
            args=(params, duration, chunk_size, extra_wait, output_path, self._show_summary.get()),
            daemon=True,
        )
        self._worker.start()

    def _run_capture(
        self,
        params: BrainFlowInputParams,
        duration: float,
        chunk_size: int,
        extra_wait: float,
        output_path: Path,
        show_summary: bool,
    ) -> None:
        self._messages.put(("log", "Muse 2 연결을 시도합니다..."))
        board_id = BoardIds.MUSE_2_BOARD.value

        try:
            data = collect_data(
                params=params,
                board_id=board_id,
                duration=duration,
                chunk_size=chunk_size,
                extra_wait=extra_wait,
            )
        except BrainFlowError as err:
            self._messages.put(("error", f"BrainFlow 스트리밍 오류: {err}"))
            return
        except Exception as err:  # pylint: disable=broad-except
            self._messages.put(("error", f"예상치 못한 오류: {err}"))
            return

        if not data or not data[0]:
            self._messages.put(("error", "헤드셋에서 데이터를 수신하지 못했습니다. Bluetooth 연결을 확인하세요."))
            return

        channel_count = len(data)
        sample_count = len(data[0])

        eeg_names = BoardShim.get_eeg_names(board_id)
        if isinstance(eeg_names, str):
            headers = [name.strip() for name in eeg_names.split(",") if name.strip()]
        else:
            headers = list(eeg_names or [])

        if len(headers) != channel_count:
            headers = [f"ch_{idx}" for idx in range(channel_count)]

        samples = list(zip(*data))

        try:
            write_csv(output_path, samples, headers)
        except OSError as err:
            self._messages.put(("error", f"CSV 저장 실패: {err}"))
            return

        summary_lines: list[str] = []
        if show_summary:
            for header, channel_values in zip(headers, data):
                summary_lines.append(
                    (
                        f"{header}: mean={statistics.fmean(channel_values):.2f} "
                        f"min={min(channel_values):.2f} max={max(channel_values):.2f}"
                    )
                )

        self._messages.put(
            (
                "success",
                {
                    "samples": sample_count,
                    "channels": channel_count,
                    "path": output_path,
                    "summary": summary_lines,
                },
            )
        )

    def _poll_messages(self) -> None:
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._log_message(str(payload))
            elif kind == "devices":
                devices = payload if isinstance(payload, list) else []
                self._update_device_list(devices)
            elif kind == "error":
                if isinstance(payload, dict):
                    message = payload.get("message", "알 수 없는 오류")
                    source = payload.get("source")
                else:
                    message = str(payload)
                    source = None
                self._log_message(message)
                messagebox.showerror("오류", message, parent=self)
                if source != "bluemuse":
                    self._start_button.state(["!disabled"])
                    self._worker = None
            elif kind == "success":
                info = payload if isinstance(payload, dict) else {}
                message = (
                    f"총 {info.get('channels', 0)}개 채널에서 {info.get('samples', 0)}개 샘플을 저장했습니다.\n"
                    f"위치: {Path(info.get('path')).resolve()}"
                )
                self._log_message(message)
                for line in info.get("summary", []):
                    self._log_message(line)
                messagebox.showinfo("완료", message, parent=self)
                self._start_button.state(["!disabled"])
                self._worker = None

        self.after(150, self._poll_messages)

    def _on_close(self) -> None:
        if self._worker and self._worker.is_alive():
            if not messagebox.askyesno(
                "종료 확인",
                "녹화가 진행 중입니다. 중단하고 종료하시겠습니까?",
                parent=self,
            ):
                return
        self.destroy()


# ----------------------------------------------------------------------
# 진입점
# ----------------------------------------------------------------------

def main() -> None:
    app = Muse2StreamApp()
    app.mainloop()


if __name__ == "__main__":
    main()

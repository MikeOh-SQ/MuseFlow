"""Windows용 Muse 2 BrainFlow 스트리밍 GUI.

Bluetooth로 페어링한 Muse 2 헤드셋에 연결해 EEG 데이터를 수집하고 CSV 파일로
저장하는 간단한 그래픽 인터페이스를 제공합니다. Raspberry Pi에서 사용하던 워크
플로우를 Windows에서도 손쉽게 재현할 수 있도록, BrainFlow 설정과 연결 과정을
GUI에서 직접 제어할 수 있게 했습니다.
"""

from __future__ import annotations

import csv
import queue
import statistics
import sys
import time
import threading
from pathlib import Path
from typing import Iterable, Optional, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from brainflow.board_shim import BoardIds, BoardShim, BrainFlowError, BrainFlowInputParams


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

        for row_index, (label_text, variable) in enumerate(labels.items()):
            ttk.Label(main, text=label_text).grid(row=row_index, column=0, sticky="e", padx=(0, 8), pady=4)
            entry = ttk.Entry(main, textvariable=variable, width=32)
            entry.grid(row=row_index, column=1, sticky="w", pady=4)
            if variable is self._mac_var:
                entry.focus()

        # Output path selector
        ttk.Label(main, text="출력 CSV 파일").grid(row=len(labels), column=0, sticky="e", padx=(0, 8), pady=4)
        output_frame = ttk.Frame(main)
        output_frame.grid(row=len(labels), column=1, sticky="w", pady=4)
        output_entry = ttk.Entry(output_frame, textvariable=self._output_var, width=28)
        output_entry.grid(row=0, column=0, pady=0, padx=(0, 4))
        ttk.Button(output_frame, text="찾아보기", command=self._choose_output).grid(row=0, column=1, pady=0)

        ttk.Checkbutton(main, text="채널 요약 출력", variable=self._show_summary).grid(
            row=len(labels) + 1, column=0, columnspan=2, sticky="w", pady=(4, 8)
        )

        self._start_button = ttk.Button(main, text="녹화 시작", command=self._on_start)
        self._start_button.grid(row=len(labels) + 2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self._log = tk.Text(main, height=12, width=60, state="disabled")
        self._log.grid(row=len(labels) + 3, column=0, columnspan=2, sticky="nsew")

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

    def _log_message(self, message: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", f"{message}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    # ------------------------------------------------------------------
    # Event handling
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
        except Exception as err:
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
            elif kind == "error":
                self._log_message(str(payload))
                messagebox.showerror("오류", str(payload), parent=self)
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


def main() -> None:
    app = Muse2StreamApp()
    app.mainloop()


if __name__ == "__main__":
    main()

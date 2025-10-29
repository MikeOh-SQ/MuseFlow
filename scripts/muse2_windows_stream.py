"""
Utilities to connect to a Muse 2 headset from Windows using BrainFlow and
collect raw EEG data over Bluetooth.

This script mirrors the workflow that is typically used on Raspberry Pi setups
but adjusts the connection parameters BrainFlow expects on Windows.

Usage example::

    python scripts/muse2_windows_stream.py --mac-address AA:BB:CC:DD:EE:FF \
        --duration 30 --output muse_capture.csv

On Windows machines the Muse 2 can be paired through the Bluetooth settings
before running the script.  Once the device is paired, pass the Bluetooth MAC
address (shown in the Muse Manager app or in the Bluetooth pairing details) via
``--mac-address``.  In some cases BrainFlow requires the value in the
``serial_port`` field; the ``--serial-port`` option forwards the same value to
that field.

The collected data are exported to a CSV file with column names matching the
BrainFlow channel order for the Muse 2 board.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence

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


def parse_arguments(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mac-address",
        dest="mac_address",
        help="Bluetooth MAC address of the Muse 2 headset",
    )
    parser.add_argument(
        "--serial-port",
        dest="serial_port",
        help="Optional value for BrainFlow's serial_port field (defaults to the MAC address on Windows)",
    )
    parser.add_argument(
        "--ip-address",
        dest="ip_address",
        help="Optional IP address (not typically required for Muse headsets)",
    )
    parser.add_argument(
        "--ip-port",
        dest="ip_port",
        type=int,
        help="Optional IP port (not typically required for Muse headsets)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Connection timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=20.0,
        help="Duration of the recording in seconds (default: 20)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=4500,
        help="BrainFlow buffer size (default: 4500). Increase if you record for long sessions.",
    )
    parser.add_argument(
        "--extra-wait",
        type=float,
        default=0.0,
        help="Additional delay after stopping the stream to allow the adapter to settle.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("muse_capture.csv"),
        help="Destination CSV file (default: muse_capture.csv)",
    )
    parser.add_argument(
        "--show-summary",
        action="store_true",
        help="Print summary statistics for the recorded channels",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_arguments(argv)

    if not args.mac_address:
        raise SystemExit("--mac-address is required to establish a Bluetooth connection")

    params = build_params(
        mac_address=args.mac_address,
        serial_port=args.serial_port,
        ip_address=args.ip_address,
        ip_port=args.ip_port,
        timeout=args.timeout,
    )

    board_id = BoardIds.MUSE_2_BOARD.value

    try:
        data = collect_data(
            params=params,
            board_id=board_id,
            duration=args.duration,
            chunk_size=args.chunk_size,
            extra_wait=args.extra_wait,
        )
    except BrainFlowError as err:
        raise SystemExit(f"BrainFlow failed to stream data: {err}")

    if not data or not data[0]:
        raise SystemExit("No data captured from the headset; verify the Bluetooth connection and try again.")

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

    write_csv(args.output, samples, headers)

    if args.show_summary:
        for header, channel_values in zip(headers, data):
            print(
                f"{header}: mean={statistics.fmean(channel_values):.2f} "
                f"min={min(channel_values):.2f} max={max(channel_values):.2f}"
            )

    print(f"Saved {sample_count} samples for {channel_count} channels to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

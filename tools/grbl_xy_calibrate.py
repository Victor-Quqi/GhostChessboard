#!/usr/bin/env python3
"""Small GRBL helper for XY calibration and jog tests."""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import serial

try:
    import fcntl
except ImportError:  # pragma: no cover - not available on Windows
    fcntl = None


STATUS_RE = re.compile(r"<([^|>]+)\|.*?\|Pn:([^>|]+)(?:\|.*)?>(?:\r?\n)?$")
MPOS_RE = re.compile(r"MPos:([-0-9.]+),([-0-9.]+),([-0-9.]+)(?:,([-0-9.]+))?")

AXIS_TO_SETTING = {
    "X": "$100",
    "Y": "$101",
}

LOCK_PATH = Path("/tmp/grbl_xy_calibrate.lock")


@dataclass
class Status:
    raw: str
    state: str
    pins: str
    mpos: List[float]

    def axis_present(self, axis: str) -> bool:
        return axis in self.pins


class GrblClient:
    def __init__(self, port: str, baud: int, startup_delay: float) -> None:
        self.port = port
        self.baud = baud
        self.startup_delay = startup_delay
        self.ser: Optional[serial.Serial] = None
        self.lock_handle = None

    def _acquire_lock(self) -> None:
        if fcntl is None:
            return
        self.lock_handle = LOCK_PATH.open("w", encoding="ascii")
        try:
            fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Serial port is already in use by another grbl_xy_calibrate.py process"
            ) from exc

    def _release_lock(self) -> None:
        if self.lock_handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_UN)
        self.lock_handle.close()
        self.lock_handle = None

    def __enter__(self) -> "GrblClient":
        self._acquire_lock()
        self.ser = serial.Serial(self.port, self.baud, timeout=0.15)
        time.sleep(self.startup_delay)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.ser is not None:
            self.ser.close()
            self.ser = None
        self._release_lock()

    def _read_all(self) -> str:
        assert self.ser is not None
        return self.ser.read_all().decode("utf-8", errors="replace")

    def send_line(self, line: str, wait: float = 0.25, echo: bool = False) -> str:
        assert self.ser is not None
        self.ser.write((line + "\n").encode("ascii"))
        self.ser.flush()
        time.sleep(wait)
        out = self._read_all()
        if echo:
            print(f">>> {line}")
            if out:
                print(out, end="")
        return out

    def send_realtime(self, data: bytes, wait: float = 0.2, echo: bool = False) -> str:
        assert self.ser is not None
        self.ser.write(data)
        self.ser.flush()
        time.sleep(wait)
        out = self._read_all()
        if echo:
            print(f">>> {data!r}")
            if out:
                print(out, end="")
        return out

    def query_status(self, echo: bool = False) -> Status:
        raw = self.send_realtime(b"?", wait=0.12, echo=False).strip()
        if echo and raw:
            print(raw)
        match = STATUS_RE.search(raw)
        if not match:
            raise RuntimeError(f"Could not parse status: {raw!r}")
        mpos_match = MPOS_RE.search(raw)
        if not mpos_match:
            raise RuntimeError(f"Could not parse machine position: {raw!r}")
        coords = [float(item) for item in mpos_match.groups(default="0")]
        return Status(raw=raw, state=match.group(1), pins=match.group(2), mpos=coords)

    def wait_idle(self, timeout: float = 15.0, echo: bool = False) -> Status:
        deadline = time.time() + timeout
        last: Optional[Status] = None
        while time.time() < deadline:
            status = self.query_status(echo=echo)
            last = status
            if status.state.startswith("Idle"):
                return status
            if status.state.startswith("Alarm"):
                raise RuntimeError(f"Controller entered alarm state: {status.raw}")
            time.sleep(0.05)
        raise RuntimeError(f"Timed out waiting for idle; last status: {last.raw if last else 'n/a'}")


def add_serial_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port path")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=2.5,
        help="Delay after opening the port because ESP32 resets on connect",
    )
    parser.add_argument("--dir-mask", type=int, default=2, help="Value to write into $3 before motion")
    parser.add_argument(
        "--limit-invert",
        type=int,
        default=0,
        help="Value to write into $5 before status/motion",
    )
    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="Do not send $3/$5/$X before the requested action",
    )
    parser.add_argument(
        "--x-steps",
        type=float,
        help="Optional runtime value to write into $100 after connect",
    )
    parser.add_argument(
        "--y-steps",
        type=float,
        help="Optional runtime value to write into $101 after connect",
    )


def init_controller(client: GrblClient, args: argparse.Namespace) -> None:
    if args.skip_init:
        return
    client.send_line(f"$3={args.dir_mask}", echo=False)
    client.send_line(f"$5={args.limit_invert}", echo=False)
    if args.x_steps is not None:
        client.send_line(f"$100={args.x_steps:.6f}", echo=False)
    if args.y_steps is not None:
        client.send_line(f"$101={args.y_steps:.6f}", echo=False)
    client.send_line("$X", echo=False)


def cmd_status(args: argparse.Namespace) -> int:
    with GrblClient(args.port, args.baud, args.startup_delay) as client:
        init_controller(client, args)
        status = client.query_status()
        print(status.raw)
    return 0


def cmd_jog(args: argparse.Namespace) -> int:
    with GrblClient(args.port, args.baud, args.startup_delay) as client:
        init_controller(client, args)
        client.send_line("G21")
        axes = []
        if args.x is not None:
            axes.append(f"X{args.x:g}")
        if args.y is not None:
            axes.append(f"Y{args.y:g}")
        if not axes:
            raise RuntimeError("At least one of --x or --y must be provided")
        client.send_line(f"G91 G1 {' '.join(axes)} F{args.feed:g}", wait=0.05, echo=True)
        status = client.wait_idle(echo=True)
        client.send_line("G90")
        print(f"Final status: {status.raw}")
    return 0


def cmd_measure_span(args: argparse.Namespace) -> int:
    axis = args.axis.upper()
    if axis not in AXIS_TO_SETTING:
        raise RuntimeError("Only X and Y are supported")
    with GrblClient(args.port, args.baud, args.startup_delay) as client:
        init_controller(client, args)
        client.send_line("G21")
        start = client.query_status(echo=True)
        start_present = start.axis_present(axis)
        print(f"Start {axis} pin present: {start_present}")
        total = 0.0
        signed_step = args.step if args.direction > 0 else -args.step
        while total < args.max_travel:
            client.send_line(
                f"G91 G1 {axis}{signed_step:g} F{args.feed:g}",
                wait=0.05,
                echo=True,
            )
            status = client.wait_idle(echo=True)
            total += args.step
            axis_present = status.axis_present(axis)
            print(f"Accumulated distance: {total:.3f} ; {axis} pin present: {axis_present}")
            if axis_present != start_present:
                print(f"Measured span on {axis}: {total:.3f}")
                print(f"Final status: {status.raw}")
                client.send_line("G90")
                return 0
        client.send_line("G90")
        raise RuntimeError(f"Limit transition not detected within {args.max_travel} units")


def cmd_calc_steps(args: argparse.Namespace) -> int:
    if args.actual <= 0:
        raise RuntimeError("--actual must be positive")
    new_steps = args.current_steps * (args.commanded / args.actual)
    print(f"Recommended {args.axis.upper()} steps/mm: {new_steps:.6f}")
    print(
        f"Formula: new = {args.current_steps:g} * ({args.commanded:g} / {args.actual:g})"
    )
    return 0


def cmd_write_steps(args: argparse.Namespace) -> int:
    commands: List[str] = []
    if args.write_x_steps is not None:
        commands.append(f"$100={args.write_x_steps:.6f}")
    if args.write_y_steps is not None:
        commands.append(f"$101={args.write_y_steps:.6f}")
    if not commands:
        raise RuntimeError("Provide --x-steps and/or --y-steps")
    with GrblClient(args.port, args.baud, args.startup_delay) as client:
        init_controller(client, args)
        for command in commands:
            print(f">>> {command}")
            out = client.send_line(command, echo=False)
            if out:
                print(out, end="")
        print(client.query_status().raw)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Read one realtime status line")
    add_serial_args(status_parser)
    status_parser.set_defaults(func=cmd_status)

    jog_parser = subparsers.add_parser("jog", help="Run one XY relative move")
    add_serial_args(jog_parser)
    jog_parser.add_argument("--x", type=float, help="Relative X move in current units")
    jog_parser.add_argument("--y", type=float, help="Relative Y move in current units")
    jog_parser.add_argument("--feed", type=float, default=300.0, help="Feed rate in mm/min")
    jog_parser.set_defaults(func=cmd_jog)

    measure_parser = subparsers.add_parser(
        "measure-span",
        help="Move one axis in small steps until the limit signal changes",
    )
    add_serial_args(measure_parser)
    measure_parser.add_argument("--axis", required=True, choices=["X", "Y", "x", "y"])
    measure_parser.add_argument(
        "--direction",
        type=int,
        choices=[-1, 1],
        default=-1,
        help="Motion sign for each step",
    )
    measure_parser.add_argument("--step", type=float, default=2.0, help="Step size for each jog")
    measure_parser.add_argument("--feed", type=float, default=300.0, help="Feed rate in mm/min")
    measure_parser.add_argument(
        "--max-travel",
        type=float,
        default=650.0,
        help="Stop if the accumulated move exceeds this distance",
    )
    measure_parser.set_defaults(func=cmd_measure_span)

    calc_parser = subparsers.add_parser(
        "calc-steps",
        help="Compute recommended steps/mm from commanded and measured distances",
    )
    calc_parser.add_argument("--axis", required=True, choices=["X", "Y", "x", "y"])
    calc_parser.add_argument("--current-steps", type=float, required=True)
    calc_parser.add_argument("--commanded", type=float, required=True)
    calc_parser.add_argument("--actual", type=float, required=True)
    calc_parser.set_defaults(func=cmd_calc_steps)

    write_parser = subparsers.add_parser("write-steps", help="Write new $100/$101 values")
    add_serial_args(write_parser)
    write_parser.add_argument("--write-x-steps", type=float)
    write_parser.add_argument("--write-y-steps", type=float)
    write_parser.set_defaults(func=cmd_write_steps)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

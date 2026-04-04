"""Minimal GRBL transport and command wrapper."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

import serial

from src.config import AppConfig


class GrblError(RuntimeError):
    """Raised when GRBL returns an error or enters a bad state."""


@dataclass(slots=True)
class GrblStatus:
    raw: str
    state: str

    @classmethod
    def parse(cls, line: str) -> "GrblStatus":
        if not line.startswith("<") or "|" not in line:
            raise ValueError(f"Not a GRBL status line: {line}")
        state = line[1:].split("|", 1)[0]
        return cls(raw=line, state=state)


class SerialTransport:
    """Thin serial helper for line-oriented GRBL traffic."""

    def __init__(self, port: str, baudrate: int, startup_delay_s: float, read_timeout_s: float) -> None:
        self._port = port
        self._baudrate = baudrate
        self._startup_delay_s = startup_delay_s
        self._read_timeout_s = read_timeout_s
        self._serial: serial.Serial | None = None

    def __enter__(self) -> "SerialTransport":
        self.open()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.close()

    def open(self) -> None:
        if self._serial is not None:
            return
        self._serial = serial.Serial(
            self._port,
            self._baudrate,
            timeout=self._read_timeout_s,
        )
        time.sleep(self._startup_delay_s)
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def close(self) -> None:
        if self._serial is None:
            return
        self._serial.close()
        self._serial = None

    def write_line(self, line: str) -> None:
        if self._serial is None:
            raise RuntimeError("Serial transport is not open.")
        self._serial.write((line + "\n").encode("ascii"))
        self._serial.flush()

    def read_lines(self, duration_s: float) -> list[str]:
        if self._serial is None:
            raise RuntimeError("Serial transport is not open.")
        end = time.time() + duration_s
        lines: list[str] = []
        while time.time() < end:
            line = self._serial.readline().decode(errors="replace").strip()
            if line:
                lines.append(line)
        return lines


class GrblController:
    """Blocking GRBL command wrapper."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._transport = SerialTransport(
            port=config.serial.port,
            baudrate=config.serial.baudrate,
            startup_delay_s=config.serial.startup_delay_s,
            read_timeout_s=config.serial.read_timeout_s,
        )

    def __enter__(self) -> "GrblController":
        self.open()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.close()

    def open(self) -> None:
        self._transport.open()

    def close(self) -> None:
        self._transport.close()

    def command(self, line: str, response_window_s: float = 0.6) -> list[str]:
        self._transport.write_line(line)
        lines = self._transport.read_lines(response_window_s)
        for item in lines:
            if item.startswith("error:"):
                raise GrblError(f"{line} -> {item}")
        return lines

    def initialize(self) -> None:
        for line in self._config.grbl.startup_commands:
            self.command(line)

    def status(self) -> GrblStatus:
        lines = self.command("?", response_window_s=0.4)
        for line in lines:
            if line.startswith("<"):
                return GrblStatus.parse(line)
        raise GrblError(f"No status line returned: {lines}")

    def wait_for_idle(self, timeout_s: float = 120.0, poll_interval_s: float = 0.2) -> GrblStatus:
        end = time.time() + timeout_s
        last_status: GrblStatus | None = None
        while time.time() < end:
            status = self.status()
            last_status = status
            if status.state == "Idle":
                return status
            if status.state in {"Alarm", "Hold", "Door"}:
                raise GrblError(f"GRBL entered state {status.state}: {status.raw}")
            time.sleep(poll_interval_s)
        raise TimeoutError(f"Timed out waiting for Idle. Last status: {last_status}")

    def magnet_on(self, pwm: int) -> None:
        self.command(f"M3 S{int(pwm)}")

    def magnet_off(self) -> None:
        self.command("M5")

    def dwell(self, seconds: float) -> None:
        self.command(f"G4 P{seconds:.3f}")
        self.wait_for_idle(timeout_s=max(5.0, seconds + 2.0))

    def jog_relative(self, *, dx_mm: float = 0.0, dy_mm: float = 0.0, feed_mm_min: float | None = None) -> None:
        words: list[str] = []
        if dx_mm:
            words.append(f"X{dx_mm:.3f}")
        if dy_mm:
            words.append(f"Y{dy_mm:.3f}")
        if not words:
            return
        if feed_mm_min is not None:
            words.append(f"F{feed_mm_min:.3f}")
        self.command("G1 " + " ".join(words))
        distance = abs(dx_mm) + abs(dy_mm)
        timeout_s = max(10.0, distance / max(feed_mm_min or 1.0, 1.0) * 90.0)
        self.wait_for_idle(timeout_s=timeout_s)

    def run_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.command(line)

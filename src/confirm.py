"""Operator trigger adapters for interactive workflows."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from src.machine.grbl import GrblStatus


class OperatorTrigger(Protocol):
    """Blocking source of operator commands."""

    def wait(self) -> "OperatorCommand":
        ...


@dataclass(slots=True)
class OperatorCommand:
    """One operator command produced by a trigger adapter."""

    source: str
    detail: str = ""
    kind: str = "confirm"


ConfirmationEvent = OperatorCommand
ConfirmationTrigger = OperatorTrigger


@dataclass(slots=True)
class ClickSequenceEvent:
    """Internal click sequence detector output."""

    kind: str
    count: int
    gap_s: float | None = None


class ClickSequenceDetector:
    """Detect double-click confirmation and triple-click reset sequences."""

    def __init__(self, *, min_gap_s: float, max_gap_s: float, debounce_s: float) -> None:
        if min_gap_s < 0:
            raise ValueError("min_gap_s must be non-negative.")
        if max_gap_s <= min_gap_s:
            raise ValueError("max_gap_s must be greater than min_gap_s.")
        if debounce_s < 0:
            raise ValueError("debounce_s must be non-negative.")

        self.min_gap_s = min_gap_s
        self.max_gap_s = max_gap_s
        self.debounce_s = debounce_s
        self._armed = False
        self._was_pressed = False
        self._click_count = 0
        self._last_sequence_gap_s: float | None = None
        self._last_sequence_press_s: float | None = None
        self._last_any_press_s: float | None = None

    def update(self, *, pressed: bool, now_s: float) -> ClickSequenceEvent | None:
        if not pressed:
            self._armed = True
            self._was_pressed = False
            return self._maybe_finish_sequence(now_s)

        timeout_event = self._maybe_finish_sequence(now_s)
        if timeout_event is not None:
            return timeout_event

        if not self._armed:
            self._was_pressed = True
            return None
        if self._was_pressed:
            return None

        self._was_pressed = True
        if self._last_any_press_s is not None and now_s - self._last_any_press_s < self.debounce_s:
            return None
        self._last_any_press_s = now_s

        if self._last_sequence_press_s is None:
            self._start_sequence(now_s)
            return ClickSequenceEvent(kind="press", count=1)

        gap_s = now_s - self._last_sequence_press_s
        if gap_s < self.min_gap_s:
            return None
        if gap_s > self.max_gap_s:
            self._start_sequence(now_s)
            return ClickSequenceEvent(kind="press", count=1)

        self._click_count += 1
        self._last_sequence_gap_s = gap_s
        self._last_sequence_press_s = now_s
        if self._click_count >= 3:
            self._reset_sequence()
            return ClickSequenceEvent(kind="triple-click", count=3, gap_s=gap_s)
        return ClickSequenceEvent(kind="press", count=self._click_count, gap_s=gap_s)

    def _start_sequence(self, now_s: float) -> None:
        self._click_count = 1
        self._last_sequence_gap_s = None
        self._last_sequence_press_s = now_s

    def _reset_sequence(self) -> None:
        self._click_count = 0
        self._last_sequence_gap_s = None
        self._last_sequence_press_s = None

    def _maybe_finish_sequence(self, now_s: float) -> ClickSequenceEvent | None:
        if self._last_sequence_press_s is None:
            return None
        if now_s - self._last_sequence_press_s <= self.max_gap_s:
            return None

        if self._click_count == 2:
            gap_s = self._last_sequence_gap_s
            self._reset_sequence()
            return ClickSequenceEvent(kind="double-click", count=2, gap_s=gap_s)

        self._reset_sequence()
        return None


class DoubleClickDetector(ClickSequenceDetector):
    """Backward-compatible name for the click sequence detector."""


class EnterConfirmationTrigger:
    """Keyboard fallback confirmation source."""

    def __init__(self, *, prompt: str = "Press Enter after the human move...") -> None:
        self.prompt = prompt

    def wait(self) -> OperatorCommand:
        input(self.prompt)
        return OperatorCommand(source="enter", kind="confirm")


class GrblPinClickTrigger:
    """Temporary operator source using GRBL limit pin click sequences."""

    def __init__(
        self,
        *,
        read_status: Callable[[], GrblStatus],
        axis: str = "Y",
        pressed_when: str = "absent",
        poll_s: float = 0.03,
        min_gap_s: float = 0.12,
        max_gap_s: float = 1.00,
        debounce_s: float = 0.07,
        on_press: Callable[[str], None] | None = None,
    ) -> None:
        axis = axis.strip().upper()
        if len(axis) != 1:
            raise ValueError("axis must be a single GRBL pin letter.")
        if pressed_when not in {"absent", "present"}:
            raise ValueError("pressed_when must be 'absent' or 'present'.")

        self.read_status = read_status
        self.axis = axis
        self.pressed_when = pressed_when
        self.poll_s = max(poll_s, 0.005)
        self.on_press = on_press
        self.detector = ClickSequenceDetector(
            min_gap_s=min_gap_s,
            max_gap_s=max_gap_s,
            debounce_s=debounce_s,
        )

    def wait(self) -> OperatorCommand:
        while True:
            status = self.read_status()
            pressed = self._pressed_from_pins(status.pins)
            event = self.detector.update(pressed=pressed, now_s=time.monotonic())
            if event is not None:
                if event.kind == "press" and self.on_press is not None:
                    self.on_press(f"axis={self.axis} click={event.count} pins={status.pins or '-'}")
                if event.kind == "double-click":
                    gap_ms = int(round((event.gap_s or 0.0) * 1000.0))
                    return OperatorCommand(
                        source="grbl-pin-double-click",
                        detail=f"axis={self.axis} gap_ms={gap_ms}",
                        kind="confirm",
                    )
                if event.kind == "triple-click":
                    gap_ms = int(round((event.gap_s or 0.0) * 1000.0))
                    return OperatorCommand(
                        source="grbl-pin-triple-click",
                        detail=f"axis={self.axis} gap_ms={gap_ms}",
                        kind="reset",
                    )
            time.sleep(self.poll_s)

    def _pressed_from_pins(self, pins: str) -> bool:
        present = self.axis in pins
        if self.pressed_when == "present":
            return present
        return not present


GrblPinDoubleClickTrigger = GrblPinClickTrigger

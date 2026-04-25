"""Tests for hardware-facing motion executor safety behavior."""

from __future__ import annotations

import unittest

from src.config import AppConfig
from src.motion.contracts import DragPlan
from src.motion.executor import MotionExecutor


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.raise_on_wait = False

    def magnet_on(self, pwm: int, *, wait_for_ack: bool = True) -> None:
        self.calls.append(("magnet_on", pwm))

    def magnet_off(self, *, wait_for_ack: bool = True) -> None:
        self.calls.append(("magnet_off", wait_for_ack))

    def dwell(self, seconds: float) -> None:
        self.calls.append(("dwell", seconds))

    def jog_relative(
        self,
        *,
        dx_mm: float,
        dy_mm: float,
        feed_mm_min: float,
        wait_for_idle: bool = True,
        wait_for_ack: bool = True,
    ) -> float:
        self.calls.append(("jog_relative", (dx_mm, dy_mm, feed_mm_min, wait_for_idle, wait_for_ack)))
        return 0.01

    def wait_for_idle(self, timeout_s: float = 120.0, poll_interval_s: float = 0.2) -> None:
        self.calls.append(("wait_for_idle", timeout_s))
        if self.raise_on_wait:
            raise TimeoutError("still moving")


class MotionExecutorSafetyTests(unittest.TestCase):
    def _config(self) -> AppConfig:
        config = AppConfig()
        config.motion.engage_delay_s = 0.0
        config.motion.settle_delay_s = 0.0
        return config

    def test_drag_plan_turns_magnet_off_when_wait_fails(self) -> None:
        controller = FakeController()
        controller.raise_on_wait = True
        executor = MotionExecutor(controller, self._config())
        plan = DragPlan(
            start=(0, 0),
            end=(0, 1),
            waypoints_mm=[(0.0, 0.0), (0.0, 42.0)],
            release_mm=(0.0, 57.0),
            overshoot_vector_mm=(0.0, 15.0),
        )

        with self.assertRaisesRegex(TimeoutError, "still moving"):
            executor.drag_plan(plan)

        self.assertEqual(controller.calls[-1], ("magnet_off", True))

    def test_drag_step_turns_magnet_off_when_wait_fails(self) -> None:
        controller = FakeController()
        controller.raise_on_wait = True
        executor = MotionExecutor(controller, self._config())

        with self.assertRaisesRegex(TimeoutError, "still moving"):
            executor.drag_step("x+")

        self.assertEqual(controller.calls[-1], ("magnet_off", True))


if __name__ == "__main__":
    unittest.main()

"""Tests for operator confirmation triggers."""

from __future__ import annotations

import unittest

from src.confirm import ClickSequenceDetector, GrblPinClickTrigger
from src.machine.grbl import GrblStatus


class ConfirmTests(unittest.TestCase):
    def test_click_sequence_detector_distinguishes_double_and_triple_clicks(self) -> None:
        detector = ClickSequenceDetector(min_gap_s=0.12, max_gap_s=0.7, debounce_s=0.07)

        self.assertIsNone(detector.update(pressed=True, now_s=1.0))
        self.assertIsNone(detector.update(pressed=False, now_s=1.1))
        self.assertEqual(detector.update(pressed=True, now_s=1.2).kind, "press")
        self.assertIsNone(detector.update(pressed=False, now_s=1.3))
        self.assertEqual(detector.update(pressed=True, now_s=1.45).count, 2)
        self.assertIsNone(detector.update(pressed=False, now_s=1.5))

        event = detector.update(pressed=False, now_s=2.3)

        self.assertEqual(event.kind, "double-click")
        self.assertAlmostEqual(event.gap_s, 0.25)

        self.assertEqual(detector.update(pressed=True, now_s=3.0).count, 1)
        self.assertIsNone(detector.update(pressed=False, now_s=3.1))
        self.assertEqual(detector.update(pressed=True, now_s=3.25).count, 2)
        self.assertIsNone(detector.update(pressed=False, now_s=3.3))
        event = detector.update(pressed=True, now_s=3.45)
        self.assertEqual(event.kind, "triple-click")

    def test_grbl_pin_trigger_defaults_to_absent_pressed_and_supports_reset(self) -> None:
        statuses = iter(
            [
                GrblStatus(raw="<Idle|Pn:XYZ>", state="Idle", pins="XYZ"),
                GrblStatus(raw="<Idle|Pn:XZ>", state="Idle", pins="XZ"),
                GrblStatus(raw="<Idle|Pn:XYZ>", state="Idle", pins="XYZ"),
                GrblStatus(raw="<Idle|Pn:XZ>", state="Idle", pins="XZ"),
                GrblStatus(raw="<Idle|Pn:XYZ>", state="Idle", pins="XYZ"),
                GrblStatus(raw="<Idle|Pn:XZ>", state="Idle", pins="XZ"),
            ]
        )
        presses = []
        trigger = GrblPinClickTrigger(
            read_status=lambda: next(statuses),
            poll_s=0.0,
            min_gap_s=0.0,
            max_gap_s=10.0,
            debounce_s=0.0,
            on_press=presses.append,
        )

        event = trigger.wait()

        self.assertEqual(event.source, "grbl-pin-triple-click")
        self.assertEqual(event.kind, "reset")
        self.assertIn("axis=Y", event.detail)
        self.assertEqual(presses, ["axis=Y click=1 pins=XZ", "axis=Y click=2 pins=XZ"])


if __name__ == "__main__":
    unittest.main()

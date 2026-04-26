"""Tests for the human-vs-engine demo loop."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.board import CaptureExecution
from src.board_state import BoardState
from src.config import AppConfig
from src.confirm import ConfirmationEvent
from src.demo import run_human_machine_demo
from src.vision.contracts import ExternalVisionPiece, ExternalVisionSnapshot


class FakeExecutor:
    """Record motion calls instead of talking to GRBL."""

    def __init__(self) -> None:
        self.config = AppConfig()
        self.drag_calls = 0
        self.jog_calls = []

    def drag_plan(self, _plan, *, include_compensation: bool = True) -> None:
        self.drag_calls += 1

    def jog(self, dx_mm: float, dy_mm: float, *, feed_mm_min: float | None = None) -> None:
        self.jog_calls.append((dx_mm, dy_mm, feed_mm_min))


class FakeProbe:
    def __init__(self, snapshots: list[ExternalVisionSnapshot], states: list[BoardState] | None = None) -> None:
        self.snapshots = list(snapshots)
        self.states = list(states or [])

    def capture_snapshot(self) -> ExternalVisionSnapshot:
        return self.snapshots.pop(0)

    def capture(self):
        if self.states:
            return self.states.pop(0)
        raise AssertionError("vision verification is disabled in this test")


class FakeTrigger:
    def __init__(self, commands: list[ConfirmationEvent] | None = None) -> None:
        self.commands = commands
        self.count = 0

    def wait(self) -> ConfirmationEvent:
        if self.commands is not None:
            command = self.commands.pop(0)
            if isinstance(command, Exception):
                raise command
            return command
        self.count += 1
        return ConfirmationEvent(source="test", detail=f"count={self.count}")


class DemoTests(unittest.TestCase):
    def test_demo_keeps_capture_slots_without_capture_vision(self) -> None:
        snapshots = [
            ExternalVisionSnapshot(
                provider="test",
                board_pieces=[
                    ExternalVisionPiece(cell=(2, 1), piece="b_pao"),
                    ExternalVisionPiece(cell=(2, 4), piece="r_zu"),
                ],
            ),
            ExternalVisionSnapshot(
                provider="test",
                board_pieces=[
                    ExternalVisionPiece(cell=(2, 4), piece="b_pao"),
                    ExternalVisionPiece(cell=(2, 5), piece="r_zu"),
                ],
            ),
        ]

        with patch("src.turn.get_best_move", side_effect=["h2e2", "e2d2"]):
            summary = run_human_machine_demo(
                executor=FakeExecutor(),
                probe=FakeProbe(snapshots),
                trigger=FakeTrigger(),
                carriage_cell=(2, 1),
                max_turns=2,
                verify_vision=False,
            )

        first = summary.records[0].turn
        second = summary.records[1].turn

        self.assertEqual(summary.completed_turns, 2)
        self.assertIsInstance(first.execution, CaptureExecution)
        self.assertIsInstance(second.execution, CaptureExecution)
        self.assertEqual(first.execution.capture_slot, 0)
        self.assertEqual(second.execution.capture_slot, 1)
        self.assertEqual(second.final_state.filled_capture_slots, {0, 1})

    def test_demo_reset_updates_only_software_carriage_position(self) -> None:
        executor = FakeExecutor()
        trigger = FakeTrigger(
            [
                ConfirmationEvent(source="test", kind="reset"),
                ConfirmationEvent(source="test", kind="confirm"),
            ]
        )
        snapshot = ExternalVisionSnapshot(
            provider="test",
            board_pieces=[ExternalVisionPiece(cell=(2, 1), piece="b_pao")],
        )

        with patch("src.turn.get_best_move", return_value="h2e2"):
            summary = run_human_machine_demo(
                executor=executor,
                probe=FakeProbe([snapshot]),
                trigger=trigger,
                carriage_cell=(9, 8),
                reset_carriage_cell=(0, 0),
                max_turns=1,
                verify_vision=False,
            )

        self.assertEqual(summary.reset_count, 1)
        self.assertEqual(summary.completed_turns, 1)
        expected_dx = 2 * executor.config.motion.x_cell_pitch_mm
        expected_dy = executor.config.motion.y_cell_pitch_mm
        self.assertAlmostEqual(executor.jog_calls[0][0], expected_dx)
        self.assertAlmostEqual(executor.jog_calls[0][1], expected_dy)

    def test_demo_allows_unbounded_turns_when_max_turns_is_none(self) -> None:
        snapshots = [
            ExternalVisionSnapshot(
                provider="test",
                board_pieces=[ExternalVisionPiece(cell=(2, 1), piece="b_pao")],
            ),
            ExternalVisionSnapshot(
                provider="test",
                board_pieces=[ExternalVisionPiece(cell=(2, 4), piece="b_pao")],
            ),
        ]
        trigger = FakeTrigger(
            [
                ConfirmationEvent(source="test", kind="confirm"),
                ConfirmationEvent(source="test", kind="confirm"),
            ]
        )

        with patch("src.turn.get_best_move", side_effect=["h2e2", "e2d2"]):
            summary = run_human_machine_demo(
                executor=FakeExecutor(),
                probe=FakeProbe(
                    snapshots,
                    states=[
                        BoardState(occupied_cells={(2, 4)}),
                        BoardState(occupied_cells={(0, 0)}),
                    ],
                ),
                trigger=trigger,
                max_turns=None,
                verify_vision=True,
            )

        self.assertEqual(summary.requested_turns, None)
        self.assertEqual(summary.completed_turns, 2)
        self.assertEqual(summary.halt_reason, "mismatch")


if __name__ == "__main__":
    unittest.main()

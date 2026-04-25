"""Tests for single-turn closed-loop orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.config import AppConfig
from src.board_state import BoardState
from src.turn import TurnError, execute_engine_turn, uci_to_cells, verify_board_state
from src.vision.contracts import ExternalVisionPiece, ExternalVisionSnapshot


class FakeExecutor:
    """Record motion calls instead of talking to GRBL."""

    def __init__(self) -> None:
        self.config = AppConfig()
        self.drag_calls = 0
        self.jog_calls: list[tuple[float, float, float | None]] = []

    def drag_plan(self, _plan, *, include_compensation: bool = True) -> None:
        self.drag_calls += 1

    def jog(self, dx_mm: float, dy_mm: float, *, feed_mm_min: float | None = None) -> None:
        self.jog_calls.append((dx_mm, dy_mm, feed_mm_min))


class StaticProbe:
    def __init__(self, state: BoardState | None) -> None:
        self.state = state

    def capture(self) -> BoardState | None:
        return self.state


class TurnTests(unittest.TestCase):
    def test_uci_to_cells_uses_project_orientation(self) -> None:
        self.assertEqual(uci_to_cells("h2e2"), ((2, 1), (2, 4)))
        self.assertEqual(uci_to_cells("a0i9"), ((0, 8), (9, 0)))

    def test_uci_to_cells_rejects_invalid_move(self) -> None:
        with self.assertRaisesRegex(TurnError, "Unparseable"):
            uci_to_cells("z9a0")

    def test_execute_engine_turn_moves_to_empty_destination(self) -> None:
        snapshot = ExternalVisionSnapshot(
            provider="test",
            board_pieces=[ExternalVisionPiece(cell=(2, 1), piece="r_pao")],
        )
        executor = FakeExecutor()

        with patch("src.turn.get_best_move", return_value="h2e2") as get_best_move_mock:
            result = execute_engine_turn(
                executor=executor,
                snapshot=snapshot,
                carriage_cell=(0, 0),
                side_to_move="red",
                engine_path="/fake/pikafish",
                depth=8,
            )

        self.assertEqual(result.kind, "move")
        self.assertEqual(result.start, (2, 1))
        self.assertEqual(result.end, (2, 4))
        self.assertEqual(result.visual_status, "skipped")
        self.assertEqual(executor.drag_calls, 1)
        self.assertEqual(get_best_move_mock.call_args.kwargs["depth"], 8)

    def test_execute_engine_turn_captures_occupied_destination(self) -> None:
        snapshot = ExternalVisionSnapshot(
            provider="test",
            board_pieces=[
                ExternalVisionPiece(cell=(2, 1), piece="r_pao"),
                ExternalVisionPiece(cell=(2, 4), piece="b_zu"),
            ],
        )
        expected_after = BoardState(occupied_cells={(2, 4)}, filled_capture_slots={3})

        with patch("src.turn.get_best_move", return_value="h2e2"):
            result = execute_engine_turn(
                executor=FakeExecutor(),
                snapshot=snapshot,
                carriage_cell=(2, 4),
                capture_slot=3,
                probe=StaticProbe(expected_after),
            )

        self.assertEqual(result.kind, "capture")
        self.assertEqual(result.execution.capture_slot, 3)
        self.assertEqual(result.visual_status, "ok")

    def test_verify_board_state_reports_main_board_diff(self) -> None:
        status, diff = verify_board_state(
            StaticProbe(BoardState(occupied_cells={(0, 1)})),
            BoardState(occupied_cells={(0, 0)}),
        )

        self.assertEqual(status, "mismatch")
        self.assertEqual(diff["missing_cells"], [[0, 0]])
        self.assertEqual(diff["extra_cells"], [[0, 1]])


if __name__ == "__main__":
    unittest.main()

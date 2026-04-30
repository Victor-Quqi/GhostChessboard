"""Tests for Web console game state and vision synchronization."""

from __future__ import annotations

import unittest

from src.vision.contracts import ExternalVisionPiece, ExternalVisionSnapshot
from src.web.state import WebGameState, infer_physical_move


class WebStateTests(unittest.TestCase):
    def test_vision_sync_accepts_legal_physical_move_and_advances_turn(self) -> None:
        state = WebGameState()
        pieces = dict(state.pieces)
        pieces.pop((3, 0))
        pieces[(4, 0)] = "r_zu"

        result = state.sync_from_snapshot(_snapshot(pieces))

        self.assertEqual(result.status, "legal_move")
        self.assertEqual(result.start, (3, 0))
        self.assertEqual(result.end, (4, 0))
        self.assertEqual(state.side_to_move, "black")
        self.assertEqual(state.last_move["source"], "vision")

    def test_vision_sync_updates_board_but_warns_on_illegal_physical_move(self) -> None:
        state = WebGameState()
        pieces = dict(state.pieces)
        pieces.pop((6, 0))
        pieces[(5, 0)] = "b_zu"

        result = state.sync_from_snapshot(_snapshot(pieces))

        self.assertEqual(result.status, "illegal_move")
        self.assertEqual(state.side_to_move, "red")
        self.assertIn((5, 0), state.pieces)
        self.assertIsNotNone(state.sync_warning)

    def test_infer_physical_capture_from_replaced_target(self) -> None:
        previous = {
            (0, 4): "r_jiang",
            (9, 3): "b_jiang",
            (3, 0): "r_ju",
            (3, 8): "b_zu",
        }
        current = {
            (0, 4): "r_jiang",
            (9, 3): "b_jiang",
            (3, 8): "r_ju",
        }

        result = infer_physical_move(previous, current, side_to_move="red")

        self.assertEqual(result.status, "legal_move")
        self.assertTrue(result.capture)
        self.assertEqual(result.start, (3, 0))
        self.assertEqual(result.end, (3, 8))

    def test_ambiguous_vision_diff_can_be_forced_without_turn_advance(self) -> None:
        state = WebGameState()
        pieces = dict(state.pieces)
        pieces.pop((3, 0))
        pieces.pop((3, 2))

        result = state.sync_from_snapshot(_snapshot(pieces), force=True)

        self.assertEqual(result.status, "forced")
        self.assertEqual(state.side_to_move, "red")
        self.assertEqual(state.sync_warning, "Forced state rebuild from vision.")

    def test_vision_sync_preserves_known_capture_slots_when_snapshot_has_none(self) -> None:
        state = WebGameState()
        state.captured[0] = "b_zu"
        pieces = dict(state.pieces)

        state.sync_from_snapshot(_snapshot(pieces))

        self.assertEqual(state.captured, {0: "b_zu"})

    def test_export_and_restore_preserves_board_turn_captures_and_carriage(self) -> None:
        state = WebGameState(carriage_cell=(5, 0))
        state.pieces.pop((6, 0))
        state.pieces.pop((3, 0))
        state.pieces[(5, 0)] = "r_zu"
        state.captured[0] = "b_zu"
        state.side_to_move = "black"

        restored = WebGameState()
        restored.restore_state(state.export_state())

        self.assertEqual(restored.pieces[(5, 0)], "r_zu")
        self.assertNotIn((3, 0), restored.pieces)
        self.assertNotIn((6, 0), restored.pieces)
        self.assertEqual(restored.captured, {0: "b_zu"})
        self.assertEqual(restored.carriage_cell, (5, 0))
        self.assertEqual(restored.side_to_move, "black")

    def test_export_includes_terminal_status_for_checkmate(self) -> None:
        state = WebGameState()
        state.pieces = _black_checkmate_position()
        state.side_to_move = "black"
        state.refresh_terminal_status()

        exported = state.export_state()
        payload = state.to_dict()

        self.assertTrue(exported["game_over"])
        self.assertEqual(exported["winner"], "red")
        self.assertEqual(exported["reason"], "checkmate")
        self.assertTrue(payload["game_over"])
        self.assertEqual(payload["winner"], "red")


def _snapshot(pieces: dict[tuple[int, int], str]) -> ExternalVisionSnapshot:
    return ExternalVisionSnapshot(
        provider="test",
        board_pieces=[
            ExternalVisionPiece(cell=cell, piece=piece)
            for cell, piece in sorted(pieces.items())
        ],
    )


def _black_checkmate_position() -> dict[tuple[int, int], str]:
    return {
        (0, 4): "r_jiang",
        (9, 4): "b_jiang",
        (8, 4): "r_ju",
        (9, 3): "r_ju",
        (9, 5): "r_ju",
        (8, 3): "r_ju",
        (8, 5): "r_ju",
    }


if __name__ == "__main__":
    unittest.main()

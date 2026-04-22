"""Tests for parsing Xiangqi FEN into a BoardState."""

from __future__ import annotations

import unittest

from src.vision import board_state_from_xiangqi_fen

STANDARD_OPENING_FEN = (
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
)


class BoardStateFromFenTests(unittest.TestCase):
    def test_standard_opening_has_32_pieces_at_expected_cells(self) -> None:
        state = board_state_from_xiangqi_fen(STANDARD_OPENING_FEN)

        self.assertEqual(len(state.occupied_cells), 32)
        self.assertEqual(state.filled_capture_slots, set())
        self.assertIsNone(state.carriage_cell)

        expected_red_back_rank = {(0, y) for y in range(9)}
        expected_black_back_rank = {(9, y) for y in range(9)}
        self.assertTrue(expected_red_back_rank.issubset(state.occupied_cells))
        self.assertTrue(expected_black_back_rank.issubset(state.occupied_cells))

        self.assertIn((2, 1), state.occupied_cells)
        self.assertIn((2, 7), state.occupied_cells)
        self.assertIn((7, 1), state.occupied_cells)
        self.assertIn((7, 7), state.occupied_cells)

        for y in (0, 2, 4, 6, 8):
            self.assertIn((3, y), state.occupied_cells)
            self.assertIn((6, y), state.occupied_cells)

    def test_carriage_cell_is_recorded_when_provided(self) -> None:
        state = board_state_from_xiangqi_fen(STANDARD_OPENING_FEN, carriage_cell=(0, 0))
        self.assertEqual(state.carriage_cell, (0, 0))

    def test_asymmetric_fen_roundtrips_with_serializer(self) -> None:
        fen = "r3k4/9/9/9/9/9/9/7C1/9/4K3R w - - 0 1"
        state = board_state_from_xiangqi_fen(fen)

        self.assertEqual(
            state.occupied_cells,
            {(9, 8), (9, 4), (2, 1), (0, 4), (0, 0)},
        )

    def test_rejects_wrong_number_of_ranks(self) -> None:
        with self.assertRaisesRegex(ValueError, "10 ranks"):
            board_state_from_xiangqi_fen("9/9/9 w - - 0 1")

    def test_rejects_rank_that_does_not_cover_nine_columns(self) -> None:
        fen = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABN w - - 0 1"
        with self.assertRaisesRegex(ValueError, "does not cover 9 columns"):
            board_state_from_xiangqi_fen(fen)

    def test_rejects_unknown_symbol(self) -> None:
        fen = "rnbakabnz/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
        with self.assertRaisesRegex(ValueError, "Unsupported FEN symbol"):
            board_state_from_xiangqi_fen(fen)


if __name__ == "__main__":
    unittest.main()

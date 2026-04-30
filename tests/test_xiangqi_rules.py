"""Tests for Xiangqi rule validation using GhostVision piece labels."""

from __future__ import annotations

import unittest

from src.xiangqi_rules import (
    XiangqiRuleError,
    has_legal_move,
    pieces_to_xiangqi_fen,
    standard_starting_pieces,
    terminal_status,
    validate_legal_move,
)


class XiangqiRulesTests(unittest.TestCase):
    def test_rook_requires_clear_straight_path(self) -> None:
        pieces = self._base({"r_ju": (0, 0), "b_zu": (0, 8), "r_zu": (0, 4)})

        self._assert_illegal(pieces, (0, 0), (0, 8))

        del pieces[(0, 4)]
        validate_legal_move(pieces, (0, 0), (0, 8), side_to_move="red")

    def test_horse_leg_blocks_l_move(self) -> None:
        pieces = self._base({"r_ma": (0, 0), "r_zu": (1, 0)})

        self._assert_illegal(pieces, (0, 0), (2, 1))

        del pieces[(1, 0)]
        validate_legal_move(pieces, (0, 0), (2, 1), side_to_move="red")

    def test_elephant_eye_and_river_are_enforced(self) -> None:
        pieces = self._base({"r_xiang": (2, 0), "b_zu": (4, 2)})
        validate_legal_move(pieces, (2, 0), (4, 2), side_to_move="red")

        pieces[(3, 1)] = "r_zu"
        self._assert_illegal(pieces, (2, 0), (4, 2))

        pieces = self._base({"r_xiang": (4, 2)})
        self._assert_illegal(pieces, (4, 2), (6, 4))

    def test_advisor_and_general_must_stay_in_palace(self) -> None:
        pieces = self._base({"r_shi": (0, 3)})
        validate_legal_move(pieces, (0, 3), (1, 4), side_to_move="red")
        self._assert_illegal(pieces, (0, 3), (1, 2))

        pieces = self._base({"r_jiang": (0, 4), "b_jiang": (9, 3)})
        validate_legal_move(pieces, (0, 4), (1, 4), side_to_move="red")
        self._assert_illegal(pieces, (0, 4), (0, 6))

    def test_cannon_uses_exactly_one_screen_when_capturing(self) -> None:
        pieces = self._base({"r_pao": (2, 1), "r_zu": (2, 4), "b_zu": (2, 7)})
        validate_legal_move(pieces, (2, 1), (2, 7), side_to_move="red")

        del pieces[(2, 4)]
        self._assert_illegal(pieces, (2, 1), (2, 7))
        validate_legal_move(pieces, (2, 1), (2, 4), side_to_move="red")

    def test_soldier_cannot_move_sideways_before_crossing_river(self) -> None:
        pieces = self._base({"r_zu": (3, 4)})
        validate_legal_move(pieces, (3, 4), (4, 4), side_to_move="red")
        self._assert_illegal(pieces, (3, 4), (3, 5))

        pieces = self._base({"r_zu": (5, 4)})
        validate_legal_move(pieces, (5, 4), (5, 5), side_to_move="red")
        self._assert_illegal(pieces, (5, 4), (4, 4))

    def test_rejects_same_side_capture_and_wrong_turn(self) -> None:
        pieces = self._base({"r_ju": (0, 0), "r_zu": (0, 8)})

        self._assert_illegal(pieces, (0, 0), (0, 8), "same-side")
        self._assert_illegal(pieces, (0, 0), (0, 1), "not red", side_to_move="black")

    def test_move_cannot_expose_general_to_check(self) -> None:
        pieces = {
            (0, 4): "r_jiang",
            (9, 3): "b_jiang",
            (9, 4): "b_ju",
            (2, 4): "r_ju",
        }

        self._assert_illegal(pieces, (2, 4), (2, 5), "leaves red in check")

    def test_generals_may_not_face_after_a_move(self) -> None:
        pieces = {
            (0, 4): "r_jiang",
            (9, 4): "b_jiang",
            (5, 4): "r_ju",
        }

        self._assert_illegal(pieces, (5, 4), (5, 5), "Generals may not face")

    def test_standard_starting_position_serializes_to_fen(self) -> None:
        fen = pieces_to_xiangqi_fen(standard_starting_pieces(), side_to_move="red")

        self.assertEqual(
            fen,
            "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
        )

    def test_checkmate_position_has_no_legal_move_and_reports_winner(self) -> None:
        pieces = _black_checkmate_position()

        self.assertFalse(has_legal_move(pieces, "black"))
        status = terminal_status(pieces, "black")

        self.assertTrue(status.game_over)
        self.assertEqual(status.reason, "checkmate")
        self.assertEqual(status.winner, "red")

    def _base(self, items: dict[str, tuple[int, int]]) -> dict[tuple[int, int], str]:
        pieces = {
            (0, 4): "r_jiang",
            (9, 3): "b_jiang",
        }
        for piece, cell in items.items():
            pieces[cell] = piece
        return pieces

    def _assert_illegal(
        self,
        pieces: dict[tuple[int, int], str],
        start: tuple[int, int],
        end: tuple[int, int],
        message: str | None = None,
        *,
        side_to_move: str = "red",
    ) -> None:
        with self.assertRaises(XiangqiRuleError) as context:
            validate_legal_move(pieces, start, end, side_to_move=side_to_move)
        if message is not None:
            self.assertIn(message, str(context.exception))


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

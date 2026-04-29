"""Tests for logical grid and capture-area coordinate helpers."""

from __future__ import annotations

import unittest

from src.coords import capture_slot_to_cell


class CoordsTests(unittest.TestCase):
    def test_capture_slots_fill_outer_column_before_board_side_column(self) -> None:
        self.assertEqual(capture_slot_to_cell(0), (0, 10))
        self.assertEqual(capture_slot_to_cell(9), (9, 10))
        self.assertEqual(capture_slot_to_cell(10), (0, 9))
        self.assertEqual(capture_slot_to_cell(19), (9, 9))


if __name__ == "__main__":
    unittest.main()

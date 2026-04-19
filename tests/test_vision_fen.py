"""Tests for Xiangqi FEN serialization from external vision snapshots."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.vision import load_external_vision_snapshot, snapshot_to_xiangqi_fen


class VisionFenTests(unittest.TestCase):
    def test_snapshot_to_xiangqi_fen_serializes_asymmetric_board(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [
            {"cell": [9, 8], "piece": "b_ju"},
            {"cell": [9, 4], "piece": "b_jiang"},
            {"cell": [2, 1], "piece": "r_pao"},
            {"cell": [0, 4], "piece": "r_jiang"},
            {"cell": [0, 0], "piece": "r_ju"}
          ]
        }
        """

        snapshot = self._load(payload)
        fen = snapshot_to_xiangqi_fen(snapshot, side_to_move="w")

        self.assertEqual(fen, "r3k4/9/9/9/9/9/9/7C1/9/4K3R w - - 0 1")

    def test_snapshot_to_xiangqi_fen_supports_black_to_move(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [
            {"cell": [9, 8], "piece": "b_ju"},
            {"cell": [0, 0], "piece": "r_ju"}
          ]
        }
        """

        snapshot = self._load(payload)
        fen = snapshot_to_xiangqi_fen(snapshot, side_to_move="b", halfmove_clock=3, fullmove_number=18)

        self.assertEqual(fen, "r8/9/9/9/9/9/9/9/9/8R b - - 3 18")

    def test_snapshot_to_xiangqi_fen_accepts_red_black_aliases(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [
            {"cell": [9, 8], "piece": "b_ju"},
            {"cell": [0, 0], "piece": "r_ju"}
          ]
        }
        """

        snapshot = self._load(payload)

        self.assertEqual(
            snapshot_to_xiangqi_fen(snapshot, side_to_move="red"),
            "r8/9/9/9/9/9/9/9/9/8R w - - 0 1",
        )
        self.assertEqual(
            snapshot_to_xiangqi_fen(snapshot, side_to_move="black"),
            "r8/9/9/9/9/9/9/9/9/8R b - - 0 1",
        )

    def test_snapshot_to_xiangqi_fen_rejects_unknown_piece(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [
            {"cell": [0, 0], "piece": "mystery_piece"}
          ]
        }
        """

        snapshot = self._load(payload)
        with self.assertRaisesRegex(ValueError, "Unsupported piece label"):
            snapshot_to_xiangqi_fen(snapshot)

    def _load(self, payload: str):
        path = _write_temp_json(payload)
        self.addCleanup(path.unlink, missing_ok=True)
        return load_external_vision_snapshot(path)


def _write_temp_json(payload: str) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        handle.write(payload)
        return Path(handle.name)


if __name__ == "__main__":
    unittest.main()

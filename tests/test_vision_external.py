"""Tests for external vision result loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.vision import build_board_state_from_snapshot, load_external_vision_snapshot, snapshot_to_dict


class ExternalVisionResultTests(unittest.TestCase):
    def test_load_snapshot_and_project_board_state(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "frame_id": "frame-001",
          "produced_at": "2026-04-09T10:00:00+08:00",
          "board_pieces": [
            {"cell": [0, 0], "piece": "r_ju", "confidence": 0.98},
            {"cell": "4,0", "piece": "r_jiang", "confidence": 0.99}
          ],
          "capture_pieces": [
            {"slot": 3, "piece": "b_zu", "confidence": 0.87}
          ],
          "pose": {
            "corners_px": {
              "top_left": [10.0, 20.0],
              "top_right": [110.0, 20.0],
              "bottom_right": [110.0, 220.0],
              "bottom_left": [10.0, 220.0]
            },
            "main_board_points_px": {
              "0,0": [11.0, 21.0],
              "4,0": [55.0, 21.0]
            },
            "confidence": 0.95
          },
          "metadata": {
            "model": "rtmpose-4pt"
          }
        }
        """

        snapshot = self._load(payload)
        board_state = build_board_state_from_snapshot(snapshot, carriage_cell=(9, 10))

        self.assertEqual(snapshot.provider, "ghostvision")
        self.assertEqual(len(snapshot.board_pieces), 2)
        self.assertEqual(board_state.occupied_cells, {(0, 0), (4, 0)})
        self.assertEqual(board_state.filled_capture_slots, {3})
        self.assertEqual(board_state.carriage_cell, (9, 10))

        normalized = snapshot_to_dict(snapshot)
        self.assertEqual(normalized["pose"]["corners_px"]["top_left"], [10.0, 20.0])
        self.assertEqual(normalized["pose"]["main_board_points_px"]["4,0"], [55.0, 21.0])

    def test_reject_duplicate_board_cells(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [
            {"cell": [1, 1], "piece": "r_ma"},
            {"cell": [1, 1], "piece": "b_ma"}
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "Duplicate board cell"):
            self._load(payload)

    def test_reject_invalid_pose_corner_set(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [],
          "pose": {
            "corners_px": {
              "top_left": [0, 0],
              "top_right": [1, 0]
            }
          }
        }
        """

        with self.assertRaisesRegex(ValueError, "pose.corners_px"):
            self._load(payload)

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

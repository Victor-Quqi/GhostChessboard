"""Tests for the scenario runner (no hardware)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.board import BoardController
from src.board_state import BoardState
from src.scenario import (
    Scenario,
    ScenarioError,
    ScenarioStep,
    load_scenario,
    parse_scenario,
    run_scenario,
)

STANDARD_OPENING_FEN = (
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
)


class FakeExecutor:
    """Record jog/drag calls instead of talking to hardware."""

    def __init__(self) -> None:
        self.drag_calls: list[tuple[tuple[tuple[str, int], ...], bool]] = []
        self.jog_calls: list[tuple[float, float]] = []

    def drag_route(self, segments, *, include_compensation: bool = True) -> None:
        self.drag_calls.append(
            (tuple((seg.direction, seg.cells) for seg in segments), include_compensation)
        )

    def jog(self, dx_mm: float, dy_mm: float, *, feed_mm_min: float | None = None) -> None:
        self.jog_calls.append((dx_mm, dy_mm))


class FakeProbe:
    """Returns the BoardController's current state by default, pluggable per step."""

    def __init__(self, board: BoardController) -> None:
        self._board = board
        self.override: BoardState | None = None
        self.calls = 0

    def capture(self) -> BoardState | None:
        self.calls += 1
        if self.override is not None:
            return self.override
        state = self._board.state
        return BoardState(
            occupied_cells=set(state.occupied_cells),
            filled_capture_slots=set(state.filled_capture_slots),
            carriage_cell=state.carriage_cell,
        )


class ScenarioParsingTests(unittest.TestCase):
    def test_parse_minimal_scenario(self) -> None:
        raw = {
            "name": "smoke",
            "initial": {"fen": STANDARD_OPENING_FEN, "carriage": [0, 0]},
            "steps": [
                {"kind": "move", "start": [0, 0], "end": [0, 1]},
                {"kind": "capture", "start": [2, 1], "end": [2, 7], "slot": 0},
            ],
        }

        scenario = parse_scenario(raw)

        self.assertEqual(scenario.name, "smoke")
        self.assertEqual(scenario.initial_state.carriage_cell, (0, 0))
        self.assertEqual(len(scenario.initial_state.occupied_cells), 32)
        self.assertEqual(scenario.steps[0], ScenarioStep("move", (0, 0), (0, 1), None))
        self.assertEqual(scenario.steps[1], ScenarioStep("capture", (2, 1), (2, 7), 0))

    def test_rejects_unknown_step_kind(self) -> None:
        raw = {
            "name": "bad",
            "initial": {"fen": STANDARD_OPENING_FEN, "carriage": [0, 0]},
            "steps": [{"kind": "teleport", "start": [0, 0], "end": [0, 1]}],
        }
        with self.assertRaisesRegex(ScenarioError, "must be 'move' or 'capture'"):
            parse_scenario(raw)

    def test_rejects_move_with_slot(self) -> None:
        raw = {
            "name": "bad",
            "initial": {"fen": STANDARD_OPENING_FEN},
            "steps": [{"kind": "move", "start": [0, 0], "end": [0, 1], "slot": 2}],
        }
        with self.assertRaisesRegex(ScenarioError, "declares 'slot'"):
            parse_scenario(raw)

    def test_accepts_string_cells(self) -> None:
        raw = {
            "name": "mix",
            "initial": {"fen": STANDARD_OPENING_FEN, "carriage": "0,0"},
            "steps": [{"kind": "move", "start": "0,0", "end": "0,1"}],
        }
        scenario = parse_scenario(raw)
        self.assertEqual(scenario.initial_state.carriage_cell, (0, 0))
        self.assertEqual(scenario.steps[0].start, (0, 0))

    def test_load_scenario_reads_file(self) -> None:
        payload = {
            "name": "disk",
            "initial": {"fen": STANDARD_OPENING_FEN, "carriage": [0, 0]},
            "steps": [{"kind": "move", "start": [0, 0], "end": [0, 1]}],
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)

        scenario = load_scenario(path)
        self.assertEqual(scenario.name, "disk")


class ScenarioRunTests(unittest.TestCase):
    def _make_board(self, scenario: Scenario) -> tuple[BoardController, FakeExecutor]:
        executor = FakeExecutor()
        board = BoardController(executor, scenario.initial_state)
        return board, executor

    def _standard_scenario(self, steps: list[dict]) -> Scenario:
        return parse_scenario(
            {
                "name": "t",
                "initial": {"fen": STANDARD_OPENING_FEN, "carriage": [0, 0]},
                "steps": steps,
            }
        )

    def test_run_all_steps_without_probe(self) -> None:
        scenario = self._standard_scenario(
            [
                {"kind": "move", "start": [3, 0], "end": [4, 0]},
                {"kind": "move", "start": [4, 0], "end": [5, 0]},
            ]
        )
        board, executor = self._make_board(scenario)

        summary = run_scenario(scenario, board)

        self.assertEqual(summary.total_steps, 2)
        self.assertEqual(summary.executed_steps, 2)
        self.assertIsNone(summary.halted_at_index)
        self.assertEqual(board.state.carriage_cell, (5, 0))
        self.assertIn((5, 0), board.state.occupied_cells)
        self.assertNotIn((3, 0), board.state.occupied_cells)
        self.assertTrue(all(result.visual_status == "skipped" for result in summary.results))
        self.assertGreaterEqual(len(executor.drag_calls), 2)

    def test_halt_on_execution_error(self) -> None:
        scenario = self._standard_scenario(
            [
                {"kind": "move", "start": [0, 0], "end": [0, 2]},
            ]
        )
        board, _ = self._make_board(scenario)

        summary = run_scenario(scenario, board)

        self.assertEqual(summary.halted_at_index, 0)
        self.assertTrue(summary.halt_reason.startswith("execution_error"))
        self.assertFalse(summary.results[0].executed)

    def test_probe_ok_records_ok_status(self) -> None:
        scenario = self._standard_scenario(
            [{"kind": "move", "start": [3, 0], "end": [4, 0]}]
        )
        board, _ = self._make_board(scenario)
        probe = FakeProbe(board)

        summary = run_scenario(scenario, board, probe=probe)

        self.assertEqual(summary.results[0].visual_status, "ok")
        self.assertEqual(probe.calls, 1)

    def test_probe_mismatch_halts_and_reports_diff(self) -> None:
        scenario = self._standard_scenario(
            [
                {"kind": "move", "start": [3, 0], "end": [4, 0]},
                {"kind": "move", "start": [4, 0], "end": [5, 0]},
            ]
        )
        board, _ = self._make_board(scenario)
        probe = FakeProbe(board)
        probe.override = BoardState(occupied_cells=set(), filled_capture_slots=set())

        summary = run_scenario(scenario, board, probe=probe)

        self.assertEqual(summary.halted_at_index, 0)
        self.assertEqual(summary.halt_reason, "visual_mismatch")
        self.assertEqual(summary.results[0].visual_status, "mismatch")
        self.assertIsNotNone(summary.results[0].visual_diff)
        self.assertEqual(summary.executed_steps, 1)

    def test_probe_unavailable_halts(self) -> None:
        scenario = self._standard_scenario(
            [{"kind": "move", "start": [3, 0], "end": [4, 0]}]
        )
        board, _ = self._make_board(scenario)

        class NullProbe:
            def capture(self):
                return None

        summary = run_scenario(scenario, board, probe=NullProbe())

        self.assertEqual(summary.halted_at_index, 0)
        self.assertEqual(summary.halt_reason, "visual_unavailable")
        self.assertEqual(summary.results[0].visual_status, "unavailable")

    def test_probe_error_halts(self) -> None:
        scenario = self._standard_scenario(
            [{"kind": "move", "start": [3, 0], "end": [4, 0]}]
        )
        board, _ = self._make_board(scenario)

        class FailingProbe:
            def capture(self):
                raise RuntimeError("camera offline")

        summary = run_scenario(scenario, board, probe=FailingProbe())

        self.assertEqual(summary.halted_at_index, 0)
        self.assertEqual(summary.halt_reason, "visual_probe_error: RuntimeError: camera offline")
        self.assertEqual(summary.results[0].visual_status, "probe_error: RuntimeError: camera offline")

    def test_capture_step_tracks_slot(self) -> None:
        scenario = parse_scenario(
            {
                "name": "cap",
                "initial": {
                    "fen": "9/9/9/9/9/9/9/9/9/R1r6 w - - 0 1",
                    "carriage": [0, 8],
                },
                "steps": [
                    {"kind": "capture", "start": [0, 8], "end": [0, 6], "slot": 3},
                ],
            }
        )
        board, _ = self._make_board(scenario)

        summary = run_scenario(scenario, board)

        self.assertIsNone(summary.halted_at_index)
        self.assertIn(3, board.state.filled_capture_slots)
        self.assertIn((0, 6), board.state.occupied_cells)


if __name__ == "__main__":
    unittest.main()

"""Tests for the UCI engine wrapper."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from src.engine import EngineError, get_best_move

INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


class EngineTests(unittest.TestCase):
    def test_get_best_move_runs_expected_uci_script(self) -> None:
        with patch("src.engine.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/opt/pikafish/pikafish"],
                returncode=0,
                stdout="uciok\nreadyok\nbestmove a3a4 ponder b9c7\n",
                stderr="",
            )

            move = get_best_move(
                INITIAL_FEN,
                engine_path=Path("/opt/pikafish/pikafish"),
                depth=12,
                threads=2,
                hash_mb=64,
                timeout_s=7.5,
            )

        self.assertEqual(move, "a3a4")
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0], [str(Path("/opt/pikafish/pikafish"))])
        self.assertEqual(kwargs["cwd"], str(Path("/opt/pikafish")))
        self.assertEqual(kwargs["timeout"], 7.5)
        self.assertIn("setoption name Threads value 2", kwargs["input"])
        self.assertIn("setoption name Hash value 64", kwargs["input"])
        self.assertIn(f"position fen {INITIAL_FEN}", kwargs["input"])
        self.assertIn("go depth 12", kwargs["input"])

    def test_get_best_move_rejects_missing_bestmove_line(self) -> None:
        with patch("src.engine.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/opt/pikafish/pikafish"],
                returncode=0,
                stdout="uciok\nreadyok\n",
                stderr="",
            )

            with self.assertRaisesRegex(EngineError, "bestmove"):
                get_best_move(INITIAL_FEN, engine_path="/opt/pikafish/pikafish")


if __name__ == "__main__":
    unittest.main()

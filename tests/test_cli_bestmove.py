"""Tests for the bestmove CLI entry point."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli import run
from src.cli_parser import build_parser

INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


class BestMoveCliTests(unittest.TestCase):
    def test_bestmove_command_prints_json_for_fen_input(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "bestmove",
                "--fen",
                INITIAL_FEN,
                "--engine",
                "/opt/pikafish/pikafish",
                "--depth",
                "8",
                "--json",
            ]
        )

        stdout = io.StringIO()
        with patch("src.cli_handlers.get_best_move", return_value="a3a4") as get_best_move_mock:
            with contextlib.redirect_stdout(stdout):
                run(args)

        get_best_move_mock.assert_called_once()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["fen"], INITIAL_FEN)
        self.assertEqual(payload["best_move"], "a3a4")
        self.assertEqual(payload["depth"], 8)
        self.assertEqual(payload["engine_path"], str(Path("/opt/pikafish/pikafish")))

    def test_bestmove_command_derives_fen_from_vision_result(self) -> None:
        payload = """
        {
          "provider": "ghostvision",
          "board_pieces": [
            {"cell": [9, 8], "piece": "b_ju"},
            {"cell": [9, 4], "piece": "b_jiang"},
            {"cell": [0, 4], "piece": "r_jiang"},
            {"cell": [0, 0], "piece": "r_ju"}
          ]
        }
        """
        input_path = _write_temp_json(payload)
        self.addCleanup(input_path.unlink, missing_ok=True)

        parser = build_parser()
        args = parser.parse_args(
            [
                "bestmove",
                "--vision-result",
                str(input_path),
                "--engine",
                "/opt/pikafish/pikafish",
                "--fen-side",
                "black",
            ]
        )

        stdout = io.StringIO()
        with patch("src.cli_handlers.get_best_move", return_value="a3a4") as get_best_move_mock:
            with contextlib.redirect_stdout(stdout):
                run(args)

        self.assertEqual(stdout.getvalue().strip(), "a3a4")
        self.assertEqual(get_best_move_mock.call_args.kwargs["engine_path"], Path("/opt/pikafish/pikafish"))
        self.assertEqual(get_best_move_mock.call_args.args[0], "r3k4/9/9/9/9/9/9/9/9/4K3R b - - 0 1")


def _write_temp_json(payload: str) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        handle.write(payload)
        return Path(handle.name)


if __name__ == "__main__":
    unittest.main()

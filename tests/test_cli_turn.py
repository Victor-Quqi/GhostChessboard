"""Tests for the single-turn CLI entry point."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli import _looks_like_web_process, build_parser, run


class FakeGrblController:
    """Minimal GRBL stand-in for exercising the CLI through MotionExecutor."""

    def __init__(self, _config) -> None:
        self.jogs = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        pass

    def initialize(self) -> None:
        pass

    def magnet_on(self, *_args, **_kwargs) -> None:
        pass

    def magnet_off(self, *_args, **_kwargs) -> None:
        pass

    def dwell(self, _seconds: float) -> None:
        pass

    def wait_for_idle(self, *, timeout_s: float) -> None:
        pass

    def jog_relative(self, **kwargs) -> float:
        self.jogs.append(kwargs)
        return 0.01


class TurnCliTests(unittest.TestCase):
    def test_turn_command_prints_json_for_saved_vision_result(self) -> None:
        input_path = _write_temp_json(
            {
                "provider": "ghostvision",
                "board_pieces": [
                    {"cell": [2, 1], "piece": "r_pao"},
                ],
            }
        )
        self.addCleanup(input_path.unlink, missing_ok=True)

        parser = build_parser()
        args = parser.parse_args(
            [
                "turn",
                "--vision-result",
                str(input_path),
                "--carriage",
                "2,1",
                "--engine",
                "/fake/pikafish",
                "--depth",
                "8",
                "--json",
            ]
        )

        stdout = io.StringIO()
        with patch("src.machine.grbl.GrblController", FakeGrblController):
            with patch("src.turn.get_best_move", return_value="h2e2"):
                with contextlib.redirect_stdout(stdout):
                    run(args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["best_move"], "h2e2")
        self.assertEqual(payload["kind"], "move")
        self.assertEqual(payload["start"], [2, 1])
        self.assertEqual(payload["end"], [2, 4])
        self.assertEqual(payload["visual_status"], "skipped")


class WebStopCliTests(unittest.TestCase):
    def test_web_stop_uses_configured_port_by_default(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["web-stop", "--dry-run"])

        with patch("src.cli.stop_web_app") as stop_mock:
            run(args)

        self.assertEqual(stop_mock.call_args.kwargs["port"], 8080)
        self.assertTrue(stop_mock.call_args.kwargs["dry_run"])

    def test_web_stop_accepts_explicit_port(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["web-stop", "--port", "8090", "--force", "--allow-any-listener"])

        with patch("src.cli.stop_web_app") as stop_mock:
            run(args)

        self.assertEqual(stop_mock.call_args.kwargs["port"], 8090)
        self.assertTrue(stop_mock.call_args.kwargs["force"])
        self.assertTrue(stop_mock.call_args.kwargs["allow_any_listener"])

    def test_web_process_matcher_accepts_cli_web_command(self) -> None:
        command = "/home/ghost/GhostChessboard/.web-venv/bin/python -m src.cli web --port 8080"

        self.assertTrue(_looks_like_web_process(command))
        self.assertFalse(_looks_like_web_process("/usr/bin/python -m src.cli status"))

    def test_web_process_matcher_accepts_installed_web_command(self) -> None:
        self.assertTrue(_looks_like_web_process("/home/ghost/.local/bin/ghostchessboard web --port 8080"))
        self.assertTrue(_looks_like_web_process('"C:\\Program Files\\GhostChessboard\\ghostchessboard.exe" web'))
        self.assertFalse(_looks_like_web_process("/home/ghost/.local/bin/ghostchessboard status"))


def _write_temp_json(payload: dict) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        return Path(handle.name)


if __name__ == "__main__":
    unittest.main()

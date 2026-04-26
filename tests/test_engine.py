"""Tests for the UCI engine wrapper."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from src.engine import EngineError, get_best_move

INITIAL_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


class FakePopen:
    """Minimal Popen stand-in that records stdin and serves stdout lines."""

    last_instance: "FakePopen | None" = None

    def __init__(self, command, *, stdout_lines=(), returncode=0, **_):
        self.command = command
        self._stdin_buffer = io.StringIO()
        self.stdin = _StdinProxy(self._stdin_buffer)
        self.stdout = iter(stdout_lines)
        self.stderr = iter(())
        self.returncode = returncode
        FakePopen.last_instance = self

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9

    @property
    def stdin_text(self) -> str:
        return self._stdin_buffer.getvalue()


class _StdinProxy:
    def __init__(self, buffer: io.StringIO) -> None:
        self._buffer = buffer
        self.closed = False

    def write(self, value: str) -> int:
        return self._buffer.write(value)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _ImmediateTimer:
    def __init__(self, _timeout, callback) -> None:
        self._callback = callback
        self.daemon = False

    def start(self) -> None:
        self._callback()

    def cancel(self) -> None:
        pass


def _popen_factory(stdout_lines, returncode=0):
    def _factory(command, **kwargs):
        return FakePopen(command, stdout_lines=stdout_lines, returncode=returncode, **kwargs)

    return _factory


class EngineTests(unittest.TestCase):
    def test_get_best_move_runs_expected_uci_script(self) -> None:
        stdout_lines = [
            "uciok\n",
            "readyok\n",
            "info depth 12 score cp 42 pv a3a4\n",
            "bestmove a3a4 ponder b9c7\n",
        ]

        with patch(
            "src.engine.subprocess.Popen",
            side_effect=_popen_factory(stdout_lines),
        ) as popen_mock:
            move = get_best_move(
                INITIAL_FEN,
                engine_path=Path("/opt/pikafish/pikafish"),
                depth=12,
                threads=2,
                hash_mb=64,
                timeout_s=7.5,
            )

        self.assertEqual(move, "a3a4")
        popen_args, popen_kwargs = popen_mock.call_args
        self.assertEqual(popen_args[0], [str(Path("/opt/pikafish/pikafish"))])
        self.assertEqual(popen_kwargs["cwd"], str(Path("/opt/pikafish")))

        assert FakePopen.last_instance is not None
        stdin_text = FakePopen.last_instance.stdin_text
        self.assertIn("setoption name Threads value 2", stdin_text)
        self.assertIn("setoption name Hash value 64", stdin_text)
        self.assertIn(f"position fen {INITIAL_FEN}", stdin_text)
        self.assertIn("go depth 12", stdin_text)
        self.assertIn("quit", stdin_text)
        self.assertLess(stdin_text.index("go depth 12"), stdin_text.index("quit"))

    def test_get_best_move_rejects_missing_bestmove_line(self) -> None:
        stdout_lines = ["uciok\n", "readyok\n"]
        with patch(
            "src.engine.subprocess.Popen",
            side_effect=_popen_factory(stdout_lines),
        ):
            with self.assertRaisesRegex(EngineError, "bestmove"):
                get_best_move(INITIAL_FEN, engine_path="/opt/pikafish/pikafish")

    def test_get_best_move_reports_engine_critical_error(self) -> None:
        stdout_lines = [
            "uciok\n",
            "readyok\n",
            "info string CRITICAL ERROR: Command `position fen bad` failed. Reason: Unsupported position.\n",
        ]
        with patch(
            "src.engine.subprocess.Popen",
            side_effect=_popen_factory(stdout_lines, returncode=1),
        ):
            with self.assertRaisesRegex(EngineError, "Unsupported position"):
                get_best_move(INITIAL_FEN, engine_path="/opt/pikafish/pikafish")

    def test_get_best_move_reports_timeout_without_relying_on_returncode_sign(self) -> None:
        with patch(
            "src.engine.subprocess.Popen",
            side_effect=_popen_factory([], returncode=1),
        ), patch("src.engine.threading.Timer", _ImmediateTimer):
            with self.assertRaisesRegex(EngineError, "timed out"):
                get_best_move(INITIAL_FEN, engine_path="/opt/pikafish/pikafish", timeout_s=0.1)


if __name__ == "__main__":
    unittest.main()

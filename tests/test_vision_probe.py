"""Tests for the GhostVision CLI visual probe."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.config import VisionProbeConfig
from src.vision.probe import GhostVisionCliProbe, VisionProbeError


SAMPLE_RESULT_JSON = json.dumps(
    {
        "provider": "chinese_chess_recognition",
        "board_pieces": [
            {"cell": [0, 0], "piece": "r_ju", "confidence": 0.9},
            {"cell": [9, 8], "piece": "b_ju", "confidence": 0.9},
        ],
        "capture_pieces": [
            {"slot": 2, "piece": "r_zu", "confidence": 0.8},
        ],
    }
)


class FakeRunner:
    """Mimic ``subprocess.run`` while recording calls and scripting outcomes."""

    def __init__(self, result_json: str | None = SAMPLE_RESULT_JSON) -> None:
        self.calls: list[list[str]] = []
        self.result_json = result_json
        self.fail_stage: str | None = None
        self.raise_file_not_found = False
        self.raise_timeout = False

    def __call__(self, cmd, *, capture_output, text, timeout, check):
        self.calls.append(list(cmd))
        if self.raise_file_not_found:
            raise FileNotFoundError(cmd[0])
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(cmd[0], timeout)

        stage = _detect_stage(cmd)
        if self.fail_stage == stage:
            return subprocess.CompletedProcess(cmd, returncode=2, stdout="", stderr=f"{stage} boom")

        if stage == "snapshot":
            _touch(_arg_after(cmd, "--raw-output"))
            _touch(_arg_after(cmd, "--output"))
        elif stage == "recognize":
            _write(_arg_after(cmd, "--output"), self.result_json)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")


class GhostVisionCliProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(_rm_tree, self.tmp_dir)

    def _config(self, **overrides) -> VisionProbeConfig:
        return replace(
            VisionProbeConfig(),
            artifacts_dir=self.tmp_dir,
            ghostvision_bin="/fake/ghostvision",
            **overrides,
        )

    def test_capture_returns_board_state_from_recognized_json(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        state = probe.capture()

        self.assertEqual(state.occupied_cells, {(0, 0), (9, 8)})
        self.assertEqual(state.filled_capture_slots, {2})
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0][1:3], ["calib", "snapshot"])
        self.assertEqual(runner.calls[1][1:3], ["recognize-image", "chinese-chess-recognition"])

    def test_capture_appends_flip_flags_when_enabled(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(flip_x=True, flip_y=True), run_process=runner)

        probe.capture()

        recognize_cmd = runner.calls[1]
        self.assertIn("--flip-x", recognize_cmd)
        self.assertIn("--flip-y", recognize_cmd)

    def test_capture_writes_artifacts_into_configured_dir(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        probe.capture()

        artifacts = list(Path(self.tmp_dir).iterdir())
        self.assertEqual(len(artifacts), 3)
        suffixes = sorted(path.name.split("_")[-1] for path in artifacts)
        self.assertEqual(suffixes, ["crop.jpg", "raw.jpg", "result.json"])

    def test_snapshot_failure_raises_vision_probe_error(self) -> None:
        runner = FakeRunner()
        runner.fail_stage = "snapshot"
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        with self.assertRaisesRegex(VisionProbeError, "snapshot stage failed"):
            probe.capture()

    def test_recognize_failure_raises_vision_probe_error(self) -> None:
        runner = FakeRunner()
        runner.fail_stage = "recognize"
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        with self.assertRaisesRegex(VisionProbeError, "recognize stage failed"):
            probe.capture()

    def test_missing_binary_raises_vision_probe_error(self) -> None:
        runner = FakeRunner()
        runner.raise_file_not_found = True
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        with self.assertRaisesRegex(VisionProbeError, "not found"):
            probe.capture()

    def test_timeout_raises_vision_probe_error(self) -> None:
        runner = FakeRunner()
        runner.raise_timeout = True
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        with self.assertRaisesRegex(VisionProbeError, "timed out"):
            probe.capture()

    def test_counter_prefixes_are_monotonic(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        probe.capture()
        probe.capture()

        result_files = sorted(Path(self.tmp_dir).glob("*_result.json"))
        self.assertEqual(len(result_files), 2)
        prefixes = [path.name.rsplit("_", 1)[0] for path in result_files]
        self.assertNotEqual(prefixes[0], prefixes[1])


def _detect_stage(cmd: list[str]) -> str:
    if "snapshot" in cmd:
        return "snapshot"
    if "recognize-image" in cmd:
        return "recognize"
    return "unknown"


def _arg_after(cmd: list[str], flag: str) -> str | None:
    try:
        return cmd[cmd.index(flag) + 1]
    except ValueError:
        return None


def _touch(path: str | None) -> None:
    if path is None:
        return
    Path(path).write_bytes(b"fake-jpeg")


def _write(path: str | None, payload: str | None) -> None:
    if path is None or payload is None:
        return
    Path(path).write_text(payload, encoding="utf-8")


def _rm_tree(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

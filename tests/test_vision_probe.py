"""Tests for the GhostVision CLI visual probe."""

from __future__ import annotations

import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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

        if stage == "capture-result":
            _touch(_arg_after(cmd, "--raw-output"))
            _touch(_arg_after(cmd, "--image-output"))
            _write(_arg_after(cmd, "--output"), self.result_json)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")


class GhostVisionCliProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = Path(__file__).resolve().parent / ".tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmp_dir = str(tmp_root / self._testMethodName)
        _rm_tree(self.tmp_dir)
        Path(self.tmp_dir).mkdir(parents=True, exist_ok=True)
        self.addCleanup(_rm_tree, self.tmp_dir)

    def _config(self, **overrides) -> VisionProbeConfig:
        values = {
            "artifacts_dir": self.tmp_dir,
            "ghostvision_bin": "/fake/ghostvision",
            **overrides,
        }
        return replace(
            VisionProbeConfig(),
            **values,
        )

    def test_capture_returns_board_state_from_recognized_json(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        state = probe.capture()

        self.assertEqual(state.occupied_cells, {(0, 0), (9, 8)})
        self.assertEqual(state.filled_capture_slots, {2})
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][1], "capture-result")

    def test_default_calibration_path_matches_current_ghostvision_file(self) -> None:
        self.assertEqual(
            VisionProbeConfig().calibration_path,
            "../GhostVision/calibrations/nuc_primary_1920x1080.json",
        )

    def test_capture_snapshot_returns_recognized_snapshot(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        snapshot = probe.capture_snapshot()

        self.assertEqual(snapshot.provider, "chinese_chess_recognition")
        self.assertEqual(snapshot.board_pieces[0].cell, (0, 0))

    def test_default_binary_resolves_next_to_current_python(self) -> None:
        bin_dir = Path(self.tmp_dir) / "bin"
        bin_dir.mkdir()
        python_path = bin_dir / "python"
        ghostvision_path = bin_dir / "ghostvision"
        python_path.write_text("", encoding="utf-8")
        ghostvision_path.write_text("", encoding="utf-8")

        runner = FakeRunner()
        probe = GhostVisionCliProbe(
            self._config(ghostvision_bin="ghostvision"),
            run_process=runner,
        )

        with patch("src.vision.probe.shutil.which", return_value=None):
            with patch("src.vision.probe.sys.executable", str(python_path)):
                probe.capture()

        self.assertEqual(runner.calls[0][0], str(ghostvision_path))

    def test_capture_writes_artifacts_into_configured_dir(self) -> None:
        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        probe.capture()

        run_dirs = _run_dirs(self.tmp_dir)
        self.assertEqual(len(run_dirs), 1)
        artifacts = list(run_dirs[0].iterdir())
        self.assertEqual(len(artifacts), 3)
        suffixes = sorted(path.name.split("_")[-1] for path in artifacts)
        self.assertEqual(suffixes, ["crop.jpg", "raw.jpg", "result.json"])

    def test_capture_result_failure_raises_vision_probe_error(self) -> None:
        runner = FakeRunner()
        runner.fail_stage = "capture-result"
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        with self.assertRaisesRegex(VisionProbeError, "capture-result stage failed"):
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

        run_dirs = _run_dirs(self.tmp_dir)
        self.assertEqual(len(run_dirs), 1)
        self.assertEqual(len(list(run_dirs[0].iterdir())), 6)
        result_files = sorted(run_dirs[0].glob("*_result.json"))
        self.assertEqual(len(result_files), 2)
        prefixes = [path.name.rsplit("_", 1)[0] for path in result_files]
        self.assertNotEqual(prefixes[0], prefixes[1])

    def test_capture_prunes_old_run_directories(self) -> None:
        for index in range(6):
            run_dir = Path(self.tmp_dir) / f"run_20260420_08480{index}_{index:09d}"
            run_dir.mkdir()
            (run_dir / "stale.txt").write_text("x", encoding="utf-8")

        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(keep_recent_runs=5), run_process=runner)

        probe.capture()

        run_dirs = _run_dirs(self.tmp_dir)
        self.assertEqual(len(run_dirs), 5)
        self.assertFalse((Path(self.tmp_dir) / "run_20260420_084800_000000000").exists())
        self.assertFalse((Path(self.tmp_dir) / "run_20260420_084801_000000001").exists())

    def test_capture_removes_legacy_flat_artifacts(self) -> None:
        _touch(str(Path(self.tmp_dir) / "verify_1776645994_009_raw.jpg"))
        _touch(str(Path(self.tmp_dir) / "verify_1776645994_009_crop.jpg"))
        _write(str(Path(self.tmp_dir) / "verify_1776645994_009_result.json"), SAMPLE_RESULT_JSON)

        runner = FakeRunner()
        probe = GhostVisionCliProbe(self._config(), run_process=runner)

        probe.capture()

        self.assertEqual(list(Path(self.tmp_dir).glob("verify_*")), [])
        self.assertEqual(len(_run_dirs(self.tmp_dir)), 1)


def _detect_stage(cmd: list[str]) -> str:
    if "capture-result" in cmd:
        return "capture-result"
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


def _run_dirs(path: str) -> list[Path]:
    return sorted(
        child
        for child in Path(path).iterdir()
        if child.is_dir() and child.name.startswith("run_")
    )


if __name__ == "__main__":
    unittest.main()

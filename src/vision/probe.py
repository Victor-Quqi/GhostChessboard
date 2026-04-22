"""Live GhostVision CLI probe for scenario visual verification.

Runs the two-step GhostVision flow (snapshot + recognize) as subprocesses
and returns the recognized ``BoardState``. Intentionally tolerant: the
scenario runner treats probe failures as unavailable (non-fatal).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.board_state import BoardState
from src.config import VisionProbeConfig
from src.vision.external import build_board_state_from_snapshot, load_external_vision_snapshot


class VisionProbeError(RuntimeError):
    """Raised when the GhostVision CLI pipeline cannot produce a result."""


RunProcess = Callable[..., subprocess.CompletedProcess]


@dataclass(slots=True)
class GhostVisionCliProbe:
    """Invoke GhostVision's snapshot + recognize CLI per probe.

    Each scenario run writes under one timestamped directory inside
    ``artifacts_dir``. Each capture in that run writes three files:
    ``<prefix>_raw.jpg``, ``<prefix>_crop.jpg``, ``<prefix>_result.json``.
    The prefix is a monotonic counter so multi-step scenarios do not overwrite
    prior debug frames. Older run directories are pruned to the configured
    retention limit.
    """

    config: VisionProbeConfig
    run_process: RunProcess = subprocess.run
    _counter: int = 0
    _run_dir: Path | None = None

    def capture(self) -> BoardState | None:
        run_dir = self._ensure_run_dir()

        self._counter += 1
        prefix = f"verify_{self._counter:03d}"
        raw_path = run_dir / f"{prefix}_raw.jpg"
        crop_path = run_dir / f"{prefix}_crop.jpg"
        result_path = run_dir / f"{prefix}_result.json"

        self._run_snapshot(raw_path, crop_path)
        self._run_recognize(crop_path, result_path)

        snapshot = load_external_vision_snapshot(result_path)
        return build_board_state_from_snapshot(snapshot)

    def _ensure_run_dir(self) -> Path:
        if self.config.keep_recent_runs < 1:
            raise ValueError("Vision probe keep_recent_runs must be >= 1.")

        if self._run_dir is not None:
            return self._run_dir

        artifacts_root = Path(self.config.artifacts_dir)
        artifacts_root.mkdir(parents=True, exist_ok=True)

        self._remove_legacy_flat_artifacts(artifacts_root)

        run_dir = artifacts_root / self._new_run_dir_name()
        run_dir.mkdir(parents=True, exist_ok=False)
        self._run_dir = run_dir

        self._prune_old_run_dirs(artifacts_root)
        return run_dir

    def _new_run_dir_name(self) -> str:
        now = time.time()
        seconds = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
        nanos = time.time_ns() % 1_000_000_000
        return f"run_{seconds}_{nanos:09d}"

    def _prune_old_run_dirs(self, artifacts_root: Path) -> None:
        run_dirs = sorted(
            path
            for path in artifacts_root.iterdir()
            if path.is_dir() and path.name.startswith("run_")
        )
        stale_dirs = run_dirs[:-self.config.keep_recent_runs]
        for path in stale_dirs:
            shutil.rmtree(path, ignore_errors=True)

    def _remove_legacy_flat_artifacts(self, artifacts_root: Path) -> None:
        for path in artifacts_root.iterdir():
            if path.is_file() and self._is_legacy_artifact_file(path):
                path.unlink(missing_ok=True)

    @staticmethod
    def _is_legacy_artifact_file(path: Path) -> bool:
        return any(
            path.match(pattern)
            for pattern in (
                "verify_*_raw.jpg",
                "verify_*_crop.jpg",
                "verify_*_result.json",
            )
        )

    def _run_snapshot(self, raw_path: Path, crop_path: Path) -> None:
        cmd = [
            self.config.ghostvision_bin,
            "calib",
            "snapshot",
            "--device",
            self.config.camera_device,
            "--calibration",
            self.config.calibration_path,
            "--raw-output",
            str(raw_path),
            "--output",
            str(crop_path),
            "--crop",
        ]
        self._run("snapshot", cmd, timeout=self.config.snapshot_timeout_s)

    def _run_recognize(self, image_path: Path, result_path: Path) -> None:
        cmd = [
            self.config.ghostvision_bin,
            "recognize-image",
            "chinese-chess-recognition",
            str(image_path),
            "--backend-root",
            self.config.backend_root,
            "--output",
            str(result_path),
        ]
        if self.config.flip_x:
            cmd.append("--flip-x")
        if self.config.flip_y:
            cmd.append("--flip-y")
        self._run("recognize", cmd, timeout=self.config.recognize_timeout_s)

    def _run(self, label: str, cmd: list[str], *, timeout: float) -> None:
        try:
            completed = self.run_process(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VisionProbeError(f"GhostVision CLI not found at {cmd[0]!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise VisionProbeError(f"{label} stage timed out after {timeout}s") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise VisionProbeError(f"{label} stage failed: {detail}")

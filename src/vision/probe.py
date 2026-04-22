"""Live GhostVision CLI probe for scenario visual verification.

Runs the two-step GhostVision flow (snapshot + recognize) as subprocesses
and returns the recognized ``BoardState``. Intentionally tolerant: the
scenario runner treats probe failures as unavailable (non-fatal).
"""

from __future__ import annotations

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

    Each capture writes three files under ``artifacts_dir``:
    ``<prefix>_raw.jpg``, ``<prefix>_crop.jpg``, ``<prefix>_result.json``.
    The prefix is a monotonic counter so multi-step scenarios do not overwrite
    prior debug frames.
    """

    config: VisionProbeConfig
    run_process: RunProcess = subprocess.run
    _counter: int = 0

    def capture(self) -> BoardState | None:
        artifacts = Path(self.config.artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)

        self._counter += 1
        prefix = f"verify_{int(time.time())}_{self._counter:03d}"
        raw_path = artifacts / f"{prefix}_raw.jpg"
        crop_path = artifacts / f"{prefix}_crop.jpg"
        result_path = artifacts / f"{prefix}_result.json"

        self._run_snapshot(raw_path, crop_path)
        self._run_recognize(crop_path, result_path)

        snapshot = load_external_vision_snapshot(result_path)
        return build_board_state_from_snapshot(snapshot)

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

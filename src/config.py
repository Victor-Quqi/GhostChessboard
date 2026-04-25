"""Runtime configuration for GhostChessboard control."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SerialConfig:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    startup_delay_s: float = 2.0
    read_timeout_s: float = 0.2


@dataclass(slots=True)
class MotionConfig:
    x_cell_pitch_mm: float = 370.0 / 9.0
    y_cell_pitch_mm: float = 337.0 / 8.0
    engage_pwm: int = 1000
    drag_pwm: int = 1000
    overshoot_pwm: int | None = 500
    overshoot_pwm_end: int | None = None
    overshoot_pwm_segments: int = 1
    move_feed_mm_min: float = 2400.0
    return_feed_mm_min: float = 12000.0
    engage_delay_s: float = 0.0
    settle_delay_s: float = 0.10


@dataclass(slots=True)
class CompensationConfig:
    release_overshoot_mm: float = 15.0


@dataclass(slots=True)
class PlanningConfig:
    magnet_exclusion_radius_mm: float = 30.0
    piece_radius_mm: float = 10.0
    piece_collision_margin_mm: float = 2.0
    soft_clearance_mm: float = 8.0
    waypoint_clearance_mm: float = 8.0
    candidate_angle_count: int = 24
    release_angle_count: int = 32
    release_approach_mm: float = 42.0
    x_bounds_margin_mm: float = 20.0
    y_left_margin_mm: float = 20.0
    y_right_workspace_mm: float = 120.0
    clearance_weight: float = 0.35
    turn_weight: float = 8.0


@dataclass(slots=True)
class GrblConfig:
    pwm_max: int = 1000
    laser_mode: int = 0
    startup_commands: list[str] = field(
        default_factory=lambda: [
            "$30=1000",
            "$32=0",
            "$120=250",
            "$121=250",
            "G21",
            "G91",
        ]
    )


@dataclass(slots=True)
class VisionResultConfig:
    provider: str = "external"
    default_result_path: str | None = None


@dataclass(slots=True)
class VisionProbeConfig:
    """Settings for a live GhostVision probe used during scenario runs."""

    ghostvision_bin: str = "/home/ghost/.venvs/ghostvision/bin/ghostvision"
    camera_device: str = "/dev/video0"
    calibration_path: str = "/home/ghost/GhostVision/calibrations/nuc_primary_1920x1080.json"
    backend_root: str = "/home/ghost/tmp_ccr/repo"
    artifacts_dir: str = "/home/ghost/GhostChessboard/runtime/verify"
    keep_recent_runs: int = 5
    snapshot_timeout_s: float = 20.0
    recognize_timeout_s: float = 45.0
    flip_x: bool = False
    flip_y: bool = False


@dataclass(slots=True)
class VisionConfig:
    result: VisionResultConfig = field(default_factory=VisionResultConfig)
    probe: VisionProbeConfig = field(default_factory=VisionProbeConfig)


@dataclass(slots=True)
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    grbl: GrblConfig = field(default_factory=GrblConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)
    compensation: CompensationConfig = field(default_factory=CompensationConfig)
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge_dataclass(instance: Any, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if not hasattr(instance, key):
            continue

        current = getattr(instance, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge_dataclass(current, value)
            continue

        setattr(instance, key, value)


def load_config(path: str | Path | None = None) -> AppConfig:
    config = AppConfig()
    if path is None:
        return config

    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a JSON object.")

    _merge_dataclass(config, raw)
    return config

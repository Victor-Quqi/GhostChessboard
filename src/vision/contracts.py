"""Contracts for externally produced vision results."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.coords import GridPoint

BOARD_CORNER_NAMES = ("top_left", "top_right", "bottom_right", "bottom_left")


@dataclass(slots=True)
class ExternalVisionPiece:
    """One recognized main-board piece already mapped to logical board coordinates."""

    cell: GridPoint
    piece: str
    confidence: float | None = None


@dataclass(slots=True)
class ExternalVisionCapturePiece:
    """One recognized capture-area piece already mapped to a capture slot."""

    slot: int
    piece: str
    confidence: float | None = None


@dataclass(slots=True)
class ExternalVisionPose:
    """Optional geometric output from an external vision provider."""

    corners_px: dict[str, tuple[float, float]] = field(default_factory=dict)
    main_board_points_px: dict[GridPoint, tuple[float, float]] = field(default_factory=dict)
    confidence: float | None = None


@dataclass(slots=True)
class ExternalVisionSnapshot:
    """Canonical payload accepted by the main repository."""

    provider: str
    board_pieces: list[ExternalVisionPiece]
    capture_pieces: list[ExternalVisionCapturePiece] = field(default_factory=list)
    pose: ExternalVisionPose | None = None
    frame_id: str | None = None
    produced_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

"""Load and validate external vision results."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from src.board_state import BoardState
from src.coords import GridPoint, validate_grid_point, validate_main_board_cell
from src.vision.contracts import (
    BOARD_CORNER_NAMES,
    ExternalVisionCapturePiece,
    ExternalVisionPiece,
    ExternalVisionPose,
    ExternalVisionSnapshot,
)


def load_external_vision_snapshot(path: str | Path) -> ExternalVisionSnapshot:
    """Load one external vision result JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Vision result root must be a JSON object.")
    return _parse_snapshot(raw)


def build_board_state_from_snapshot(
    snapshot: ExternalVisionSnapshot,
    *,
    carriage_cell: GridPoint | None = None,
) -> BoardState:
    """Project an external vision snapshot to the board controller state."""
    if carriage_cell is not None:
        validate_grid_point(carriage_cell)

    return BoardState(
        occupied_cells={piece.cell for piece in snapshot.board_pieces},
        filled_capture_slots={piece.slot for piece in snapshot.capture_pieces},
        carriage_cell=carriage_cell,
    )


def snapshot_to_dict(snapshot: ExternalVisionSnapshot) -> dict[str, Any]:
    """Serialize a validated snapshot with stable JSON-friendly shapes."""
    payload = asdict(snapshot)
    payload["board_pieces"] = [
        {
            "cell": [piece.cell[0], piece.cell[1]],
            "piece": piece.piece,
            "confidence": piece.confidence,
        }
        for piece in snapshot.board_pieces
    ]
    payload["capture_pieces"] = [
        {
            "slot": piece.slot,
            "piece": piece.piece,
            "confidence": piece.confidence,
        }
        for piece in snapshot.capture_pieces
    ]
    if snapshot.pose is not None:
        payload["pose"] = {
            "corners_px": {
                name: [point[0], point[1]]
                for name, point in snapshot.pose.corners_px.items()
            },
            "main_board_points_px": {
                f"{cell[0]},{cell[1]}": [point[0], point[1]]
                for cell, point in sorted(snapshot.pose.main_board_points_px.items())
            },
            "confidence": snapshot.pose.confidence,
        }
    return payload


def _parse_snapshot(raw: dict[str, Any]) -> ExternalVisionSnapshot:
    provider = raw.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("Vision result field 'provider' must be a non-empty string.")

    board_pieces_raw = raw.get("board_pieces")
    if not isinstance(board_pieces_raw, list):
        raise ValueError("Vision result field 'board_pieces' must be a list.")
    board_pieces = [_parse_board_piece(item) for item in board_pieces_raw]

    seen_cells: set[GridPoint] = set()
    for piece in board_pieces:
        if piece.cell in seen_cells:
            raise ValueError(f"Duplicate board cell in vision result: {piece.cell}")
        seen_cells.add(piece.cell)

    capture_pieces_raw = raw.get("capture_pieces", [])
    if not isinstance(capture_pieces_raw, list):
        raise ValueError("Vision result field 'capture_pieces' must be a list when present.")
    capture_pieces = [_parse_capture_piece(item) for item in capture_pieces_raw]

    seen_slots: set[int] = set()
    for piece in capture_pieces:
        if piece.slot in seen_slots:
            raise ValueError(f"Duplicate capture slot in vision result: {piece.slot}")
        seen_slots.add(piece.slot)

    pose_raw = raw.get("pose")
    pose = _parse_pose(pose_raw) if pose_raw is not None else None

    frame_id = _optional_string(raw, "frame_id")
    produced_at = _optional_string(raw, "produced_at")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Vision result field 'metadata' must be an object when present.")

    return ExternalVisionSnapshot(
        provider=provider.strip(),
        board_pieces=board_pieces,
        capture_pieces=capture_pieces,
        pose=pose,
        frame_id=frame_id,
        produced_at=produced_at,
        metadata=metadata,
    )


def _parse_board_piece(raw: Any) -> ExternalVisionPiece:
    if not isinstance(raw, dict):
        raise ValueError("Each board piece entry must be an object.")
    cell = _parse_cell(raw.get("cell"))
    validate_main_board_cell(cell)
    piece = _parse_piece_name(raw.get("piece"))
    confidence = _parse_confidence(raw.get("confidence"))
    return ExternalVisionPiece(cell=cell, piece=piece, confidence=confidence)


def _parse_capture_piece(raw: Any) -> ExternalVisionCapturePiece:
    if not isinstance(raw, dict):
        raise ValueError("Each capture piece entry must be an object.")
    slot = raw.get("slot")
    if not isinstance(slot, int) or not (0 <= slot <= 19):
        raise ValueError(f"Capture slot must be an integer in range 0-19, got {slot!r}")
    piece = _parse_piece_name(raw.get("piece"))
    confidence = _parse_confidence(raw.get("confidence"))
    return ExternalVisionCapturePiece(slot=slot, piece=piece, confidence=confidence)


def _parse_pose(raw: Any) -> ExternalVisionPose:
    if not isinstance(raw, dict):
        raise ValueError("Vision result field 'pose' must be an object.")

    corners_px: dict[str, tuple[float, float]] = {}
    corners_raw = raw.get("corners_px", {})
    if corners_raw:
        if not isinstance(corners_raw, dict):
            raise ValueError("Vision result field 'pose.corners_px' must be an object.")
        if set(corners_raw) != set(BOARD_CORNER_NAMES):
            raise ValueError(
                "Vision result field 'pose.corners_px' must contain "
                f"{', '.join(BOARD_CORNER_NAMES)}."
            )
        corners_px = {
            name: _parse_point(point, field_name=f"pose.corners_px.{name}")
            for name, point in corners_raw.items()
        }

    main_board_points_px: dict[GridPoint, tuple[float, float]] = {}
    points_raw = raw.get("main_board_points_px", {})
    if points_raw:
        if not isinstance(points_raw, dict):
            raise ValueError("Vision result field 'pose.main_board_points_px' must be an object.")
        for key, value in points_raw.items():
            cell = _parse_cell(key)
            validate_main_board_cell(cell)
            main_board_points_px[cell] = _parse_point(value, field_name=f"pose.main_board_points_px.{key}")

    confidence = _parse_confidence(raw.get("confidence"))
    return ExternalVisionPose(
        corners_px=corners_px,
        main_board_points_px=main_board_points_px,
        confidence=confidence,
    )


def _parse_cell(raw: Any) -> GridPoint:
    if isinstance(raw, str):
        x_text, separator, y_text = raw.partition(",")
        if separator == "":
            raise ValueError(f"Grid cell string must use 'x,y' format, got {raw!r}")
        try:
            return (int(x_text.strip()), int(y_text.strip()))
        except ValueError as exc:
            raise ValueError(f"Grid cell string must use integer 'x,y' format, got {raw!r}") from exc

    if isinstance(raw, list | tuple) and len(raw) == 2:
        x_value, y_value = raw
        if isinstance(x_value, int) and isinstance(y_value, int):
            return (x_value, y_value)
    raise ValueError(f"Grid cell must be [x, y] or 'x,y', got {raw!r}")


def _parse_point(raw: Any, *, field_name: str) -> tuple[float, float]:
    if isinstance(raw, list | tuple) and len(raw) == 2:
        x_value, y_value = raw
        if isinstance(x_value, int | float) and isinstance(y_value, int | float):
            return (float(x_value), float(y_value))
    raise ValueError(f"Vision result field '{field_name}' must be [x, y] numbers.")


def _parse_piece_name(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Piece label must be a non-empty string, got {raw!r}")
    return raw.strip()


def _parse_confidence(raw: Any) -> float | None:
    if raw is None:
        return None
    if not isinstance(raw, int | float):
        raise ValueError(f"Confidence must be numeric when present, got {raw!r}")
    value = float(raw)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"Confidence must be within [0, 1], got {value}")
    return value


def _optional_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Vision result field '{key}' must be a string when present.")
    return value

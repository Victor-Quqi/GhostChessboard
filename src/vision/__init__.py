"""External vision result contracts and adapters."""

from src.vision.contracts import (
    BOARD_CORNER_NAMES,
    ExternalVisionCapturePiece,
    ExternalVisionPiece,
    ExternalVisionPose,
    ExternalVisionSnapshot,
)
from src.vision.external import (
    build_board_state_from_snapshot,
    load_external_vision_snapshot,
    snapshot_to_dict,
)
from src.vision.fen import board_state_from_xiangqi_fen, normalize_xiangqi_side_to_move, snapshot_to_xiangqi_fen

__all__ = [
    "BOARD_CORNER_NAMES",
    "ExternalVisionCapturePiece",
    "ExternalVisionPiece",
    "ExternalVisionPose",
    "ExternalVisionSnapshot",
    "board_state_from_xiangqi_fen",
    "build_board_state_from_snapshot",
    "load_external_vision_snapshot",
    "normalize_xiangqi_side_to_move",
    "snapshot_to_dict",
    "snapshot_to_xiangqi_fen",
]

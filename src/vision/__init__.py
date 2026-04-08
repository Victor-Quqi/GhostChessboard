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

__all__ = [
    "BOARD_CORNER_NAMES",
    "ExternalVisionCapturePiece",
    "ExternalVisionPiece",
    "ExternalVisionPose",
    "ExternalVisionSnapshot",
    "build_board_state_from_snapshot",
    "load_external_vision_snapshot",
    "snapshot_to_dict",
]

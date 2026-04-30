"""Web-console state with Xiangqi piece identity."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Literal

from src.board import CaptureExecution
from src.board_state import BoardCell, BoardState
from src.coords import GridPoint, validate_grid_point, validate_main_board_cell
from src.vision.contracts import ExternalVisionSnapshot
from src.vision.external import snapshot_to_dict
from src.xiangqi_rules import (
    XiangqiRuleError,
    apply_move_to_pieces,
    normalize_side,
    opposite_side,
    pieces_to_xiangqi_fen,
    standard_starting_pieces,
    terminal_status,
    validate_legal_move,
)

SyncStatus = Literal["initialized", "no_change", "legal_move", "illegal_move", "ambiguous", "forced"]


@dataclass(slots=True)
class InferredPhysicalMove:
    status: SyncStatus
    message: str
    start: BoardCell | None = None
    end: BoardCell | None = None
    capture: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "message": self.message,
            "start": list(self.start) if self.start is not None else None,
            "end": list(self.end) if self.end is not None else None,
            "capture": self.capture,
        }


class WebGameState:
    """Mutable Web console state projected onto the hardware BoardState."""

    def __init__(self, *, carriage_cell: GridPoint | None = (0, 0)) -> None:
        if carriage_cell is not None:
            validate_grid_point(carriage_cell)
        self._lock = threading.RLock()
        self.pieces: dict[BoardCell, str] = standard_starting_pieces()
        self.captured: dict[int, str] = {}
        self.carriage_cell: GridPoint | None = carriage_cell
        self.side_to_move: str = "red"
        self.hardware_busy = False
        self.hardware_status: str | None = None
        self.ai_status: str = "idle"
        self.last_move: dict[str, object] | None = None
        self.last_vision: dict[str, object] | None = None
        self.sync_warning: str | None = None
        self.game_over = False
        self.winner: str | None = None
        self.reason: str | None = None
        self.message = "red to move."
        self.updated_at = time.time()
        self._refresh_terminal_status_locked()

    def to_dict(self, *, user: dict[str, object] | None = None, seats: list[dict[str, object]] | None = None) -> dict[str, object]:
        with self._lock:
            return {
                "board_pieces": [
                    {"cell": [cell[0], cell[1]], "piece": piece}
                    for cell, piece in sorted(self.pieces.items())
                ],
                "capture_pieces": [
                    {"slot": slot, "piece": piece}
                    for slot, piece in sorted(self.captured.items())
                ],
                "carriage_cell": list(self.carriage_cell) if self.carriage_cell is not None else None,
                "side_to_move": self.side_to_move,
                "hardware": {
                    "busy": self.hardware_busy,
                    "status": self.hardware_status,
                },
                "ai": {
                    "status": self.ai_status,
                },
                "last_move": self.last_move,
                "last_vision": self.last_vision,
                "sync_warning": self.sync_warning,
                "game_over": self.game_over,
                "winner": self.winner,
                "reason": self.reason,
                "message": self.message,
                "updated_at": self.updated_at,
                "user": user,
                "seats": seats or [],
            }

    def board_state(self) -> BoardState:
        with self._lock:
            return BoardState(
                occupied_cells=set(self.pieces),
                filled_capture_slots=set(self.captured),
                carriage_cell=self.carriage_cell,
            )

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            self.hardware_busy = busy
            self.updated_at = time.time()

    def set_hardware_status(self, status: str) -> None:
        with self._lock:
            self.hardware_status = status
            self.updated_at = time.time()

    def set_ai_status(self, status: str) -> None:
        with self._lock:
            self.ai_status = status
            self.updated_at = time.time()

    def set_carriage_cell(self, cell: GridPoint) -> None:
        validate_grid_point(cell)
        with self._lock:
            self.carriage_cell = cell
            self.updated_at = time.time()

    def export_state(self) -> dict[str, object]:
        with self._lock:
            return {
                "board_pieces": [
                    {"cell": [cell[0], cell[1]], "piece": piece}
                    for cell, piece in sorted(self.pieces.items())
                ],
                "capture_pieces": [
                    {"slot": slot, "piece": piece}
                    for slot, piece in sorted(self.captured.items())
                ],
                "carriage_cell": list(self.carriage_cell) if self.carriage_cell is not None else None,
                "side_to_move": self.side_to_move,
                "last_move": self.last_move,
                "last_vision": self.last_vision,
                "sync_warning": self.sync_warning,
                "game_over": self.game_over,
                "winner": self.winner,
                "reason": self.reason,
                "message": self.message,
                "updated_at": self.updated_at,
            }

    def restore_state(self, raw: dict[str, object]) -> None:
        pieces: dict[BoardCell, str] = {}
        for item in _list_items(raw.get("board_pieces")):
            cell = _parse_cell(item["cell"])
            pieces[cell] = str(item["piece"])

        captured: dict[int, str] = {}
        for item in _list_items(raw.get("capture_pieces")):
            slot = int(item["slot"])
            if not (0 <= slot <= 19):
                raise ValueError(f"Capture slot out of range: {slot}")
            captured[slot] = str(item["piece"])

        carriage_cell = None
        if raw.get("carriage_cell") is not None:
            carriage_raw = raw["carriage_cell"]
            if not isinstance(carriage_raw, (list, tuple)) or len(carriage_raw) != 2:
                raise ValueError("carriage_cell must contain two coordinates.")
            carriage_cell = (int(carriage_raw[0]), int(carriage_raw[1]))
            validate_grid_point(carriage_cell)

        side_to_move = normalize_side(str(raw.get("side_to_move", "red")))
        with self._lock:
            self.pieces = pieces or standard_starting_pieces()
            self.captured = captured
            self.carriage_cell = carriage_cell
            self.side_to_move = side_to_move
            self.last_move = _optional_dict(raw.get("last_move"))
            self.last_vision = _optional_dict(raw.get("last_vision"))
            self.sync_warning = raw.get("sync_warning") if isinstance(raw.get("sync_warning"), str) else None
            self._refresh_terminal_status_locked()
            self.updated_at = float(raw.get("updated_at", time.time()))

    def reset_game(self, *, carriage_cell: GridPoint = (0, 0)) -> None:
        validate_grid_point(carriage_cell)
        with self._lock:
            self.pieces = standard_starting_pieces()
            self.captured = {}
            self.carriage_cell = carriage_cell
            self.side_to_move = "red"
            self.ai_status = "idle"
            self.last_move = None
            self.last_vision = None
            self.sync_warning = None
            self._refresh_terminal_status_locked()
            self.updated_at = time.time()

    def validate_move(self, start: BoardCell, end: BoardCell, *, side_to_move: str | None = None) -> None:
        with self._lock:
            self._raise_if_game_over_locked()
            validate_legal_move(self.pieces, start, end, side_to_move=side_to_move or self.side_to_move)

    def move_kind(self, end: BoardCell) -> str:
        with self._lock:
            return "capture" if end in self.pieces else "move"

    def fen(self, *, side_to_move: str | None = None) -> str:
        with self._lock:
            return pieces_to_xiangqi_fen(self.pieces, side_to_move=side_to_move or self.side_to_move)

    def commit_hardware_move(
        self,
        start: BoardCell,
        end: BoardCell,
        final_state: BoardState,
        *,
        source: str,
        best_move: str | None = None,
        capture_slot: int | None = None,
    ) -> dict[str, object]:
        with self._lock:
            moving_piece = self.pieces[start]
            captured_piece = self.pieces.get(end)
            if captured_piece is not None:
                if capture_slot is None:
                    capture_slot = _next_capture_slot(self.captured)
                self.captured[capture_slot] = captured_piece
            self.pieces = apply_move_to_pieces(self.pieces, start, end)
            self.carriage_cell = final_state.carriage_cell
            previous_side = self.side_to_move
            self.side_to_move = opposite_side(self.side_to_move)
            self.sync_warning = None
            self.last_move = {
                "source": source,
                "piece": moving_piece,
                "start": [start[0], start[1]],
                "end": [end[0], end[1]],
                "capture": captured_piece is not None,
                "captured_piece": captured_piece,
                "capture_slot": capture_slot,
                "side": previous_side,
                "best_move": best_move,
                "created_at": time.time(),
            }
            self._refresh_terminal_status_locked()
            self.updated_at = time.time()
            return self.last_move

    def sync_from_snapshot(self, snapshot: ExternalVisionSnapshot, *, force: bool = False) -> InferredPhysicalMove:
        new_pieces = {piece.cell: piece.piece for piece in snapshot.board_pieces}
        with self._lock:
            if snapshot.capture_pieces:
                new_captured = {piece.slot: piece.piece for piece in snapshot.capture_pieces}
            else:
                new_captured = dict(self.captured)
            old_pieces = dict(self.pieces)
            if not old_pieces:
                result = InferredPhysicalMove("initialized", "Initialized from vision.")
            else:
                result = infer_physical_move(old_pieces, new_pieces, side_to_move=self.side_to_move)
                if force and result.status not in {"legal_move", "no_change"}:
                    result = InferredPhysicalMove("forced", "Forced state rebuild from vision.")

            self.pieces = new_pieces
            self.captured = new_captured
            self.last_vision = snapshot_to_dict(snapshot)

            if result.status == "legal_move":
                assert result.start is not None and result.end is not None
                moving_piece = old_pieces[result.start]
                captured_piece = old_pieces.get(result.end)
                previous_side = self.side_to_move
                self.side_to_move = opposite_side(self.side_to_move)
                self.last_move = {
                    "source": "vision",
                    "piece": moving_piece,
                    "start": [result.start[0], result.start[1]],
                    "end": [result.end[0], result.end[1]],
                    "capture": result.capture,
                    "captured_piece": captured_piece,
                    "capture_slot": None,
                    "side": previous_side,
                    "best_move": None,
                    "created_at": time.time(),
                }
                self.sync_warning = None
            elif result.status in {"illegal_move", "ambiguous"}:
                self.sync_warning = result.message
            elif result.status == "forced":
                self.sync_warning = result.message
            else:
                self.sync_warning = None

            self._refresh_terminal_status_locked()
            self.updated_at = time.time()
            return result

    def refresh_terminal_status(self) -> dict[str, object]:
        with self._lock:
            self._refresh_terminal_status_locked()
            self.updated_at = time.time()
            return self.terminal_state()

    def force_terminal_status(
        self,
        *,
        winner: str | None,
        reason: str,
        message: str,
    ) -> dict[str, object]:
        if winner is not None:
            winner = normalize_side(winner)
        with self._lock:
            self.game_over = True
            self.winner = winner
            self.reason = reason
            self.message = message
            self.sync_warning = None
            self.updated_at = time.time()
            return self.terminal_state()

    def terminal_state(self) -> dict[str, object]:
        with self._lock:
            return {
                "game_over": self.game_over,
                "winner": self.winner,
                "reason": self.reason,
                "message": self.message,
            }

    def _refresh_terminal_status_locked(self) -> None:
        status = terminal_status(self.pieces, self.side_to_move)
        self.game_over = status.game_over
        self.winner = status.winner
        self.reason = status.reason
        self.message = status.message

    def _raise_if_game_over_locked(self) -> None:
        if self.game_over:
            raise XiangqiRuleError(self.message)


def infer_physical_move(
    previous: dict[BoardCell, str],
    current: dict[BoardCell, str],
    *,
    side_to_move: str,
) -> InferredPhysicalMove:
    """Infer and validate a physical human move from two board snapshots."""

    removed = [cell for cell in previous if cell not in current]
    added = [cell for cell in current if cell not in previous]
    changed = [cell for cell in current if cell in previous and current[cell] != previous[cell]]

    if not removed and not added and not changed:
        return InferredPhysicalMove("no_change", "Vision matches current board state.")

    start: BoardCell | None = None
    end: BoardCell | None = None
    capture = False

    if len(removed) == 1 and len(added) == 1 and not changed:
        start = removed[0]
        end = added[0]
        capture = False
        if previous[start] != current[end]:
            return InferredPhysicalMove("ambiguous", "Changed piece identity does not match a single move.")
    elif len(removed) == 1 and not added and len(changed) == 1:
        start = removed[0]
        end = changed[0]
        capture = True
        if previous[start] != current[end]:
            return InferredPhysicalMove("ambiguous", "Capture replacement does not match the moved piece.")
    else:
        return InferredPhysicalMove("ambiguous", "Vision difference is not a unique single move.")

    try:
        validate_legal_move(previous, start, end, side_to_move=side_to_move)
    except XiangqiRuleError as exc:
        return InferredPhysicalMove("illegal_move", str(exc), start=start, end=end, capture=capture)

    return InferredPhysicalMove("legal_move", "Physical move accepted from vision.", start=start, end=end, capture=capture)


def capture_slot_from_execution(execution: object) -> int | None:
    """Return the capture slot when an execution record represents a capture."""

    if isinstance(execution, CaptureExecution):
        return execution.capture_slot
    return None


def _next_capture_slot(captured: dict[int, str]) -> int:
    for slot in range(20):
        if slot not in captured:
            return slot
    raise ValueError("No empty capture slot is available.")


def _parse_cell(raw: list[int] | tuple[int, int]) -> BoardCell:
    if len(raw) != 2:
        raise ValueError("Cell must contain exactly two coordinates.")
    cell = (int(raw[0]), int(raw[1]))
    validate_main_board_cell(cell)
    return cell


def _list_items(raw: object) -> list[dict[str, object]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("State field must be a list.")
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("State list items must be objects.")
        result.append(item)
    return result


def _optional_dict(raw: object) -> dict[str, object] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("State field must be an object.")
    return raw

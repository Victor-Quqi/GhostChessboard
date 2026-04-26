"""Single-turn closed loop from vision to engine to motion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.board import BoardController, CaptureExecution, ExecutedRoute
from src.board_state import BoardState
from src.coords import GridPoint, validate_main_board_cell
from src.engine import get_best_move
from src.vision import build_board_state_from_snapshot, snapshot_to_xiangqi_fen
from src.vision.contracts import ExternalVisionSnapshot

UCI_FILES = "abcdefghi"


class TurnError(ValueError):
    """Raised when a single-turn command cannot be resolved or verified."""


class BoardStateProbe(Protocol):
    """Probe interface used for post-move visual verification."""

    def capture(self) -> BoardState | None:
        ...


@dataclass(slots=True)
class TurnResult:
    """Result of one vision-driven engine turn."""

    fen: str
    best_move: str
    kind: str
    start: GridPoint
    end: GridPoint
    execution: ExecutedRoute | CaptureExecution
    visual_status: str
    visual_diff: dict[str, list] | None
    final_state: BoardState


def uci_to_cells(move_uci: str) -> tuple[GridPoint, GridPoint]:
    """Parse a UCI move string like ``h2e2`` into internal ``(x, y)`` cells."""

    move = move_uci.strip()
    if len(move) != 4:
        raise TurnError(f"Unexpected UCI move length: {move_uci!r}")

    try:
        start = (int(move[1]), 8 - UCI_FILES.index(move[0]))
        end = (int(move[3]), 8 - UCI_FILES.index(move[2]))
    except ValueError as exc:
        raise TurnError(f"Unparseable UCI move: {move_uci!r}") from exc

    try:
        validate_main_board_cell(start)
        validate_main_board_cell(end)
    except ValueError as exc:
        raise TurnError(f"UCI move maps outside the main board: {move_uci!r}") from exc

    return start, end


def execute_engine_turn(
    *,
    executor,
    snapshot: ExternalVisionSnapshot,
    carriage_cell: GridPoint,
    side_to_move: str = "red",
    engine_path: str | Path | None = None,
    depth: int = 15,
    threads: int | None = None,
    hash_mb: int | None = None,
    timeout_s: float = 15.0,
    capture_slot: int | None = None,
    probe: BoardStateProbe | None = None,
    verify_capture_slots: bool = True,
    include_release_offset: bool = True,
    known_capture_slots: set[int] | None = None,
) -> TurnResult:
    """Run one AI turn from an already captured visual snapshot."""

    initial_state = build_board_state_from_snapshot(snapshot, carriage_cell=carriage_cell)
    if known_capture_slots is not None:
        initial_state.filled_capture_slots.update(known_capture_slots)
    fen = snapshot_to_xiangqi_fen(snapshot, side_to_move=side_to_move)
    best_move = get_best_move(
        fen,
        engine_path=engine_path,
        depth=depth,
        threads=threads,
        hash_mb=hash_mb,
        timeout_s=timeout_s,
    )
    start, end = uci_to_cells(best_move)

    if start not in initial_state.occupied_cells:
        raise TurnError(f"Engine returned {best_move}, but no piece is observed at {start}.")

    kind = "capture" if end in initial_state.occupied_cells else "move"
    if kind == "move" and capture_slot is not None:
        raise TurnError(f"Engine returned non-capture move {best_move}, but --slot was provided.")

    board = BoardController(executor, initial_state)
    if kind == "capture":
        execution = board.capture_piece(
            start=start,
            target=end,
            capture_slot=capture_slot,
            include_release_offset=include_release_offset,
        )
    else:
        execution = board.move_piece(
            start=start,
            end=end,
            include_release_offset=include_release_offset,
        )

    visual_status, visual_diff = verify_board_state(
        probe,
        board.state,
        verify_capture_slots=verify_capture_slots,
    )
    return TurnResult(
        fen=fen,
        best_move=best_move,
        kind=kind,
        start=start,
        end=end,
        execution=execution,
        visual_status=visual_status,
        visual_diff=visual_diff,
        final_state=BoardState(
            occupied_cells=set(board.state.occupied_cells),
            filled_capture_slots=set(board.state.filled_capture_slots),
            carriage_cell=board.state.carriage_cell,
        ),
    )


def verify_board_state(
    probe: BoardStateProbe | None,
    expected: BoardState,
    *,
    verify_capture_slots: bool = True,
) -> tuple[str, dict[str, list] | None]:
    """Compare a live probe result with an expected board state."""

    if probe is None:
        return "skipped", None

    try:
        observed = probe.capture()
    except Exception as exc:
        return f"probe_error: {type(exc).__name__}: {exc}", None

    if observed is None:
        return "unavailable", None

    missing = sorted(expected.occupied_cells - observed.occupied_cells)
    extra = sorted(observed.occupied_cells - expected.occupied_cells)

    slots_missing: list[int] = []
    slots_extra: list[int] = []
    if verify_capture_slots:
        slots_missing = sorted(expected.filled_capture_slots - observed.filled_capture_slots)
        slots_extra = sorted(observed.filled_capture_slots - expected.filled_capture_slots)

    if not missing and not extra and not slots_missing and not slots_extra:
        return "ok", None

    return (
        "mismatch",
        {
            "missing_cells": [list(cell) for cell in missing],
            "extra_cells": [list(cell) for cell in extra],
            "missing_capture_slots": slots_missing,
            "extra_capture_slots": slots_extra,
        },
    )

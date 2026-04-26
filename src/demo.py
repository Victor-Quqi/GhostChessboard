"""Human-vs-engine demonstration loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from src.board_state import BoardState
from src.confirm import OperatorCommand, OperatorTrigger
from src.coords import GridPoint, validate_grid_point
from src.turn import TurnResult, execute_engine_turn
from src.vision.contracts import ExternalVisionSnapshot


class DemoError(ValueError):
    """Raised when a demo run is configured incorrectly."""


class DemoVisionProbe(Protocol):
    """Live vision probe used before and after a machine turn."""

    def capture_snapshot(self) -> ExternalVisionSnapshot:
        ...

    def capture(self) -> BoardState | None:
        ...


@dataclass(slots=True)
class DemoTurnRecord:
    """One attempted machine response in the demonstration loop."""

    index: int
    confirmation: OperatorCommand
    turn: TurnResult | None
    error: str | None = None


@dataclass(slots=True)
class DemoRunSummary:
    """Summary of a human-machine demo run."""

    requested_turns: int | None
    completed_turns: int
    halted_at_index: int | None
    halt_reason: str | None
    reset_count: int
    records: list[DemoTurnRecord]


def run_human_machine_demo(
    *,
    executor,
    probe: DemoVisionProbe,
    trigger: OperatorTrigger,
    carriage_cell: GridPoint = (0, 0),
    reset_carriage_cell: GridPoint = (0, 0),
    side_to_move: str = "black",
    max_turns: int | None = None,
    engine_path: str | Path | None = None,
    depth: int = 15,
    threads: int | None = None,
    hash_mb: int | None = None,
    timeout_s: float = 15.0,
    verify_vision: bool = True,
    verify_capture_slots: bool = True,
    include_compensation: bool = True,
    on_waiting: Callable[[int], None] | None = None,
    on_confirmed: Callable[[int, OperatorCommand], None] | None = None,
    on_reset: Callable[[int, OperatorCommand, GridPoint], None] | None = None,
    on_turn_done: Callable[[DemoTurnRecord], None] | None = None,
) -> DemoRunSummary:
    """Run repeated human-confirmed engine turns for presentation use."""

    if max_turns is not None and max_turns < 1:
        raise DemoError(f"max_turns must be positive, got {max_turns}")
    validate_grid_point(carriage_cell)
    validate_grid_point(reset_carriage_cell)

    current_carriage = carriage_cell
    known_capture_slots: set[int] = set()
    records: list[DemoTurnRecord] = []
    halted_at_index: int | None = None
    halt_reason: str | None = None
    reset_count = 0

    index = 0
    while max_turns is None or index < max_turns:
        if on_waiting is not None:
            on_waiting(index)
        command = trigger.wait()
        if command.kind == "reset":
            current_carriage = reset_carriage_cell
            reset_count += 1
            if on_reset is not None:
                on_reset(index, command, current_carriage)
            continue
        if command.kind != "confirm":
            raise DemoError(f"Unsupported operator command kind: {command.kind!r}")

        if on_confirmed is not None:
            on_confirmed(index, command)

        try:
            snapshot = probe.capture_snapshot()
            known_capture_slots.update(piece.slot for piece in snapshot.capture_pieces)
            turn = execute_engine_turn(
                executor=executor,
                snapshot=snapshot,
                carriage_cell=current_carriage,
                side_to_move=side_to_move,
                engine_path=engine_path,
                depth=depth,
                threads=threads,
                hash_mb=hash_mb,
                timeout_s=timeout_s,
                probe=probe if verify_vision else None,
                verify_capture_slots=verify_capture_slots,
                include_compensation=include_compensation,
                known_capture_slots=known_capture_slots,
            )
            known_capture_slots = set(turn.final_state.filled_capture_slots)
            current_carriage = turn.final_state.carriage_cell or turn.end
            record = DemoTurnRecord(index=index, confirmation=command, turn=turn)
        except Exception as exc:
            record = DemoTurnRecord(
                index=index,
                confirmation=command,
                turn=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            records.append(record)
            halted_at_index = index
            halt_reason = "turn_error"
            if on_turn_done is not None:
                on_turn_done(record)
            break

        records.append(record)
        if on_turn_done is not None:
            on_turn_done(record)

        if turn.visual_status not in {"skipped", "ok"}:
            halted_at_index = index
            halt_reason = turn.visual_status
            break

        index += 1

    return DemoRunSummary(
        requested_turns=max_turns,
        completed_turns=sum(1 for record in records if record.turn is not None),
        halted_at_index=halted_at_index,
        halt_reason=halt_reason,
        reset_count=reset_count,
        records=records,
    )

"""High-level board state and move orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from src.board_state import BoardCell, BoardState, BoardStateError
from src.coords import (
    GridPoint,
    capture_slot_to_cell,
    grid_to_xy,
    validate_grid_point,
    validate_main_board_cell,
)
from src.motion.contracts import Segment
from src.motion.executor import MotionExecutor
from src.motion.planner import PlannedMove, plan_grid_move, plan_move


@dataclass(slots=True)
class ExecutedRoute:
    """Executed piece route together with any empty-carriage reposition."""

    approach_from: GridPoint | None
    path: list[GridPoint]
    segments: list[Segment]


@dataclass(slots=True)
class CaptureExecution:
    """Both legs of a capture operation."""

    capture_slot: int
    victim_route: ExecutedRoute
    attacker_route: ExecutedRoute


class BoardController:
    """Execute logical moves while tracking occupancy and carriage position."""

    def __init__(self, executor: MotionExecutor, state: BoardState | None = None) -> None:
        self._executor = executor
        self._state = state or BoardState()

    @property
    def state(self) -> BoardState:
        """Expose mutable board state for callers that need to inspect it."""
        return self._state

    def set_carriage_cell(self, cell: GridPoint) -> None:
        """Trust the caller and record the carriage's current grid point."""
        validate_grid_point(cell)
        self._state.carriage_cell = cell

    def move_piece(
        self,
        start: BoardCell,
        end: BoardCell,
        *,
        include_compensation: bool = True,
    ) -> ExecutedRoute:
        """Move one piece across the main board."""
        validate_main_board_cell(start)
        validate_main_board_cell(end)
        if start == end:
            raise BoardStateError("Start and end must be different cells.")
        if start not in self._state.occupied_cells:
            raise BoardStateError(f"No piece is recorded at start cell {start}.")
        if end in self._state.occupied_cells:
            raise BoardStateError(f"End cell {end} is already occupied.")

        approach_from = self._move_carriage_to(start)
        plan = plan_move(
            occupied=self._state.occupied_cells - {start},
            start=start,
            end=end,
        )
        self._executor.drag_route(plan.segments, include_compensation=include_compensation)

        self._state.occupied_cells.remove(start)
        self._state.occupied_cells.add(end)
        self._state.carriage_cell = end
        return self._route_from_plan(plan, approach_from)

    def capture_piece(
        self,
        start: BoardCell,
        target: BoardCell,
        *,
        capture_slot: int | None = None,
        include_compensation: bool = True,
    ) -> CaptureExecution:
        """Remove the target piece, then move the attacker into the freed cell."""
        validate_main_board_cell(start)
        validate_main_board_cell(target)
        if start == target:
            raise BoardStateError("Attacker and target must be different cells.")
        if start not in self._state.occupied_cells:
            raise BoardStateError(f"No attacking piece is recorded at start cell {start}.")
        if target not in self._state.occupied_cells:
            raise BoardStateError(f"No target piece is recorded at cell {target}.")

        resolved_slot = capture_slot if capture_slot is not None else self._state.next_capture_slot()
        capture_cell = capture_slot_to_cell(resolved_slot)
        if resolved_slot in self._state.filled_capture_slots:
            raise BoardStateError(f"Capture slot {resolved_slot} is already occupied.")

        victim_approach = self._move_carriage_to(target)
        victim_plan = plan_grid_move(
            occupied=(self._state.occupied_cells - {target}) | self._state.occupied_capture_cells(),
            start=target,
            end=capture_cell,
            max_x=9,
            max_y=10,
        )
        self._executor.drag_route(victim_plan.segments, include_compensation=include_compensation)

        self._state.occupied_cells.remove(target)
        self._state.filled_capture_slots.add(resolved_slot)
        self._state.carriage_cell = capture_cell

        attacker_approach = self._move_carriage_to(start)
        attacker_plan = plan_move(
            occupied=self._state.occupied_cells - {start},
            start=start,
            end=target,
        )
        self._executor.drag_route(attacker_plan.segments, include_compensation=include_compensation)

        self._state.occupied_cells.remove(start)
        self._state.occupied_cells.add(target)
        self._state.carriage_cell = target

        return CaptureExecution(
            capture_slot=resolved_slot,
            victim_route=self._route_from_plan(victim_plan, victim_approach),
            attacker_route=self._route_from_plan(attacker_plan, attacker_approach),
        )

    def _move_carriage_to(self, target: GridPoint) -> GridPoint | None:
        """Reposition the empty carriage to a grid point if needed."""
        validate_grid_point(target)
        current = self._state.carriage_cell
        if current is None:
            self._state.carriage_cell = target
            return None
        if current == target:
            return current

        current_x_mm, current_y_mm = grid_to_xy(*current)
        target_x_mm, target_y_mm = grid_to_xy(*target)
        self._executor.jog(target_x_mm - current_x_mm, target_y_mm - current_y_mm)
        self._state.carriage_cell = target
        return current

    def _route_from_plan(self, plan: PlannedMove, approach_from: GridPoint | None) -> ExecutedRoute:
        """Convert an internal plan to a caller-friendly execution record."""
        return ExecutedRoute(
            approach_from=approach_from,
            path=list(plan.path),
            segments=list(plan.segments),
        )

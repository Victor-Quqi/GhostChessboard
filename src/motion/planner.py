"""Board-level move planning helpers."""

from __future__ import annotations

from dataclasses import dataclass

from src.motion.executor import Segment
from src.pathfinder import find_path

BoardCell = tuple[int, int]
GridCell = tuple[int, int]


class MovePlanningError(ValueError):
    """Raised when a board move cannot be planned."""


@dataclass(slots=True)
class PlannedMove:
    path: list[GridCell]
    segments: list[Segment]


def validate_cell(cell: GridCell, *, max_x: int = 9, max_y: int = 8) -> None:
    """Validate a cell on a bounded grid."""
    x_index, y_index = cell
    if not (0 <= x_index <= max_x and 0 <= y_index <= max_y):
        raise MovePlanningError(
            f"Cell out of range: x={x_index}, y={y_index}, bounds=(0-{max_x}, 0-{max_y})"
        )


def path_to_segments(path: list[GridCell]) -> list[Segment]:
    """Convert a board path to merged motion segments."""
    if len(path) < 2:
        return []

    segments: list[Segment] = []
    current_direction: str | None = None
    current_cells = 0

    for current, nxt in zip(path, path[1:]):
        step_x = nxt[0] - current[0]
        step_y = nxt[1] - current[1]

        if abs(step_x) + abs(step_y) != 1:
            raise MovePlanningError(f"Non-adjacent path step: {current} -> {nxt}")

        if step_x == 1:
            direction = "x+"
        elif step_x == -1:
            direction = "x-"
        elif step_y == 1:
            direction = "y+"
        else:
            direction = "y-"

        if direction == current_direction:
            current_cells += 1
            continue

        if current_direction is not None:
            segments.append(Segment(direction=current_direction, cells=current_cells))

        current_direction = direction
        current_cells = 1

    if current_direction is not None:
        segments.append(Segment(direction=current_direction, cells=current_cells))

    return segments


def plan_grid_move(
    occupied: set[GridCell],
    start: GridCell,
    end: GridCell,
    *,
    max_x: int = 9,
    max_y: int = 8,
) -> PlannedMove:
    """Plan a 4-neighbor move on a bounded grid."""
    validate_cell(start, max_x=max_x, max_y=max_y)
    validate_cell(end, max_x=max_x, max_y=max_y)

    if start == end:
        return PlannedMove(path=[start], segments=[])

    board = set(occupied)
    board.discard(start)
    board.discard(end)

    path = find_path(board=board, start=start, end=end, max_x=max_x, max_y=max_y)
    if not path:
        raise MovePlanningError(
            f"No BFS path found from x={start[0]}, y={start[1]} to x={end[0]}, y={end[1]}"
        )

    return PlannedMove(path=path, segments=path_to_segments(path))


def plan_move(occupied: set[BoardCell], start: BoardCell, end: BoardCell) -> PlannedMove:
    """Plan a 4-neighbor move on the 10x9 main board."""
    return plan_grid_move(occupied=occupied, start=start, end=end, max_x=9, max_y=8)

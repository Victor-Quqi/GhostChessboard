"""Board-level move planning helpers."""

from __future__ import annotations

from dataclasses import dataclass

from src.motion.executor import Segment
from src.pathfinder import find_path

BoardCell = tuple[int, int]


class MovePlanningError(ValueError):
    """Raised when a board move cannot be planned."""


@dataclass(slots=True)
class PlannedMove:
    path: list[BoardCell]
    segments: list[Segment]


def validate_cell(cell: BoardCell) -> None:
    """Validate a main-board cell."""
    x_index, y_index = cell
    if not (0 <= x_index <= 9 and 0 <= y_index <= 8):
        raise MovePlanningError(f"Cell out of range: x={x_index}, y={y_index}")


def path_to_segments(path: list[BoardCell]) -> list[Segment]:
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


def plan_move(occupied: set[BoardCell], start: BoardCell, end: BoardCell) -> PlannedMove:
    """Plan a 4-neighbor move on the main board."""
    validate_cell(start)
    validate_cell(end)

    if start == end:
        return PlannedMove(path=[start], segments=[])

    if start in occupied:
        raise MovePlanningError(f"Start cell is occupied: x={start[0]}, y={start[1]}")

    board = set(occupied)
    board.discard(start)
    board.discard(end)

    path = find_path(board=board, start=start, end=end)
    if not path:
        raise MovePlanningError(
            f"No BFS path found from x={start[0]}, y={start[1]} to x={end[0]}, y={end[1]}"
        )

    return PlannedMove(path=path, segments=path_to_segments(path))

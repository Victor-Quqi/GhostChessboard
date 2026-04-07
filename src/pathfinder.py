"""BFS pathfinding on a bounded grid using board coordinates (x, y)."""
from collections import deque
from typing import Set, Tuple, List

def find_path(
    board: Set[Tuple[int, int]],
    start: Tuple[int, int],
    end: Tuple[int, int],
    *,
    max_x: int = 9,
    max_y: int = 8,
) -> List[Tuple[int, int]]:
    """Return a 4-neighbor BFS path from start to end.

    Args:
        board: Occupied cells that cannot be traversed.
        start: Start cell as ``(x, y)``.
        end: Target cell as ``(x, y)``.
        max_x: Largest valid x index.
        max_y: Largest valid y index.

    Returns:
        A list of cells including both start and end.
        Returns an empty list when no path is found.
    """
    def is_valid_cell(cell: Tuple[int, int]) -> bool:
        x_index, y_index = cell
        return 0 <= x_index <= max_x and 0 <= y_index <= max_y

    if not is_valid_cell(start) or not is_valid_cell(end):
        return []
    if start == end:
        return [start]
    if end in board:
        return []
    
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    visited = set()
    queue = deque()
    queue.append((start, [start]))
    visited.add(start)
    
    while queue:
        current_cell, path = queue.popleft()

        for step_x, step_y in directions:
            next_x = current_cell[0] + step_x
            next_y = current_cell[1] + step_y
            next_cell = (next_x, next_y)

            if not is_valid_cell(next_cell):
                continue
            if next_cell in visited:
                continue
            if next_cell in board:
                continue

            if next_cell == end:
                return path + [next_cell]

            visited.add(next_cell)
            queue.append((next_cell, path + [next_cell]))

    return []

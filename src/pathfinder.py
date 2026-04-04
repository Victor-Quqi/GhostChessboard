"""BFS pathfinding on the 9x10 main board."""
from collections import deque
from typing import Set, Tuple, List

def find_path(
    board: Set[Tuple[int, int]],
    start: Tuple[int, int],
    end: Tuple[int, int],
) -> List[Tuple[int, int]]:
    """Return a 4-neighbor BFS path from start to end.

    Args:
        board: Occupied cells that cannot be traversed.
        start: Start cell as ``(col, row)``.
        end: Target cell as ``(col, row)``.

    Returns:
        A list of cells including both start and end.
        Returns an empty list when no path is found.
    """
    def is_valid_cell(cell: Tuple[int, int]) -> bool:
        col, row = cell
        return 0 <= col <= 8 and 0 <= row <= 9
    
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
        
        for dx, dy in directions:
            next_col = current_cell[0] + dx
            next_row = current_cell[1] + dy
            next_cell = (next_col, next_row)

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

"""BFS路径规划模块
在主棋盘空格点间进行4-邻接（上下左右）寻路，避开已占用棋位
"""
from collections import deque
from typing import Set, Tuple, List

def find_path(
    board: Set[Tuple[int, int]],   
    start: Tuple[int, int],       
    end: Tuple[int, int],          
) -> List[Tuple[int, int]]:
    """BFS寻找从起点到终点的路径
    
    Args:
        board: 已被占用的棋位集合（不可通行）
        start: 起点棋位 (col, row)
        end: 终点棋位 (col, row)
    
    Returns:
        路径棋位列表（含起点和终点），找不到路径返回空列表
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
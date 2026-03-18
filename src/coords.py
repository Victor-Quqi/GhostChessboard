"""棋位与物理坐标映射模块
主棋盘：9列(0-8) × 10行(0-9)，左下角为原点(0,0)，点间距44mm
吃子区：主棋盘右侧，2列宽（列9/10）× 10行，槽位编号0-19（0-9对应列9，10-19对应列10）
"""

def cell_to_xy(col: int, row: int) -> tuple[float, float]:
    """主棋盘棋位转物理坐标（mm）
    
    Args:
        col: 列号 0-8
        row: 行号 0-9
    
    Returns:
        (x, y): 物理坐标，左下角为原点
    """
    if not (0 <= col <= 8 and 0 <= row <= 9):
        raise ValueError(f"主棋盘棋位超出范围：col={col}(0-8), row={row}(0-9)")
    
    x = col * 41.0
    y = row * 41.0
    return (x, y)

def capture_slot_to_xy(slot_index: int) -> tuple[float, float]:
    """吃子区槽位转物理坐标（mm）
    
    Args:
        slot_index: 吃子区槽位编号 0-19
                    0-9 → 列9，行0-9
                    10-19 → 列10，行0-9
    
    Returns:
        (x, y): 物理坐标，左下角为原点
    """
    if not (0 <= slot_index <= 19):
        raise ValueError(f"吃子区槽位超出范围：slot_index={slot_index}(0-19)")
    
    col = 9 + (slot_index // 10)  
    row = slot_index % 10          
    
    x = col * 41.0
    y = row * 41.0
    return (x, y)
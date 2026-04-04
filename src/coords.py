"""Board-cell to physical-coordinate helpers.

Main board:
- 9 columns (0-8) x 10 rows (0-9)
- origin at the lower-left corner
- x axis is perpendicular to the river
- y axis is parallel to the river

Capture area:
- located on the right side of the main board
- 2 columns wide (columns 9 and 10) x 10 rows
- slot indices 0-19
"""

X_CELL_PITCH_MM = 41.2
Y_CELL_PITCH_MM = 42.0

def cell_to_xy(col: int, row: int) -> tuple[float, float]:
    """Convert a main-board cell to physical coordinates in mm."""
    if not (0 <= col <= 8 and 0 <= row <= 9):
        raise ValueError(f"Main-board cell out of range: col={col} (0-8), row={row} (0-9)")
    
    x = col * X_CELL_PITCH_MM
    y = row * Y_CELL_PITCH_MM
    return (x, y)

def capture_slot_to_xy(slot_index: int) -> tuple[float, float]:
    """Convert a capture-area slot index to physical coordinates in mm."""
    if not (0 <= slot_index <= 19):
        raise ValueError(f"Capture slot out of range: slot_index={slot_index} (0-19)")
    
    col = 9 + (slot_index // 10)
    row = slot_index % 10
    
    x = col * X_CELL_PITCH_MM
    y = row * Y_CELL_PITCH_MM
    return (x, y)

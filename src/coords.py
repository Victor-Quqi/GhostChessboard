"""Board-index to physical-coordinate helpers.

Main board:
- 10 points on the x axis (0-9), perpendicular to the river
- 9 points on the y axis (0-8), parallel to the river
- origin at the lower-left corner

Capture area:
- located on the right side of the main board
- 10 rows on x (0-9) and 2 extra columns on y (9 and 10)
- slot indices 0-19
"""

X_CELL_PITCH_MM = 41.2
Y_CELL_PITCH_MM = 42.0

def cell_to_xy(x_index: int, y_index: int) -> tuple[float, float]:
    """Convert a main-board point index (x, y) to physical coordinates in mm."""
    if not (0 <= x_index <= 9 and 0 <= y_index <= 8):
        raise ValueError(
            f"Main-board cell out of range: x={x_index} (0-9), y={y_index} (0-8)"
        )

    x_mm = x_index * X_CELL_PITCH_MM
    y_mm = y_index * Y_CELL_PITCH_MM
    return (x_mm, y_mm)

def capture_slot_to_xy(slot_index: int) -> tuple[float, float]:
    """Convert a capture-area slot index to physical coordinates in mm."""
    if not (0 <= slot_index <= 19):
        raise ValueError(f"Capture slot out of range: slot_index={slot_index} (0-19)")

    x_index = slot_index % 10
    y_index = 9 + (slot_index // 10)

    x_mm = x_index * X_CELL_PITCH_MM
    y_mm = y_index * Y_CELL_PITCH_MM
    return (x_mm, y_mm)

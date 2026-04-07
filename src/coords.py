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

X_CELL_PITCH_MM = 371.0 / 9.0
Y_CELL_PITCH_MM = 335.0 / 8.0
GridPoint = tuple[int, int]


def validate_main_board_cell(cell: GridPoint) -> None:
    """Validate a main-board point index."""
    x_index, y_index = cell
    if not (0 <= x_index <= 9 and 0 <= y_index <= 8):
        raise ValueError(
            f"Main-board cell out of range: x={x_index} (0-9), y={y_index} (0-8)"
        )


def validate_capture_cell(cell: GridPoint) -> None:
    """Validate a capture-area point index."""
    x_index, y_index = cell
    if not (0 <= x_index <= 9 and 9 <= y_index <= 10):
        raise ValueError(
            f"Capture cell out of range: x={x_index} (0-9), y={y_index} (9-10)"
        )


def validate_grid_point(cell: GridPoint) -> None:
    """Validate a point on the full 10x11 grid including capture area."""
    x_index, y_index = cell
    if not (0 <= x_index <= 9 and 0 <= y_index <= 10):
        raise ValueError(f"Grid point out of range: x={x_index} (0-9), y={y_index} (0-10)")


def grid_to_xy(x_index: int, y_index: int) -> tuple[float, float]:
    """Convert an extended-grid point index (x, y) to physical coordinates in mm."""
    validate_grid_point((x_index, y_index))

    x_mm = x_index * X_CELL_PITCH_MM
    y_mm = y_index * Y_CELL_PITCH_MM
    return (x_mm, y_mm)


def cell_to_xy(x_index: int, y_index: int) -> tuple[float, float]:
    """Convert a main-board point index (x, y) to physical coordinates in mm."""
    validate_main_board_cell((x_index, y_index))
    return grid_to_xy(x_index, y_index)


def capture_slot_to_cell(slot_index: int) -> GridPoint:
    """Convert a capture-area slot index to an extended-grid cell."""
    if not (0 <= slot_index <= 19):
        raise ValueError(f"Capture slot out of range: slot_index={slot_index} (0-19)")

    x_index = slot_index % 10
    y_index = 9 + (slot_index // 10)
    validate_capture_cell((x_index, y_index))
    return (x_index, y_index)


def capture_slot_to_xy(slot_index: int) -> tuple[float, float]:
    """Convert a capture-area slot index to physical coordinates in mm."""
    x_index, y_index = capture_slot_to_cell(slot_index)
    return grid_to_xy(x_index, y_index)

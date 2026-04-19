"""Pure logical board-state contracts with no hardware dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.coords import GridPoint, capture_slot_to_cell

BoardCell = tuple[int, int]


class BoardStateError(ValueError):
    """Raised when the requested board operation is invalid."""


@dataclass(slots=True)
class BoardState:
    """Minimal logical state for main-board and capture-area occupancy."""

    occupied_cells: set[BoardCell] = field(default_factory=set)
    filled_capture_slots: set[int] = field(default_factory=set)
    carriage_cell: GridPoint | None = None

    def occupied_capture_cells(self) -> set[GridPoint]:
        """Return the occupied capture-area cells on the extended grid."""
        return {capture_slot_to_cell(slot) for slot in self.filled_capture_slots}

    def next_capture_slot(self) -> int:
        """Return the first empty capture slot."""
        for slot_index in range(20):
            if slot_index not in self.filled_capture_slots:
                return slot_index
        raise BoardStateError("No empty capture slot is available.")

"""Pure motion data contracts shared by planning and execution."""

from __future__ import annotations

from dataclasses import dataclass

GridPoint = tuple[int, int]
PointMm = tuple[float, float]


@dataclass(slots=True)
class Segment:
    direction: str
    cells: int = 1


@dataclass(slots=True)
class DragPlan:
    start: GridPoint
    end: GridPoint
    waypoints_mm: list[PointMm]
    release_mm: PointMm
    release_offset_vector_mm: PointMm

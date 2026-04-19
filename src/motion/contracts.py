"""Pure motion data contracts shared by planning and execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Segment:
    direction: str
    cells: int = 1

"""Scenario runner for chained board moves under a single controller session.

A scenario declares an initial board state (fen + carriage) and an ordered
list of logical steps (move or capture). The runner executes them in order
through one ``BoardController`` and, when a ``VisionProbe`` is supplied,
verifies the expected occupancy against a live visual capture after each
step. Any step failure halts the run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from src.board import BoardController, CaptureExecution, ExecutedRoute
from src.board_state import BoardState
from src.coords import GridPoint, validate_grid_point, validate_main_board_cell
from src.vision import board_state_from_xiangqi_fen


class ScenarioError(ValueError):
    """Raised when a scenario definition cannot be parsed or executed."""


class VisionProbe(Protocol):
    """Hook that returns the currently observed board state.

    Implementations capture a frame and run recognition. Returning ``None``
    means "probe unavailable this step"; the scenario runner will treat the
    step as visually unverified but still successful.
    """

    def capture(self) -> BoardState | None:
        ...


@dataclass(slots=True, frozen=True)
class ScenarioStep:
    kind: str
    start: GridPoint
    end: GridPoint
    capture_slot: int | None = None


@dataclass(slots=True)
class Scenario:
    name: str
    initial_state: BoardState
    steps: list[ScenarioStep]


@dataclass(slots=True)
class StepResult:
    index: int
    kind: str
    start: GridPoint
    end: GridPoint
    execution: ExecutedRoute | CaptureExecution | None
    executed: bool
    error: str | None
    visual_status: str
    visual_diff: dict[str, list] | None


@dataclass(slots=True)
class ScenarioRunSummary:
    name: str
    total_steps: int
    executed_steps: int
    halted_at_index: int | None
    halt_reason: str | None
    results: list[StepResult] = field(default_factory=list)


def load_scenario(path: str | Path) -> Scenario:
    """Load a scenario JSON file from disk."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_scenario(raw)


def parse_scenario(raw: dict) -> Scenario:
    """Parse a scenario dict (JSON-loaded) into a ``Scenario`` value."""
    if not isinstance(raw, dict):
        raise ScenarioError("Scenario root must be a JSON object.")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioError("Scenario field 'name' must be a non-empty string.")

    initial_raw = raw.get("initial")
    if not isinstance(initial_raw, dict):
        raise ScenarioError("Scenario field 'initial' must be an object.")

    fen = initial_raw.get("fen")
    if not isinstance(fen, str) or not fen.strip():
        raise ScenarioError("Scenario field 'initial.fen' must be a non-empty string.")

    carriage_raw = initial_raw.get("carriage")
    carriage = _parse_cell(carriage_raw, "initial.carriage") if carriage_raw is not None else None
    if carriage is not None:
        validate_grid_point(carriage)

    filled_slots_raw = initial_raw.get("filled_capture_slots", [])
    if not isinstance(filled_slots_raw, list):
        raise ScenarioError("Scenario field 'initial.filled_capture_slots' must be a list when present.")
    filled_slots = set()
    for slot in filled_slots_raw:
        if not isinstance(slot, int) or not (0 <= slot <= 19):
            raise ScenarioError(f"Capture slot must be an int 0..19, got {slot!r}.")
        filled_slots.add(slot)

    initial_state = board_state_from_xiangqi_fen(fen, carriage_cell=carriage)
    initial_state.filled_capture_slots = filled_slots

    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ScenarioError("Scenario field 'steps' must be a non-empty list.")

    steps = [_parse_step(step_raw, index) for index, step_raw in enumerate(steps_raw)]

    return Scenario(name=name.strip(), initial_state=initial_state, steps=steps)


def run_scenario(
    scenario: Scenario,
    board: BoardController,
    *,
    probe: VisionProbe | None = None,
    verify_capture_slots: bool = True,
    on_step_start: Callable[[int, ScenarioStep], None] | None = None,
    on_step_done: Callable[[StepResult], None] | None = None,
) -> ScenarioRunSummary:
    """Execute each step in sequence inside one controller session.

    Halts at the first step whose execution raises, or whose post-step vision
    probe disagrees with the internally tracked state.
    """

    summary = ScenarioRunSummary(
        name=scenario.name,
        total_steps=len(scenario.steps),
        executed_steps=0,
        halted_at_index=None,
        halt_reason=None,
    )

    for index, step in enumerate(scenario.steps):
        if on_step_start is not None:
            on_step_start(index, step)

        execution, exec_error = _execute_step(board, step)
        if exec_error is not None:
            result = StepResult(
                index=index,
                kind=step.kind,
                start=step.start,
                end=step.end,
                execution=None,
                executed=False,
                error=exec_error,
                visual_status="skipped",
                visual_diff=None,
            )
            summary.results.append(result)
            summary.halted_at_index = index
            summary.halt_reason = f"execution_error: {exec_error}"
            if on_step_done is not None:
                on_step_done(result)
            break

        summary.executed_steps += 1
        visual_status, visual_diff = _verify_with_probe(
            probe,
            board.state,
            verify_capture_slots=verify_capture_slots,
        )

        result = StepResult(
            index=index,
            kind=step.kind,
            start=step.start,
            end=step.end,
            execution=execution,
            executed=True,
            error=None,
            visual_status=visual_status,
            visual_diff=visual_diff,
        )
        summary.results.append(result)
        if on_step_done is not None:
            on_step_done(result)

        if probe is not None and visual_status != "ok":
            summary.halted_at_index = index
            summary.halt_reason = _halt_reason_for_visual_status(visual_status)
            break

    return summary


def _execute_step(
    board: BoardController, step: ScenarioStep
) -> tuple[ExecutedRoute | CaptureExecution | None, str | None]:
    try:
        if step.kind == "move":
            return board.move_piece(start=step.start, end=step.end), None
        if step.kind == "capture":
            return (
                board.capture_piece(
                    start=step.start,
                    target=step.end,
                    capture_slot=step.capture_slot,
                ),
                None,
            )
        return None, f"unknown step kind: {step.kind!r}"
    except Exception as exc:  # surface planner / state errors as halt reasons
        return None, f"{type(exc).__name__}: {exc}"


def _verify_with_probe(
    probe: VisionProbe | None,
    expected: BoardState,
    *,
    verify_capture_slots: bool = True,
) -> tuple[str, dict[str, list] | None]:
    if probe is None:
        return "skipped", None
    try:
        observed = probe.capture()
    except Exception as exc:  # surface as non-fatal status instead of halting the run
        return f"probe_error: {type(exc).__name__}: {exc}", None
    if observed is None:
        return "unavailable", None

    expected_cells = expected.occupied_cells
    observed_cells = observed.occupied_cells
    missing = sorted(expected_cells - observed_cells)
    extra = sorted(observed_cells - expected_cells)

    slots_missing: list[int] = []
    slots_extra: list[int] = []
    if verify_capture_slots:
        expected_slots = expected.filled_capture_slots
        observed_slots = observed.filled_capture_slots
        slots_missing = sorted(expected_slots - observed_slots)
        slots_extra = sorted(observed_slots - expected_slots)

    if not missing and not extra and not slots_missing and not slots_extra:
        return "ok", None

    diff = {
        "missing_cells": [list(cell) for cell in missing],
        "extra_cells": [list(cell) for cell in extra],
        "missing_capture_slots": slots_missing,
        "extra_capture_slots": slots_extra,
    }
    return "mismatch", diff


def _halt_reason_for_visual_status(visual_status: str) -> str:
    if visual_status == "mismatch":
        return "visual_mismatch"
    if visual_status == "unavailable":
        return "visual_unavailable"
    if visual_status.startswith("probe_error:"):
        return visual_status.replace("probe_error:", "visual_probe_error:", 1)
    return f"visual_check_failed: {visual_status}"


def _parse_step(raw: object, index: int) -> ScenarioStep:
    if not isinstance(raw, dict):
        raise ScenarioError(f"Step {index} must be an object.")

    kind = raw.get("kind")
    if kind not in {"move", "capture"}:
        raise ScenarioError(f"Step {index} field 'kind' must be 'move' or 'capture', got {kind!r}.")

    start = _parse_cell(raw.get("start"), f"steps[{index}].start")
    end = _parse_cell(raw.get("end"), f"steps[{index}].end")
    validate_main_board_cell(start)
    validate_main_board_cell(end)

    slot_raw = raw.get("slot")
    if slot_raw is not None and (not isinstance(slot_raw, int) or not (0 <= slot_raw <= 19)):
        raise ScenarioError(f"Step {index} field 'slot' must be an int 0..19, got {slot_raw!r}.")

    if kind == "move" and slot_raw is not None:
        raise ScenarioError(f"Step {index} is a 'move' but declares 'slot'.")

    return ScenarioStep(kind=kind, start=start, end=end, capture_slot=slot_raw)


def _parse_cell(raw: object, field_name: str) -> GridPoint:
    if isinstance(raw, list | tuple) and len(raw) == 2:
        x_value, y_value = raw
        if isinstance(x_value, int) and isinstance(y_value, int):
            return (x_value, y_value)
    if isinstance(raw, str):
        x_text, separator, y_text = raw.partition(",")
        if separator:
            try:
                return (int(x_text.strip()), int(y_text.strip()))
            except ValueError:
                pass
    raise ScenarioError(f"Field {field_name} must be [x, y] or 'x,y', got {raw!r}.")

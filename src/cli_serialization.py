"""JSON serialization helpers for CLI payloads."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.board import CaptureExecution


def point_to_list(point) -> list | None:
    return list(point) if point is not None else None


def route_to_dict(route) -> dict:
    data = asdict(route)
    return {
        "approach_from": point_to_list(data["approach_from"]),
        "start": list(data["start"]),
        "end": list(data["end"]),
        "waypoints_mm": [list(point) for point in data["waypoints_mm"]],
        "release_mm": list(data["release_mm"]),
        "release_offset_vector_mm": list(data["release_offset_vector_mm"]),
    }


def execution_to_dict(execution) -> dict | None:
    if execution is None:
        return None
    if isinstance(execution, CaptureExecution):
        data = asdict(execution)
        return {
            "kind": "capture",
            "capture_slot": data["capture_slot"],
            "victim_route": route_to_dict(execution.victim_route),
            "attacker_route": route_to_dict(execution.attacker_route),
        }
    return {"kind": "move", "route": route_to_dict(execution)}


def board_state_to_dict(state) -> dict:
    data = asdict(state)
    return {
        "occupied_cells": [list(cell) for cell in sorted(data["occupied_cells"])],
        "filled_capture_slots": sorted(data["filled_capture_slots"]),
        "carriage_cell": point_to_list(data["carriage_cell"]),
    }


def scenario_summary_to_dict(summary) -> dict:
    data = asdict(summary)
    return {
        "name": data["name"],
        "total_steps": data["total_steps"],
        "executed_steps": data["executed_steps"],
        "halted_at_index": data["halted_at_index"],
        "halt_reason": data["halt_reason"],
        "results": [scenario_result_to_dict(result) for result in summary.results],
    }


def scenario_result_to_dict(result) -> dict[str, Any]:
    data = asdict(result)
    return {
        "index": data["index"],
        "kind": data["kind"],
        "start": list(data["start"]),
        "end": list(data["end"]),
        "executed": data["executed"],
        "error": data["error"],
        "visual_status": data["visual_status"],
        "visual_diff": data["visual_diff"],
        "execution": execution_to_dict(result.execution),
    }


def turn_result_to_dict(result) -> dict:
    data = asdict(result)
    return {
        "fen": data["fen"],
        "best_move": data["best_move"],
        "kind": data["kind"],
        "start": list(data["start"]),
        "end": list(data["end"]),
        "visual_status": data["visual_status"],
        "visual_diff": data["visual_diff"],
        "execution": execution_to_dict(result.execution),
        "final_state": board_state_to_dict(result.final_state),
    }


def demo_summary_to_dict(summary) -> dict:
    data = asdict(summary)
    return {
        "requested_turns": data["requested_turns"],
        "completed_turns": data["completed_turns"],
        "halted_at_index": data["halted_at_index"],
        "halt_reason": data["halt_reason"],
        "reset_count": data["reset_count"],
        "records": [demo_record_to_dict(record) for record in summary.records],
    }


def demo_record_to_dict(record) -> dict[str, Any]:
    data = asdict(record)
    confirmation = data["confirmation"]
    return {
        "index": data["index"],
        "confirmation": {
            "source": confirmation["source"],
            "detail": confirmation["detail"],
        },
        "error": data["error"],
        "turn": turn_result_to_dict(record.turn) if record.turn is not None else None,
    }

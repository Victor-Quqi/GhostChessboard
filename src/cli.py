"""Thin CLI for manual control and calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from src.board import BoardController, BoardState, BoardStateError, CaptureExecution, ExecutedRoute
from src.config import AppConfig, load_config
from src.machine.grbl import GrblController
from src.motion.executor import MotionExecutor, Segment
from src.motion.planner import BoardCell, MovePlanningError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ghostchessboard")
    parser.add_argument("--config", type=Path, help="Path to JSON config override.")
    parser.add_argument("--port", help="Override serial port from config.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    vision_parser = subparsers.add_parser("vision-result", help="Load one external vision result JSON.")
    vision_parser.add_argument("input", nargs="?", type=Path, help="Path to external vision result JSON.")
    vision_parser.add_argument("--carriage", metavar="X,Y", help="Optional empty-carriage grid point.")
    vision_parser.add_argument("--json", action="store_true", help="Print normalized result as JSON.")

    subparsers.add_parser("status", help="Read current GRBL status.")

    magnet_parser = subparsers.add_parser("magnet", help="Turn magnet on or off.")
    magnet_parser.add_argument("state", choices=["on", "off"])
    magnet_parser.add_argument("--pwm", type=int, help="PWM override for magnet on.")

    jog_parser = subparsers.add_parser("jog", help="Move the carriage in relative mode.")
    jog_parser.add_argument("--x", type=float, default=0.0)
    jog_parser.add_argument("--y", type=float, default=0.0)
    jog_parser.add_argument("--feed", type=float, help="Feed in mm/min.")

    step_parser = subparsers.add_parser("step", help="Move one or more chess cells with segmented compensation.")
    step_parser.add_argument("direction", choices=["x+", "x-", "y+", "y-"])
    step_parser.add_argument("--cells", type=int, default=1)
    step_parser.add_argument("--no-comp", action="store_true", help="Disable directional compensation.")

    route_parser = subparsers.add_parser("route", help="Run a segmented route cell by cell.")
    route_parser.add_argument("segments", nargs="+", help="Examples: x+ x-:2 y+")
    route_parser.add_argument("--no-comp", action="store_true", help="Disable directional compensation.")

    move_parser = subparsers.add_parser("move", help="Plan and execute a board move with BFS.")
    move_parser.add_argument("start", help="Start cell as x,y.")
    move_parser.add_argument("end", help="End cell as x,y.")
    move_parser.add_argument(
        "--occupied",
        action="append",
        default=[],
        metavar="X,Y",
        help="Additional occupied blocking cell on the 10x9 main board. Repeatable.",
    )
    move_parser.add_argument(
        "--carriage",
        metavar="X,Y",
        help="Current empty-carriage cell. Defaults to the start cell.",
    )
    move_parser.add_argument(
        "--print-path",
        action="store_true",
        help="Print the resolved BFS path and merged segments before execution.",
    )
    move_parser.add_argument("--move-feed", type=float, help="Override drag feed in mm/min for this run.")
    move_parser.add_argument("--return-feed", type=float, help="Override empty return feed in mm/min for this run.")
    move_parser.add_argument("--no-comp", action="store_true", help="Disable directional compensation.")

    capture_parser = subparsers.add_parser("capture", help="Move the victim to capture area, then move attacker in.")
    capture_parser.add_argument("start", help="Attacker cell as x,y.")
    capture_parser.add_argument("target", help="Target cell as x,y.")
    capture_parser.add_argument(
        "--occupied",
        action="append",
        default=[],
        metavar="X,Y",
        help="Additional occupied blocking cell on the 10x9 main board. Repeatable.",
    )
    capture_parser.add_argument(
        "--filled-slot",
        action="append",
        default=[],
        type=int,
        metavar="N",
        help="Capture slot already occupied. Repeatable.",
    )
    capture_parser.add_argument("--slot", type=int, help="Capture slot to use. Defaults to the first empty slot.")
    capture_parser.add_argument(
        "--carriage",
        metavar="X,Y",
        help="Current empty-carriage cell. Defaults to the target cell.",
    )
    capture_parser.add_argument(
        "--print-path",
        action="store_true",
        help="Print both resolved BFS paths and merged segments before execution.",
    )
    capture_parser.add_argument("--move-feed", type=float, help="Override drag feed in mm/min for this run.")
    capture_parser.add_argument("--return-feed", type=float, help="Override empty return feed in mm/min for this run.")
    capture_parser.add_argument("--no-comp", action="store_true", help="Disable directional compensation.")

    config_parser = subparsers.add_parser("show-config", help="Print resolved config.")
    config_parser.add_argument("--json", action="store_true", help="Print as JSON.")

    return parser


def load_runtime_config(args: argparse.Namespace) -> AppConfig:
    config = load_config(args.config)
    if args.port:
        config.serial.port = args.port
    if hasattr(args, "move_feed") and args.move_feed is not None:
        config.motion.move_feed_mm_min = args.move_feed
    if hasattr(args, "return_feed") and args.return_feed is not None:
        config.motion.return_feed_mm_min = args.return_feed
    return config


def parse_segments(raw_segments: Iterable[str]) -> list[Segment]:
    segments: list[Segment] = []
    for token in raw_segments:
        direction, separator, raw_count = token.partition(":")
        if direction not in {"x+", "x-", "y+", "y-"}:
            raise ValueError(f"Unsupported segment: {token}")
        cells = int(raw_count) if separator else 1
        segments.append(Segment(direction=direction, cells=cells))
    return segments


def parse_cell(raw_cell: str) -> BoardCell:
    try:
        x_text, y_text = raw_cell.split(",", 1)
        return (int(x_text.strip()), int(y_text.strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid cell format: {raw_cell}. Expected x,y") from exc


def print_route(label: str, execution: ExecutedRoute) -> None:
    """Print a single executed route in a compact debug format."""
    if execution.approach_from is None:
        print(f"{label} approach: (assumed aligned)")
    elif execution.approach_from == execution.path[0]:
        print(f"{label} approach: already at ({execution.path[0][0]},{execution.path[0][1]})")
    else:
        print(f"{label} approach: from ({execution.approach_from[0]},{execution.approach_from[1]})")
    print(f"{label} path:", " -> ".join(f"({x},{y})" for x, y in execution.path))
    print(
        f"{label} segments:",
        " ".join(f"{segment.direction}:{segment.cells}" for segment in execution.segments) or "(none)",
    )


def print_capture_execution(execution: CaptureExecution) -> None:
    """Print both legs of a capture operation."""
    print(f"Capture slot: {execution.capture_slot}")
    print_route("Victim", execution.victim_route)
    print_route("Attacker", execution.attacker_route)


def resolve_vision_result_path(config: AppConfig, override: Path | None) -> Path:
    if override is not None:
        return override
    if config.vision.result.default_result_path is not None:
        return Path(config.vision.result.default_result_path)
    raise ValueError("Provide an input JSON path or set config.vision.result.default_result_path.")


def run(args: argparse.Namespace) -> None:
    config = load_runtime_config(args)

    if args.command == "vision-result":
        from src.vision import (
            build_board_state_from_snapshot,
            load_external_vision_snapshot,
            snapshot_to_dict,
        )

        snapshot = load_external_vision_snapshot(resolve_vision_result_path(config, args.input))
        carriage = parse_cell(args.carriage) if args.carriage else None
        board_state = build_board_state_from_snapshot(snapshot, carriage_cell=carriage)
        payload = snapshot_to_dict(snapshot)
        payload["board_state"] = {
            "occupied_cells": [list(cell) for cell in sorted(board_state.occupied_cells)],
            "filled_capture_slots": sorted(board_state.filled_capture_slots),
            "carriage_cell": list(board_state.carriage_cell) if board_state.carriage_cell is not None else None,
        }

        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(payload, ensure_ascii=False))
        return

    if args.command == "show-config":
        payload = config.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(payload)
        return

    with GrblController(config) as controller:
        controller.initialize()
        executor = MotionExecutor(controller, config)

        if args.command == "status":
            print(controller.status().raw)
            return

        if args.command == "magnet":
            if args.state == "on":
                controller.magnet_on(args.pwm or config.motion.engage_pwm)
            else:
                controller.magnet_off()
            return

        if args.command == "jog":
            controller.jog_relative(
                dx_mm=args.x,
                dy_mm=args.y,
                feed_mm_min=args.feed or config.motion.move_feed_mm_min,
            )
            return

        if args.command == "step":
            executor.drag_step(
                args.direction,
                cells=args.cells,
                include_compensation=not args.no_comp,
            )
            return

        if args.command == "route":
            executor.drag_route(
                parse_segments(args.segments),
                include_compensation=not args.no_comp,
            )
            return

        if args.command == "move":
            start = parse_cell(args.start)
            end = parse_cell(args.end)
            occupied = {parse_cell(token) for token in args.occupied}
            carriage = parse_cell(args.carriage) if args.carriage else start
            board = BoardController(
                executor,
                BoardState(
                    occupied_cells=occupied | {start},
                    carriage_cell=carriage,
                ),
            )
            execution = board.move_piece(
                start=start,
                end=end,
                include_compensation=not args.no_comp,
            )

            if args.print_path:
                print_route("Move", execution)
            return

        if args.command == "capture":
            start = parse_cell(args.start)
            target = parse_cell(args.target)
            occupied = {parse_cell(token) for token in args.occupied}
            carriage = parse_cell(args.carriage) if args.carriage else target
            board = BoardController(
                executor,
                BoardState(
                    occupied_cells=occupied | {start, target},
                    filled_capture_slots=set(args.filled_slot),
                    carriage_cell=carriage,
                ),
            )
            execution = board.capture_piece(
                start=start,
                target=target,
                capture_slot=args.slot,
                include_compensation=not args.no_comp,
            )

            if args.print_path:
                print_capture_execution(execution)
            return

    raise ValueError(f"Unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except (BoardStateError, MovePlanningError) as exc:
        parser.exit(status=2, message=f"{exc}\n")


if __name__ == "__main__":
    main()

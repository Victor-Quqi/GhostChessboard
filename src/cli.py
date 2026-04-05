"""Thin CLI for manual control and calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from src.config import AppConfig, load_config
from src.machine.grbl import GrblController
from src.motion.executor import MotionExecutor, Segment
from src.motion.planner import BoardCell, MovePlanningError, plan_move


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ghostchessboard")
    parser.add_argument("--config", type=Path, help="Path to JSON config override.")
    parser.add_argument("--port", help="Override serial port from config.")

    subparsers = parser.add_subparsers(dest="command", required=True)

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
        help="Occupied blocking cell on the 10x9 main board. Repeatable.",
    )
    move_parser.add_argument(
        "--print-path",
        action="store_true",
        help="Print the resolved BFS path and merged segments before execution.",
    )
    move_parser.add_argument("--no-comp", action="store_true", help="Disable directional compensation.")

    config_parser = subparsers.add_parser("show-config", help="Print resolved config.")
    config_parser.add_argument("--json", action="store_true", help="Print as JSON.")

    return parser


def load_runtime_config(args: argparse.Namespace) -> AppConfig:
    config = load_config(args.config)
    if args.port:
        config.serial.port = args.port
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


def run(args: argparse.Namespace) -> None:
    config = load_runtime_config(args)

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
            plan = plan_move(occupied=occupied, start=start, end=end)

            if args.print_path:
                print("Path:", " -> ".join(f"({x},{y})" for x, y in plan.path))
                print("Segments:", " ".join(f"{segment.direction}:{segment.cells}" for segment in plan.segments) or "(none)")

            executor.drag_route(
                plan.segments,
                include_compensation=not args.no_comp,
            )
            return

    raise ValueError(f"Unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except MovePlanningError as exc:
        parser.exit(status=2, message=f"{exc}\n")


if __name__ == "__main__":
    main()

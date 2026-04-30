"""Argument parser construction for the GhostChessboard CLI."""

from __future__ import annotations

import argparse
from pathlib import Path


def _add_motion_feed_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--move-feed", type=float, help="Override drag feed in mm/min for this run.")
    parser.add_argument("--return-feed", type=float, help="Override both empty return feeds in mm/min for this run.")
    parser.add_argument("--return-feed-x", type=float, help="Override X-axis empty return feed in mm/min for this run.")
    parser.add_argument("--return-feed-y", type=float, help="Override Y-axis empty return feed in mm/min for this run.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ghostchessboard")
    parser.add_argument("--config", type=Path, help="Path to JSON config override.")
    parser.add_argument("--port", help="Override serial port from config.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    vision_parser = subparsers.add_parser("vision-result", help="Load one external vision result JSON.")
    vision_parser.add_argument("input", nargs="?", type=Path, help="Path to external vision result JSON.")
    vision_parser.add_argument("--carriage", metavar="X,Y", help="Optional empty-carriage grid point.")
    vision_parser.add_argument("--json", action="store_true", help="Print normalized result as JSON.")
    vision_parser.add_argument(
        "--fen-side",
        metavar="SIDE",
        help="Also serialize the result as Xiangqi FEN. Use 'red' or 'black' for clarity; 'w'/'b' remain supported.",
    )

    bestmove_parser = subparsers.add_parser("bestmove", help="Resolve a Xiangqi best move through a UCI engine.")
    bestmove_source_group = bestmove_parser.add_mutually_exclusive_group(required=True)
    bestmove_source_group.add_argument("--fen", help="Input Xiangqi FEN string.")
    bestmove_source_group.add_argument("--vision-result", type=Path, help="Input normalized vision result JSON path.")
    bestmove_parser.add_argument(
        "--fen-side",
        default="red",
        metavar="SIDE",
        help="Side to move when deriving FEN from a vision result. Use 'red' or 'black'; 'w'/'b' remain supported.",
    )
    bestmove_parser.add_argument("--engine", type=Path, help="Optional engine executable path.")
    bestmove_parser.add_argument("--depth", type=int, default=15, help="Search depth.")
    bestmove_parser.add_argument("--threads", type=int, help="Optional engine thread count.")
    bestmove_parser.add_argument("--hash-mb", type=int, help="Optional transposition-table size in MiB.")
    bestmove_parser.add_argument("--timeout-s", type=float, default=15.0, help="Search timeout in seconds.")
    bestmove_parser.add_argument("--json", action="store_true", help="Print the engine request/result as JSON.")

    turn_parser = subparsers.add_parser("turn", help="Run one vision-driven engine turn.")
    turn_parser.add_argument(
        "--vision-result",
        type=Path,
        help="Use a saved initial vision result JSON instead of capturing live GhostVision output.",
    )
    turn_parser.add_argument(
        "--carriage",
        required=True,
        metavar="X,Y",
        help="Current empty-carriage grid point before this turn.",
    )
    turn_parser.add_argument(
        "--fen-side",
        default="red",
        metavar="SIDE",
        help="Side to move for the generated FEN. Use 'red' or 'black'.",
    )
    turn_parser.add_argument("--engine", type=Path, help="Optional engine executable path.")
    turn_parser.add_argument("--depth", type=int, default=15, help="Search depth.")
    turn_parser.add_argument("--threads", type=int, help="Optional engine thread count.")
    turn_parser.add_argument("--hash-mb", type=int, help="Optional transposition-table size in MiB.")
    turn_parser.add_argument("--timeout-s", type=float, default=15.0, help="Search timeout in seconds.")
    turn_parser.add_argument("--slot", type=int, help="Capture slot to use when the engine move captures.")
    turn_parser.add_argument(
        "--verify-vision",
        action="store_true",
        help="After executing the turn, capture GhostVision output and compare with expected occupancy.",
    )
    turn_parser.add_argument(
        "--ignore-capture-vision",
        action="store_true",
        help="Ignore capture-area slot differences during post-turn vision verification.",
    )
    turn_parser.add_argument("--print-path", action="store_true", help="Print the resolved physical path.")
    _add_motion_feed_args(turn_parser)
    turn_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")
    turn_parser.add_argument("--json", action="store_true", help="Emit the turn summary as JSON.")

    demo_parser = subparsers.add_parser("demo", help="Run a human-vs-engine demo loop.")
    demo_parser.add_argument(
        "--carriage",
        default="0,0",
        metavar="X,Y",
        help="Initial empty-carriage grid point. Default: 0,0.",
    )
    demo_parser.add_argument(
        "--reset-carriage",
        default="0,0",
        metavar="X,Y",
        help="Software carriage position after a reset command. Default: 0,0.",
    )
    demo_parser.add_argument(
        "--turns",
        type=int,
        help="Maximum number of machine responses to run. Default: run until Ctrl+C or error.",
    )
    demo_parser.add_argument(
        "--fen-side",
        default="black",
        metavar="SIDE",
        help="Engine side to move after each human confirmation. Default: black.",
    )
    demo_parser.add_argument(
        "--trigger",
        choices=["grbl-y-clicks", "grbl-y-double-click", "enter"],
        default="grbl-y-clicks",
        help="Operator command source. GRBL clicks use double-click for confirm and triple-click for reset.",
    )
    demo_parser.add_argument("--engine", type=Path, help="Optional engine executable path.")
    demo_parser.add_argument("--depth", type=int, default=15, help="Search depth.")
    demo_parser.add_argument("--threads", type=int, help="Optional engine thread count.")
    demo_parser.add_argument("--hash-mb", type=int, help="Optional transposition-table size in MiB.")
    demo_parser.add_argument("--timeout-s", type=float, default=15.0, help="Search timeout in seconds.")
    demo_parser.add_argument(
        "--no-verify-vision",
        action="store_true",
        help="Do not verify the board with vision after the machine move.",
    )
    demo_parser.add_argument(
        "--ignore-capture-vision",
        action="store_true",
        help="Ignore capture-area slot differences during post-move vision verification.",
    )
    demo_parser.add_argument("--print-path", action="store_true", help="Print resolved physical paths.")
    _add_motion_feed_args(demo_parser)
    demo_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")
    demo_parser.add_argument("--button-axis", default="Y", help="GRBL limit pin used by the click trigger.")
    demo_parser.add_argument(
        "--button-pressed-when",
        choices=["absent", "present"],
        default="absent",
        help="For GRBL pin trigger, treat the button as pressed when the pin is absent or present in Pn.",
    )
    demo_parser.add_argument("--button-poll-ms", type=float, default=30.0, help="Button polling interval.")
    demo_parser.add_argument("--double-click-min-ms", type=float, default=120.0, help="Minimum double-click gap.")
    demo_parser.add_argument("--double-click-max-ms", type=float, default=1000.0, help="Maximum double-click gap.")
    demo_parser.add_argument("--button-debounce-ms", type=float, default=70.0, help="Button debounce window.")
    demo_parser.add_argument("--json", action="store_true", help="Emit the demo summary as JSON.")

    subparsers.add_parser("status", help="Read current GRBL status.")

    magnet_parser = subparsers.add_parser("magnet", help="Turn magnet on or off.")
    magnet_parser.add_argument("state", choices=["on", "off"])
    magnet_parser.add_argument("--pwm", type=int, help="PWM override for magnet on.")

    jog_parser = subparsers.add_parser("jog", help="Move the carriage in relative mode.")
    jog_parser.add_argument("--x", type=float, default=0.0)
    jog_parser.add_argument("--y", type=float, default=0.0)
    jog_parser.add_argument("--feed", type=float, help="Feed in mm/min.")

    step_parser = subparsers.add_parser("step", help="Move one or more chess cells with release offset motion.")
    step_parser.add_argument("direction", choices=["x+", "x-", "y+", "y-"])
    step_parser.add_argument("--cells", type=int, default=1)
    step_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")

    route_parser = subparsers.add_parser("route", help="Run a segmented route cell by cell.")
    route_parser.add_argument("segments", nargs="+", help="Examples: x+ x-:2 y+")
    route_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")

    move_parser = subparsers.add_parser("move", help="Plan and execute a physical board move.")
    move_parser.add_argument("start", help="Start cell as x,y.")
    move_parser.add_argument("end", help="End cell as x,y.")
    move_parser.add_argument(
        "--occupied",
        action="append",
        default=[],
        metavar="X,Y",
        help="Additional occupied blocking cell on the 10x9 main board. Repeatable.",
    )
    move_occupancy_source = move_parser.add_mutually_exclusive_group()
    move_occupancy_source.add_argument(
        "--from-fen",
        help="Derive initial occupancy from a Xiangqi FEN string. Start cell is added automatically.",
    )
    move_occupancy_source.add_argument(
        "--from-vision-result",
        type=Path,
        help="Derive initial occupancy and capture-area slots from an external vision result JSON.",
    )
    move_parser.add_argument(
        "--carriage",
        metavar="X,Y",
        help="Current empty-carriage cell. Defaults to the start cell.",
    )
    move_parser.add_argument(
        "--print-path",
        action="store_true",
        help="Print the resolved physical path before execution.",
    )
    _add_motion_feed_args(move_parser)
    move_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")

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
    capture_occupancy_source = capture_parser.add_mutually_exclusive_group()
    capture_occupancy_source.add_argument(
        "--from-fen",
        help="Derive initial occupancy from a Xiangqi FEN string. Attacker and target are added automatically.",
    )
    capture_occupancy_source.add_argument(
        "--from-vision-result",
        type=Path,
        help="Derive initial occupancy and capture-area slots from an external vision result JSON.",
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
        help="Print both resolved physical paths before execution.",
    )
    _add_motion_feed_args(capture_parser)
    capture_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")

    scenario_parser = subparsers.add_parser("scenario", help="Run a scenario JSON file inside one GRBL session.")
    scenario_parser.add_argument("path", type=Path, help="Path to the scenario JSON file.")
    _add_motion_feed_args(scenario_parser)
    scenario_parser.add_argument("--no-release-offset", action="store_true", help="Disable release offset motion.")
    scenario_parser.add_argument(
        "--verify-vision",
        action="store_true",
        help="After every step, capture a GhostVision snapshot and compare with expected occupancy.",
    )
    scenario_parser.add_argument(
        "--ignore-capture-vision",
        action="store_true",
        help="Ignore capture-area slot differences during scenario vision verification.",
    )
    scenario_parser.add_argument("--json", action="store_true", help="Emit the run summary as JSON.")

    config_parser = subparsers.add_parser("show-config", help="Print resolved config.")
    config_parser.add_argument("--json", action="store_true", help="Print as JSON.")

    web_parser = subparsers.add_parser("web", help="Run the GhostChessboard Web console.")
    web_parser.add_argument("--host", help="Listen host. Default comes from config.web.host.")
    web_parser.add_argument("--port", type=int, help="Listen port. Default comes from config.web.port.")

    web_stop_parser = subparsers.add_parser("web-stop", help="Stop a background GhostChessboard Web console.")
    web_stop_parser.add_argument("--port", type=int, help="Listening port. Default comes from config.web.port.")
    web_stop_parser.add_argument("--timeout-s", type=float, default=5.0, help="Seconds to wait after SIGTERM.")
    web_stop_parser.add_argument("--force", action="store_true", help="Send SIGKILL if the process ignores SIGTERM.")
    web_stop_parser.add_argument(
        "--allow-any-listener",
        action="store_true",
        help="Stop any process listening on the port, even if its command line does not look like this Web console.",
    )
    web_stop_parser.add_argument("--dry-run", action="store_true", help="Print matching processes without stopping them.")

    return parser

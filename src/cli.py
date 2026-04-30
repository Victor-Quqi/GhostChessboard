"""GhostChessboard command-line entry point."""

from __future__ import annotations

import argparse

from src.board_state import BoardStateError
from src import cli_parser
from src.cli_handlers import dispatch_command
from src.config import AppConfig, load_config
from src.demo import DemoError
from src.engine import EngineError
from src.motion.planner import MovePlanningError
from src.scenario import ScenarioError
from src.turn import TurnError
from src.vision.probe import VisionProbeError


def load_runtime_config(args: argparse.Namespace) -> AppConfig:
    config = load_config(args.config)
    if getattr(args, "command", None) not in {"web", "web-stop"} and args.port:
        config.serial.port = args.port
    if hasattr(args, "move_feed") and args.move_feed is not None:
        config.motion.move_feed_mm_min = args.move_feed
    if hasattr(args, "return_feed") and args.return_feed is not None:
        config.motion.return_feed_mm_min = args.return_feed
    if hasattr(args, "return_feed_x") and args.return_feed_x is not None:
        config.motion.return_feed_x_mm_min = args.return_feed_x
    if hasattr(args, "return_feed_y") and args.return_feed_y is not None:
        config.motion.return_feed_y_mm_min = args.return_feed_y
    return config


def run(args: argparse.Namespace) -> None:
    dispatch_command(args, load_runtime_config(args))


def main() -> None:
    parser = cli_parser.build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except _handled_cli_errors() as exc:
        parser.exit(status=2, message=f"{exc}\n")


def _handled_cli_errors() -> tuple[type[Exception], ...]:
    return (BoardStateError, DemoError, EngineError, MovePlanningError, ScenarioError, TurnError, VisionProbeError)


if __name__ == "__main__":
    main()

"""Thin CLI for manual control and calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from src import cli_parser, cli_serialization, web_process
from src.config import AppConfig, load_config

if TYPE_CHECKING:
    from src.board import BoardController, CaptureExecution, ExecutedRoute
    from src.board_state import BoardState, BoardStateError
    from src.engine import EngineError
    from src.machine.grbl import GrblController
    from src.motion.contracts import Segment
    from src.motion.executor import MotionExecutor
    from src.motion.planner import BoardCell, MovePlanningError


def load_runtime_config(args: argparse.Namespace) -> AppConfig:
    config = load_config(args.config)
    if getattr(args, "command", None) not in {"web", "web-stop"} and args.port:
        config.serial.port = args.port
    if hasattr(args, "move_feed") and args.move_feed is not None:
        config.motion.move_feed_mm_min = args.move_feed
    if hasattr(args, "return_feed") and args.return_feed is not None:
        config.motion.return_feed_mm_min = args.return_feed
    return config


def parse_segments(raw_segments: Iterable[str]) -> list["Segment"]:
    from src.motion.contracts import Segment

    segments: list[Segment] = []
    for token in raw_segments:
        direction, separator, raw_count = token.partition(":")
        if direction not in {"x+", "x-", "y+", "y-"}:
            raise ValueError(f"Unsupported segment: {token}")
        cells = int(raw_count) if separator else 1
        segments.append(Segment(direction=direction, cells=cells))
    return segments


def parse_cell(raw_cell: str) -> "BoardCell":
    try:
        x_text, y_text = raw_cell.split(",", 1)
        return (int(x_text.strip()), int(y_text.strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid cell format: {raw_cell}. Expected x,y") from exc


def print_route(label: str, execution: "ExecutedRoute") -> None:
    """Print a single executed route in a compact debug format."""
    if execution.approach_from is None:
        print(f"{label} approach: (assumed aligned)")
    elif execution.approach_from == execution.start:
        print(f"{label} approach: already at ({execution.start[0]},{execution.start[1]})")
    else:
        print(f"{label} approach: from ({execution.approach_from[0]},{execution.approach_from[1]})")
    print(
        f"{label} cells:",
        f"({execution.start[0]},{execution.start[1]}) -> ({execution.end[0]},{execution.end[1]})",
    )
    print(
        f"{label} waypoints:",
        " -> ".join(f"({x:.1f},{y:.1f})" for x, y in execution.waypoints_mm),
    )
    print(
        f"{label} release:",
        f"release=({execution.release_mm[0]:.1f},{execution.release_mm[1]:.1f}) "
        f"offset=({execution.release_offset_vector_mm[0]:.1f},{execution.release_offset_vector_mm[1]:.1f})",
    )


def print_capture_execution(execution: "CaptureExecution") -> None:
    """Print both legs of a capture operation."""
    print(f"Capture slot: {execution.capture_slot}")
    print_route("Victim", execution.victim_route)
    print_route("Attacker", execution.attacker_route)


def _print_turn_result(result, *, print_path: bool) -> None:
    from src.board import CaptureExecution

    print(f"FEN: {result.fen}")
    print(
        f"Best move: {result.best_move} {result.kind} "
        f"({result.start[0]},{result.start[1]}) -> ({result.end[0]},{result.end[1]})"
    )
    if print_path:
        if isinstance(result.execution, CaptureExecution):
            print_capture_execution(result.execution)
        else:
            print_route("Move", result.execution)
    diff_suffix = ""
    if result.visual_diff is not None:
        diff_suffix = f" diff={json.dumps(result.visual_diff, ensure_ascii=False)}"
    print(f"Visual: {result.visual_status}{diff_suffix}")


def _print_demo_record(record, *, print_path: bool) -> None:
    if record.error is not None:
        print(f"  ! turn failed: {record.error}")
        return
    assert record.turn is not None
    _print_turn_result(record.turn, print_path=print_path)
    state = record.turn.final_state
    if state.carriage_cell is not None:
        print(f"  carriage assumed at: ({state.carriage_cell[0]},{state.carriage_cell[1]})")
    if state.filled_capture_slots:
        print(f"  occupied capture slots: {','.join(str(slot) for slot in sorted(state.filled_capture_slots))}")


def resolve_vision_result_path(config: AppConfig, override: Path | None) -> Path:
    if override is not None:
        return override
    if config.vision.result.default_result_path is not None:
        return Path(config.vision.result.default_result_path)
    raise ValueError("Provide an input JSON path or set config.vision.result.default_result_path.")


def resolve_initial_board_state(args: argparse.Namespace) -> "BoardState":
    """Build the initial BoardState for move/capture commands from CLI args.

    Mutually exclusive sources: --from-fen, --from-vision-result, else the
    manual --occupied / --filled-slot switches. Mandatory cells (start, end,
    target) are added by the caller after this returns.
    """
    from src.board_state import BoardState
    from src.vision import (
        board_state_from_xiangqi_fen,
        build_board_state_from_snapshot,
        load_external_vision_snapshot,
    )

    from_fen = getattr(args, "from_fen", None)
    from_vision = getattr(args, "from_vision_result", None)

    if from_fen is not None:
        return board_state_from_xiangqi_fen(from_fen)
    if from_vision is not None:
        return build_board_state_from_snapshot(load_external_vision_snapshot(from_vision))

    occupied = {parse_cell(token) for token in getattr(args, "occupied", [])}
    filled_slots = set(getattr(args, "filled_slot", []))
    return BoardState(occupied_cells=occupied, filled_capture_slots=filled_slots)


def build_confirmation_trigger(args: argparse.Namespace, controller: "GrblController"):
    from src.confirm import EnterConfirmationTrigger, GrblPinClickTrigger

    if args.trigger == "enter":
        return EnterConfirmationTrigger(prompt="Human move done. Press Enter for machine response...")
    if args.trigger in {"grbl-y-clicks", "grbl-y-double-click"}:
        def _on_press(detail: str) -> None:
            if not args.json:
                print(f"  button press detected: {detail}", flush=True)

        return GrblPinClickTrigger(
            read_status=controller.realtime_status,
            axis=args.button_axis,
            pressed_when=args.button_pressed_when,
            poll_s=args.button_poll_ms / 1000.0,
            min_gap_s=args.double_click_min_ms / 1000.0,
            max_gap_s=args.double_click_max_ms / 1000.0,
            debounce_s=args.button_debounce_ms / 1000.0,
            on_press=_on_press,
        )
    raise ValueError(f"Unsupported confirmation trigger: {args.trigger}")


def run(args: argparse.Namespace) -> None:
    config = load_runtime_config(args)

    if args.command == "vision-result":
        from src.vision import (
            build_board_state_from_snapshot,
            load_external_vision_snapshot,
            snapshot_to_xiangqi_fen,
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
        if args.fen_side is not None:
            payload["fen"] = snapshot_to_xiangqi_fen(snapshot, side_to_move=args.fen_side)

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

    if args.command == "web":
        from src.web.server import run_web_app

        run_web_app(config, host=args.host, port=args.port)
        return

    if args.command == "web-stop":
        web_process.stop_web_app(
            port=args.port or config.web.port,
            timeout_s=args.timeout_s,
            force=args.force,
            allow_any_listener=args.allow_any_listener,
            dry_run=args.dry_run,
        )
        return

    if args.command == "bestmove":
        from src.engine import get_best_move
        from src.vision import load_external_vision_snapshot, snapshot_to_xiangqi_fen

        if args.fen is not None:
            fen = args.fen
        else:
            snapshot = load_external_vision_snapshot(args.vision_result)
            fen = snapshot_to_xiangqi_fen(snapshot, side_to_move=args.fen_side)

        best_move = get_best_move(
            fen,
            engine_path=args.engine,
            depth=args.depth,
            threads=args.threads,
            hash_mb=args.hash_mb,
            timeout_s=args.timeout_s,
        )
        if args.json:
            payload = {
                "fen": fen,
                "best_move": best_move,
                "depth": args.depth,
                "engine_path": str(args.engine) if args.engine is not None else None,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(best_move)
        return

    if args.command == "turn":
        from src.machine.grbl import GrblController
        from src.motion.executor import MotionExecutor
        from src.turn import execute_engine_turn
        from src.vision import load_external_vision_snapshot
        from src.vision.probe import GhostVisionCliProbe

        probe = GhostVisionCliProbe(config=config.vision.probe)
        if args.vision_result is not None:
            snapshot = load_external_vision_snapshot(args.vision_result)
        else:
            snapshot = probe.capture_snapshot()
        verify_probe = probe if args.verify_vision else None

        with GrblController(config) as controller:
            controller.initialize()
            executor = MotionExecutor(controller, config)
            result = execute_engine_turn(
                executor=executor,
                snapshot=snapshot,
                carriage_cell=parse_cell(args.carriage),
                side_to_move=args.fen_side,
                engine_path=args.engine,
                depth=args.depth,
                threads=args.threads,
                hash_mb=args.hash_mb,
                timeout_s=args.timeout_s,
                capture_slot=args.slot,
                probe=verify_probe,
                verify_capture_slots=not args.ignore_capture_vision,
                include_release_offset=not args.no_release_offset,
            )

        if args.json:
            print(json.dumps(cli_serialization.turn_result_to_dict(result), indent=2, ensure_ascii=False))
        else:
            _print_turn_result(result, print_path=args.print_path)
        if result.visual_status not in {"skipped", "ok"}:
            raise SystemExit(3)
        return

    from src.board import BoardController
    from src.board_state import BoardState
    from src.machine.grbl import GrblController
    from src.motion.executor import MotionExecutor

    with GrblController(config) as controller:
        controller.initialize()
        executor = MotionExecutor(controller, config)

        if args.command == "demo":
            from src.demo import run_human_machine_demo
            from src.vision.probe import GhostVisionCliProbe

            probe = GhostVisionCliProbe(config=config.vision.probe)
            trigger = build_confirmation_trigger(args, controller)
            initial_carriage = parse_cell(args.carriage)
            if not args.json:
                print(
                    "Demo assumes the empty carriage is currently at "
                    f"({initial_carriage[0]},{initial_carriage[1]})."
                )

            def _on_waiting(index: int) -> None:
                total = str(args.turns) if args.turns is not None else "∞"
                print(f"[{index + 1}/{total}] Waiting for human confirmation via {args.trigger}...")

            def _on_confirmed(index: int, event) -> None:
                detail = f" {event.detail}" if event.detail else ""
                total = str(args.turns) if args.turns is not None else "∞"
                print(f"[{index + 1}/{total}] confirmed: {event.source}{detail}")
                print("  capturing board and calculating machine move...")

            def _on_reset(index: int, event, cell) -> None:
                detail = f" {event.detail}" if event.detail else ""
                total = str(args.turns) if args.turns is not None else "∞"
                print(
                    f"[{index + 1}/{total}] reset: {event.source}{detail}; "
                    f"carriage assumed at ({cell[0]},{cell[1]})"
                )

            def _on_turn_done(record) -> None:
                _print_demo_record(record, print_path=args.print_path)

            summary = run_human_machine_demo(
                executor=executor,
                probe=probe,
                trigger=trigger,
                carriage_cell=initial_carriage,
                reset_carriage_cell=parse_cell(args.reset_carriage),
                side_to_move=args.fen_side,
                max_turns=args.turns,
                engine_path=args.engine,
                depth=args.depth,
                threads=args.threads,
                hash_mb=args.hash_mb,
                timeout_s=args.timeout_s,
                verify_vision=not args.no_verify_vision,
                verify_capture_slots=not args.ignore_capture_vision,
                include_release_offset=not args.no_release_offset,
                on_waiting=None if args.json else _on_waiting,
                on_confirmed=None if args.json else _on_confirmed,
                on_reset=None if args.json else _on_reset,
                on_turn_done=None if args.json else _on_turn_done,
            )

            if args.json:
                print(json.dumps(cli_serialization.demo_summary_to_dict(summary), indent=2, ensure_ascii=False))
            else:
                print(
                    f"Demo: completed {summary.completed_turns}/{summary.requested_turns} "
                    f"machine turns; resets={summary.reset_count}."
                )
                if summary.halted_at_index is not None:
                    print(f"Halted at turn {summary.halted_at_index + 1}: {summary.halt_reason}")
            if summary.halted_at_index is not None:
                raise SystemExit(3)
            return

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
                include_release_offset=not args.no_release_offset,
            )
            return

        if args.command == "route":
            executor.drag_route(
                parse_segments(args.segments),
                include_release_offset=not args.no_release_offset,
            )
            return

        if args.command == "move":
            start = parse_cell(args.start)
            end = parse_cell(args.end)
            initial_state = resolve_initial_board_state(args)
            initial_state.occupied_cells.add(start)
            initial_state.carriage_cell = parse_cell(args.carriage) if args.carriage else start
            board = BoardController(executor, initial_state)
            execution = board.move_piece(
                start=start,
                end=end,
                include_release_offset=not args.no_release_offset,
            )

            if args.print_path:
                print_route("Move", execution)
            return

        if args.command == "capture":
            start = parse_cell(args.start)
            target = parse_cell(args.target)
            initial_state = resolve_initial_board_state(args)
            initial_state.occupied_cells.update({start, target})
            initial_state.carriage_cell = parse_cell(args.carriage) if args.carriage else target
            board = BoardController(executor, initial_state)
            execution = board.capture_piece(
                start=start,
                target=target,
                capture_slot=args.slot,
                include_release_offset=not args.no_release_offset,
            )

            if args.print_path:
                print_capture_execution(execution)
            return

        if args.command == "scenario":
            from src.board import CaptureExecution
            from src.scenario import load_scenario, run_scenario

            scenario = load_scenario(args.path)
            board = BoardController(executor, scenario.initial_state)

            probe = None
            if args.verify_vision:
                from src.vision.probe import GhostVisionCliProbe

                probe = GhostVisionCliProbe(config=config.vision.probe)

            def _on_step_start(index: int, step) -> None:
                slot_hint = f" slot={step.capture_slot}" if step.capture_slot is not None else ""
                print(
                    f"[{index + 1}/{len(scenario.steps)}] {step.kind} "
                    f"({step.start[0]},{step.start[1]}) -> ({step.end[0]},{step.end[1]}){slot_hint}"
                )

            def _on_step_done(result) -> None:
                if not result.executed:
                    print(f"  ! execution failed: {result.error}")
                    return
                if isinstance(result.execution, CaptureExecution):
                    print_capture_execution(result.execution)
                else:
                    print_route("  move", result.execution)
                diff_suffix = ""
                if result.visual_diff is not None:
                    diff_suffix = f" diff={json.dumps(result.visual_diff, ensure_ascii=False)}"
                print(f"  visual: {result.visual_status}{diff_suffix}")

            summary = run_scenario(
                scenario,
                board,
                probe=probe,
                verify_capture_slots=not args.ignore_capture_vision,
                include_release_offset=not args.no_release_offset,
                on_step_start=None if args.json else _on_step_start,
                on_step_done=None if args.json else _on_step_done,
            )

            if args.json:
                print(json.dumps(cli_serialization.scenario_summary_to_dict(summary), indent=2, ensure_ascii=False))
            else:
                print(
                    f"Scenario {summary.name!r}: executed {summary.executed_steps}/"
                    f"{summary.total_steps} steps."
                )
                if summary.halted_at_index is not None:
                    print(f"Halted at step {summary.halted_at_index + 1}: {summary.halt_reason}")
            if summary.halted_at_index is not None:
                raise SystemExit(3)
            return

    raise ValueError(f"Unsupported command: {args.command}")


def main() -> None:
    parser = cli_parser.build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except _handled_cli_errors() as exc:
        parser.exit(status=2, message=f"{exc}\n")


def _handled_cli_errors() -> tuple[type[Exception], ...]:
    from src.board_state import BoardStateError
    from src.demo import DemoError
    from src.engine import EngineError
    from src.motion.planner import MovePlanningError
    from src.scenario import ScenarioError
    from src.turn import TurnError
    from src.vision.probe import VisionProbeError

    return (BoardStateError, DemoError, EngineError, MovePlanningError, ScenarioError, TurnError, VisionProbeError)


if __name__ == "__main__":
    main()

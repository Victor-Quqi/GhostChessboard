"""Command handlers for the GhostChessboard CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import json
from pathlib import Path

from src import cli_serialization, web_process
from src.board import BoardController, CaptureExecution, ExecutedRoute
from src.board_state import BoardState
from src.config import AppConfig
from src.confirm import EnterConfirmationTrigger, GrblPinClickTrigger
from src.demo import run_human_machine_demo
from src.engine import get_best_move
from src.machine.grbl import GrblController
from src.motion.contracts import Segment
from src.motion.executor import MotionExecutor
from src.scenario import load_scenario, run_scenario
from src.turn import execute_engine_turn
from src.vision import (
    board_state_from_xiangqi_fen,
    build_board_state_from_snapshot,
    load_external_vision_snapshot,
    snapshot_to_dict,
    snapshot_to_xiangqi_fen,
)
from src.vision.probe import GhostVisionCliProbe
from src.web.server import run_web_app

CommandHandler = Callable[[argparse.Namespace, AppConfig], None]


def dispatch_command(args: argparse.Namespace, config: AppConfig) -> None:
    try:
        handler = COMMAND_HANDLERS[args.command]
    except KeyError as exc:
        raise ValueError(f"Unsupported command: {args.command}") from exc
    handler(args, config)


def parse_segments(raw_segments: Iterable[str]) -> list[Segment]:
    segments: list[Segment] = []
    for token in raw_segments:
        direction, separator, raw_count = token.partition(":")
        if direction not in {"x+", "x-", "y+", "y-"}:
            raise ValueError(f"Unsupported segment: {token}")
        cells = int(raw_count) if separator else 1
        segments.append(Segment(direction=direction, cells=cells))
    return segments


def parse_cell(raw_cell: str):
    try:
        x_text, y_text = raw_cell.split(",", 1)
        return (int(x_text.strip()), int(y_text.strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid cell format: {raw_cell}. Expected x,y") from exc


def print_route(label: str, execution: ExecutedRoute) -> None:
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


def resolve_initial_board_state(args: argparse.Namespace) -> BoardState:
    """Build the initial BoardState for move/capture commands from CLI args."""
    from_fen = getattr(args, "from_fen", None)
    from_vision = getattr(args, "from_vision_result", None)

    if from_fen is not None:
        return board_state_from_xiangqi_fen(from_fen)
    if from_vision is not None:
        return build_board_state_from_snapshot(load_external_vision_snapshot(from_vision))

    occupied = {parse_cell(token) for token in getattr(args, "occupied", [])}
    filled_slots = set(getattr(args, "filled_slot", []))
    return BoardState(occupied_cells=occupied, filled_capture_slots=filled_slots)


def build_confirmation_trigger(args: argparse.Namespace, controller: GrblController):
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


def handle_vision_result(args: argparse.Namespace, config: AppConfig) -> None:
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
    _print_json(payload, pretty=args.json)


def handle_show_config(args: argparse.Namespace, config: AppConfig) -> None:
    payload = config.to_dict()
    if args.json:
        _print_json(payload, pretty=True)
    else:
        print(payload)


def handle_web(args: argparse.Namespace, config: AppConfig) -> None:
    run_web_app(config, host=args.host, port=args.port)


def handle_web_stop(args: argparse.Namespace, config: AppConfig) -> None:
    web_process.stop_web_app(
        port=args.port or config.web.port,
        timeout_s=args.timeout_s,
        force=args.force,
        allow_any_listener=args.allow_any_listener,
        dry_run=args.dry_run,
    )


def handle_bestmove(args: argparse.Namespace, config: AppConfig) -> None:
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
        _print_json(
            {
                "fen": fen,
                "best_move": best_move,
                "depth": args.depth,
                "engine_path": str(args.engine) if args.engine is not None else None,
            },
            pretty=True,
        )
    else:
        print(best_move)


def handle_turn(args: argparse.Namespace, config: AppConfig) -> None:
    probe = GhostVisionCliProbe(config=config.vision.probe)
    snapshot = load_external_vision_snapshot(args.vision_result) if args.vision_result is not None else probe.capture_snapshot()
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
        _print_json(cli_serialization.turn_result_to_dict(result), pretty=True)
    else:
        _print_turn_result(result, print_path=args.print_path)
    if result.visual_status not in {"skipped", "ok"}:
        raise SystemExit(3)


def handle_demo(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (controller, executor):
        probe = GhostVisionCliProbe(config=config.vision.probe)
        trigger = build_confirmation_trigger(args, controller)
        initial_carriage = parse_cell(args.carriage)
        if not args.json:
            print(
                "Demo assumes the empty carriage is currently at "
                f"({initial_carriage[0]},{initial_carriage[1]})."
            )

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
            on_waiting=None if args.json else _demo_waiting_printer(args),
            on_confirmed=None if args.json else _demo_confirmed_printer(args),
            on_reset=None if args.json else _demo_reset_printer(args),
            on_turn_done=None if args.json else lambda record: _print_demo_record(record, print_path=args.print_path),
        )

    if args.json:
        _print_json(cli_serialization.demo_summary_to_dict(summary), pretty=True)
    else:
        print(f"Demo: completed {summary.completed_turns}/{summary.requested_turns} machine turns; resets={summary.reset_count}.")
        if summary.halted_at_index is not None:
            print(f"Halted at turn {summary.halted_at_index + 1}: {summary.halt_reason}")
    if summary.halted_at_index is not None:
        raise SystemExit(3)


def handle_status(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (controller, _executor):
        print(controller.status().raw)


def handle_magnet(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (controller, _executor):
        if args.state == "on":
            controller.magnet_on(args.pwm or config.motion.engage_pwm)
        else:
            controller.magnet_off()


def handle_jog(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (controller, _executor):
        controller.jog_relative(
            dx_mm=args.x,
            dy_mm=args.y,
            feed_mm_min=args.feed or config.motion.move_feed_mm_min,
        )


def handle_step(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (_controller, executor):
        executor.drag_step(
            args.direction,
            cells=args.cells,
            include_release_offset=not args.no_release_offset,
        )


def handle_route(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (_controller, executor):
        executor.drag_route(
            parse_segments(args.segments),
            include_release_offset=not args.no_release_offset,
        )


def handle_move(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (_controller, executor):
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


def handle_capture(args: argparse.Namespace, config: AppConfig) -> None:
    with _hardware_session(config) as (_controller, executor):
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


def handle_scenario(args: argparse.Namespace, config: AppConfig) -> None:
    scenario = load_scenario(args.path)
    probe = GhostVisionCliProbe(config=config.vision.probe) if args.verify_vision else None

    with _hardware_session(config) as (_controller, executor):
        board = BoardController(executor, scenario.initial_state)
        summary = run_scenario(
            scenario,
            board,
            probe=probe,
            verify_capture_slots=not args.ignore_capture_vision,
            include_release_offset=not args.no_release_offset,
            on_step_start=None if args.json else _scenario_step_start_printer(scenario),
            on_step_done=None if args.json else _scenario_step_done_printer(),
        )

    if args.json:
        _print_json(cli_serialization.scenario_summary_to_dict(summary), pretty=True)
    else:
        print(f"Scenario {summary.name!r}: executed {summary.executed_steps}/{summary.total_steps} steps.")
        if summary.halted_at_index is not None:
            print(f"Halted at step {summary.halted_at_index + 1}: {summary.halt_reason}")
    if summary.halted_at_index is not None:
        raise SystemExit(3)


class _hardware_session:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._controller: GrblController | None = None

    def __enter__(self) -> tuple[GrblController, MotionExecutor]:
        self._controller = GrblController(self._config)
        controller = self._controller.__enter__()
        controller.initialize()
        return controller, MotionExecutor(controller, self._config)

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self._controller is not None
        self._controller.__exit__(exc_type, exc, traceback)


def _print_json(payload: object, *, pretty: bool) -> None:
    indent = 2 if pretty else None
    print(json.dumps(payload, indent=indent, ensure_ascii=False))


def _print_turn_result(result, *, print_path: bool) -> None:
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


def _demo_waiting_printer(args: argparse.Namespace):
    def _on_waiting(index: int) -> None:
        total = str(args.turns) if args.turns is not None else "∞"
        print(f"[{index + 1}/{total}] Waiting for human confirmation via {args.trigger}...")

    return _on_waiting


def _demo_confirmed_printer(args: argparse.Namespace):
    def _on_confirmed(index: int, event) -> None:
        detail = f" {event.detail}" if event.detail else ""
        total = str(args.turns) if args.turns is not None else "∞"
        print(f"[{index + 1}/{total}] confirmed: {event.source}{detail}")
        print("  capturing board and calculating machine move...")

    return _on_confirmed


def _demo_reset_printer(args: argparse.Namespace):
    def _on_reset(index: int, event, cell) -> None:
        detail = f" {event.detail}" if event.detail else ""
        total = str(args.turns) if args.turns is not None else "∞"
        print(f"[{index + 1}/{total}] reset: {event.source}{detail}; carriage assumed at ({cell[0]},{cell[1]})")

    return _on_reset


def _scenario_step_start_printer(scenario):
    def _on_step_start(index: int, step) -> None:
        slot_hint = f" slot={step.capture_slot}" if step.capture_slot is not None else ""
        print(
            f"[{index + 1}/{len(scenario.steps)}] {step.kind} "
            f"({step.start[0]},{step.start[1]}) -> ({step.end[0]},{step.end[1]}){slot_hint}"
        )

    return _on_step_start


def _scenario_step_done_printer():
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

    return _on_step_done


COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "vision-result": handle_vision_result,
    "show-config": handle_show_config,
    "web": handle_web,
    "web-stop": handle_web_stop,
    "bestmove": handle_bestmove,
    "turn": handle_turn,
    "demo": handle_demo,
    "status": handle_status,
    "magnet": handle_magnet,
    "jog": handle_jog,
    "step": handle_step,
    "route": handle_route,
    "move": handle_move,
    "capture": handle_capture,
    "scenario": handle_scenario,
}

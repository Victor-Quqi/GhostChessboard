"""Tests for Web console command orchestration."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from src.board_state import BoardState
from src.config import AppConfig
from src.vision.contracts import ExternalVisionPiece, ExternalVisionSnapshot
from src.web.auth import AuthError
from src.web.server import WebConsoleService
from src.xiangqi_rules import XiangqiRuleError


class FakeHardware:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, int], tuple[int, int]]] = []

    def execute_board_move(self, state: BoardState, *, start, end, include_release_offset=True):
        self.calls.append((start, end))
        occupied = set(state.occupied_cells)
        occupied.discard(start)
        occupied.discard(end)
        occupied.add(end)
        return object(), BoardState(
            occupied_cells=occupied,
            filled_capture_slots=set(state.filled_capture_slots),
            carriage_cell=end,
        )

    def safe_magnet_off(self) -> None:
        pass

    def close(self) -> None:
        pass


class RecordingBroadcast:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send(self, payload: dict[str, object]) -> None:
        self.messages.append(payload)


class WebServiceTests(unittest.TestCase):
    def test_illegal_manual_move_does_not_call_hardware(self) -> None:
        async def run() -> None:
            service = _service()
            session = service.login("pw")

            with self.assertRaises(XiangqiRuleError):
                await service.manual_move(session, (0, 0), (0, 1))

            self.assertEqual(service.hardware.calls, [])

        asyncio.run(run())

    def test_legal_manual_move_calls_hardware_and_updates_turn(self) -> None:
        async def run() -> None:
            service = _service()
            session = service.login("pw")

            move = await service.manual_move(session, (3, 0), (4, 0))

            self.assertEqual(service.hardware.calls, [((3, 0), (4, 0))])
            self.assertEqual(service.state.pieces[(4, 0)], "r_zu")
            self.assertNotIn((3, 0), service.state.pieces)
            self.assertEqual(service.state.side_to_move, "black")
            self.assertEqual(move["source"], "web")

        asyncio.run(run())

    def test_manual_move_rejects_other_player_turn_even_when_single_user(self) -> None:
        async def run() -> None:
            service = _service()
            session = service.login("pw")
            service.auth.switch_color(session.token, "black")

            with self.assertRaises(AuthError):
                await service.manual_move(session, (3, 0), (4, 0))

            self.assertEqual(service.hardware.calls, [])
            self.assertEqual(service.state.side_to_move, "red")

        asyncio.run(run())

    def test_ai_move_uses_configured_engine_path(self) -> None:
        async def run() -> None:
            service = _service()
            service.config.web.ai_engine_path = "/opt/pikafish/pikafish"
            service._ai_engine_path = service.config.web.ai_engine_path
            session = service.login("pw")

            with (
                patch("src.engine.get_best_move", return_value="a3a4") as best_move_mock,
                patch("src.turn.uci_to_cells", return_value=((3, 0), (4, 0))),
            ):
                move = await service.ai_move(session, depth=2, timeout_s=1.0)

            self.assertEqual(move["source"], "ai")
            self.assertEqual(best_move_mock.call_args.kwargs["engine_path"], "/opt/pikafish/pikafish")

        asyncio.run(run())

    def test_ai_move_emits_committed_board_before_command_goes_idle(self) -> None:
        async def run() -> None:
            service = _service()
            service.broadcast = RecordingBroadcast()
            session = service.login("pw")

            with (
                patch("src.engine.get_best_move", return_value="a3a4"),
                patch("src.turn.uci_to_cells", return_value=((3, 0), (4, 0))),
            ):
                await service.ai_move(session, depth=2, timeout_s=1.0)

            idle_state = _first_idle_state_after_busy(service.broadcast.messages)
            self.assertEqual(idle_state["side_to_move"], "black")
            self.assertIn({"cell": [4, 0], "piece": "r_zu"}, idle_state["board_pieces"])
            self.assertNotIn({"cell": [3, 0], "piece": "r_zu"}, idle_state["board_pieces"])

        asyncio.run(run())

    def test_ai_move_rejects_other_player_turn_even_when_single_user(self) -> None:
        async def run() -> None:
            service = _service()
            session = service.login("pw")
            service.auth.switch_color(session.token, "black")

            with self.assertRaises(AuthError):
                await service.ai_move(session, depth=2, timeout_s=1.0)

            self.assertEqual(service.hardware.calls, [])
            self.assertEqual(service.state.side_to_move, "red")

        asyncio.run(run())

    def test_vision_sync_applies_snapshot_before_idle_state_and_video_restart(self) -> None:
        async def run() -> None:
            service = _service()
            service.broadcast = RecordingBroadcast()
            pieces = dict(service.state.pieces)
            pieces.pop((3, 0))
            pieces[(4, 0)] = "r_zu"
            snapshot = _snapshot(pieces)

            class FakeProbe:
                def __init__(self, *, config) -> None:
                    self.config = config

                def capture_snapshot(self) -> ExternalVisionSnapshot:
                    return snapshot

            with (
                patch("src.web.video.stop_all_camera_streamers"),
                patch("src.vision.probe.GhostVisionCliProbe", FakeProbe),
            ):
                result = await service.vision_sync()

            self.assertEqual(result["status"], "legal_move")
            idle_state = _first_idle_state_after_busy(service.broadcast.messages)
            self.assertEqual(idle_state["side_to_move"], "black")
            self.assertIn({"cell": [4, 0], "piece": "r_zu"}, idle_state["board_pieces"])
            self.assertLess(
                _first_idle_state_index_after_busy(service.broadcast.messages),
                _first_message_index(service.broadcast.messages, "video_restart"),
            )

        asyncio.run(run())

    def test_reset_game_restores_opening_and_records_carriage_origin(self) -> None:
        async def run() -> None:
            service = _service(reset_carriage_cell=(2, 3))
            session = service.login("pw")
            move = await service.manual_move(session, (3, 0), (4, 0))
            service.state.captured[0] = "b_zu"
            service.state.last_vision = {"frame_id": "old"}
            self.assertEqual(move["source"], "web")

            await service.reset_game()

            self.assertEqual(service.state.side_to_move, "red")
            self.assertEqual(service.state.carriage_cell, (2, 3))
            self.assertEqual(service.state.captured, {})
            self.assertIsNone(service.state.last_move)
            self.assertIsNone(service.state.last_vision)
            self.assertIsNone(service.state.sync_warning)
            self.assertEqual(service.state.pieces[(3, 0)], "r_zu")
            self.assertNotIn((4, 0), service.state.pieces)
            self.assertEqual(service.hardware.calls, [((3, 0), (4, 0))])

        asyncio.run(run())


def _service(*, reset_carriage_cell: tuple[int, int] | None = None) -> WebConsoleService:
    config = AppConfig()
    config.web.password = "pw"
    if reset_carriage_cell is not None:
        config.web.reset_carriage_cell = list(reset_carriage_cell)
    service = WebConsoleService(config)
    service.hardware = FakeHardware()
    return service


def _snapshot(pieces: dict[tuple[int, int], str]) -> ExternalVisionSnapshot:
    return ExternalVisionSnapshot(
        provider="test",
        board_pieces=[
            ExternalVisionPiece(cell=cell, piece=piece)
            for cell, piece in sorted(pieces.items())
        ],
    )


def _first_idle_state_after_busy(messages: list[dict[str, object]]) -> dict[str, object]:
    return messages[_first_idle_state_index_after_busy(messages)]["state"]


def _first_idle_state_index_after_busy(messages: list[dict[str, object]]) -> int:
    saw_busy = False
    for index, payload in enumerate(messages):
        if payload.get("type") != "state":
            continue
        current = payload["state"]
        busy = current["hardware"]["busy"]
        if busy:
            saw_busy = True
        elif saw_busy:
            return index
    raise AssertionError("No idle state was emitted after a busy state.")


def _first_message_index(messages: list[dict[str, object]], message_type: str) -> int:
    for index, payload in enumerate(messages):
        if payload.get("type") == message_type:
            return index
    raise AssertionError(f"No {message_type} message was emitted.")


if __name__ == "__main__":
    unittest.main()

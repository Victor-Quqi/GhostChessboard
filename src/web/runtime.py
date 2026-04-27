"""Hardware runtime used by the Web command queue."""

from __future__ import annotations

import threading

from src.board import BoardController
from src.board_state import BoardCell, BoardState
from src.config import AppConfig


class HardwareRuntime:
    """Lazy GRBL session shared by serialized Web commands."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._controller = None
        self._executor = None

    def close(self) -> None:
        with self._lock:
            if self._controller is not None:
                self._controller.close()
            self._controller = None
            self._executor = None

    def status(self) -> str:
        controller = self._ensure_controller()
        return controller.status().raw

    def jog(self, *, dx_mm: float, dy_mm: float, feed_mm_min: float | None = None) -> None:
        executor = self._ensure_executor()
        executor.jog(dx_mm, dy_mm, feed_mm_min=feed_mm_min)

    def magnet(self, *, enabled: bool, pwm: int | None = None) -> None:
        controller = self._ensure_controller()
        if enabled:
            controller.magnet_on(pwm or self._config.motion.engage_pwm)
        else:
            controller.magnet_off()

    def safe_magnet_off(self) -> None:
        try:
            controller = self._controller
            if controller is not None:
                controller.magnet_off()
        except Exception:
            pass

    def execute_board_move(
        self,
        state: BoardState,
        *,
        start: BoardCell,
        end: BoardCell,
        include_release_offset: bool = True,
    ) -> tuple[object, BoardState]:
        executor = self._ensure_executor()
        board = BoardController(executor, state)
        if end in state.occupied_cells:
            execution = board.capture_piece(
                start=start,
                target=end,
                include_release_offset=include_release_offset,
            )
        else:
            execution = board.move_piece(
                start=start,
                end=end,
                include_release_offset=include_release_offset,
            )
        final_state = BoardState(
            occupied_cells=set(board.state.occupied_cells),
            filled_capture_slots=set(board.state.filled_capture_slots),
            carriage_cell=board.state.carriage_cell,
        )
        return execution, final_state

    def _ensure_controller(self):
        with self._lock:
            if self._controller is None:
                from src.machine.grbl import GrblController

                controller = GrblController(self._config)
                controller.open()
                controller.initialize()
                self._controller = controller
            return self._controller

    def _ensure_executor(self):
        with self._lock:
            if self._executor is None:
                from src.motion.executor import MotionExecutor

                self._executor = MotionExecutor(self._ensure_controller(), self._config)
            return self._executor

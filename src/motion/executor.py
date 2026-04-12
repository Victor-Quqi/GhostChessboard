"""Motion primitives built on top of GRBL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.config import AppConfig
from src.machine.grbl import GrblController


@dataclass(slots=True)
class Segment:
    direction: str
    cells: int = 1


class MotionExecutor:
    """Chess-aware motion helpers with segmented place strategy."""

    def __init__(self, controller: GrblController, config: AppConfig) -> None:
        self._controller = controller
        self._config = config

    def engage(self) -> None:
        self._controller.magnet_on(self._config.motion.engage_pwm)
        self._controller.dwell(self._config.motion.engage_delay_s)
        if self._config.motion.drag_pwm != self._config.motion.engage_pwm:
            self._controller.magnet_on(self._config.motion.drag_pwm)

    def release(self) -> None:
        self._controller.dwell(self._config.motion.settle_delay_s)
        self._controller.magnet_off()

    def jog(self, dx_mm: float, dy_mm: float, *, feed_mm_min: float | None = None) -> None:
        self._controller.jog_relative(
            dx_mm=dx_mm,
            dy_mm=dy_mm,
            feed_mm_min=feed_mm_min or self._config.motion.move_feed_mm_min,
        )

    def _axis_vector(self, direction: str) -> tuple[float, float]:
        mapping = {
            "x+": (1.0, 0.0),
            "x-": (-1.0, 0.0),
            "y+": (0.0, 1.0),
            "y-": (0.0, -1.0),
        }
        try:
            return mapping[direction]
        except KeyError as exc:
            raise ValueError(f"Unsupported direction: {direction}") from exc

    def _pitch_for_direction(self, direction: str) -> float:
        if direction.startswith("x"):
            return self._config.motion.x_cell_pitch_mm
        if direction.startswith("y"):
            return self._config.motion.y_cell_pitch_mm
        raise ValueError(f"Unsupported direction: {direction}")

    def _overshoot_pwm_profile(self) -> list[int | None]:
        start_pwm = self._config.motion.overshoot_pwm
        end_pwm = self._config.motion.overshoot_pwm_end
        segments = max(1, self._config.motion.overshoot_pwm_segments)

        if start_pwm is None:
            return [None]
        if end_pwm is None or segments == 1 or start_pwm == end_pwm:
            return [start_pwm]

        if segments == 2:
            return [start_pwm, end_pwm]

        pwm_values: list[int] = []
        for index in range(segments):
            ratio = index / (segments - 1)
            pwm = round(start_pwm + (end_pwm - start_pwm) * ratio)
            pwm_values.append(pwm)
        return pwm_values

    def compensated_distance_mm(self, direction: str, cells: int = 1, include_compensation: bool = True) -> float:
        if cells <= 0:
            raise ValueError("cells must be positive.")
        sign_x, sign_y = self._axis_vector(direction)
        pitch = self._pitch_for_direction(direction) * cells
        overshoot = self._config.compensation.overshoot_for(direction) if include_compensation else 0.0
        signed_distance = pitch + overshoot
        return signed_distance * (sign_x or sign_y)

    def step(self, direction: str, *, cells: int = 1, include_compensation: bool = True) -> None:
        distance = self.compensated_distance_mm(
            direction=direction,
            cells=cells,
            include_compensation=include_compensation,
        )
        if direction.startswith("x"):
            self.jog(distance, 0.0)
        else:
            self.jog(0.0, distance)

    def drag_step(self, direction: str, *, cells: int = 1, include_compensation: bool = True) -> None:
        if cells <= 0:
            raise ValueError("cells must be positive.")

        sign_x, sign_y = self._axis_vector(direction)
        pitch = self._pitch_for_direction(direction) * cells
        overshoot = self._config.compensation.overshoot_for(direction) if include_compensation else 0.0
        pre = self._config.compensation.pre_for(direction) if include_compensation else 0.0

        total_drag = pitch + overshoot - pre
        if total_drag <= 0:
            raise ValueError(
                f"Invalid step profile for {direction}: pitch={pitch}, overshoot={overshoot}, pre={pre}"
            )
        drag_to_target = min(total_drag, max(pitch - pre, 0.0))
        overshoot_drag = total_drag - drag_to_target

        move_feed = self._config.motion.move_feed_mm_min
        total_drag_timeout_s = 0.0

        if pre:
            total_drag_timeout_s += self._controller.jog_relative(
                dx_mm=sign_x * pre,
                dy_mm=sign_y * pre,
                feed_mm_min=move_feed,
                wait_for_idle=False,
                wait_for_ack=False,
            )

        # Queue magnet enable between pre and main drag so the carriage does not
        # fully stop at the pre boundary before pulling the piece.
        self._controller.magnet_on(self._config.motion.engage_pwm, wait_for_ack=False)

        # A delayed dwell here would reintroduce the visible stop we are trying
        # to remove. When engage and drag PWM differ, switch immediately.
        if self._config.motion.drag_pwm != self._config.motion.engage_pwm:
            self._controller.magnet_on(self._config.motion.drag_pwm, wait_for_ack=False)

        if drag_to_target:
            total_drag_timeout_s += self._controller.jog_relative(
                dx_mm=sign_x * drag_to_target,
                dy_mm=sign_y * drag_to_target,
                feed_mm_min=move_feed,
                wait_for_idle=False,
                wait_for_ack=False,
            )

        if overshoot_drag:
            pwm_profile = self._overshoot_pwm_profile()
            segment_count = len(pwm_profile)
            previous_distance = 0.0

            for index, pwm in enumerate(pwm_profile, start=1):
                if pwm is not None and pwm != self._config.motion.drag_pwm:
                    self._controller.magnet_on(pwm, wait_for_ack=False)

                target_distance = overshoot_drag * index / segment_count
                segment_distance = target_distance - previous_distance
                previous_distance = target_distance
                total_drag_timeout_s += self._controller.jog_relative(
                    dx_mm=sign_x * segment_distance,
                    dy_mm=sign_y * segment_distance,
                    feed_mm_min=move_feed,
                    wait_for_idle=False,
                    wait_for_ack=False,
                )

        self._controller.wait_for_idle(timeout_s=total_drag_timeout_s + 5.0)
        self._controller.magnet_off()

        if overshoot:
            self.jog(
                -(sign_x * overshoot),
                -(sign_y * overshoot),
                feed_mm_min=self._config.motion.return_feed_mm_min,
            )

    def drag_route(self, segments: Iterable[Segment], *, include_compensation: bool = True) -> None:
        for segment in segments:
            self.drag_step(
                segment.direction,
                cells=segment.cells,
                include_compensation=include_compensation,
            )

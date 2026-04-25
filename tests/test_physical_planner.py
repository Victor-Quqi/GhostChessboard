"""Tests for continuous physical path planning."""

from __future__ import annotations

import math
import unittest

from src.config import AppConfig
from src.motion.planner import grid_point_to_xy, plan_move


class PhysicalPlannerTests(unittest.TestCase):
    def test_uses_direct_continuous_path_when_clear(self) -> None:
        config = AppConfig()

        plan = plan_move(set(), (0, 0), (2, 2), config=config)

        self.assertEqual(plan.start, (0, 0))
        self.assertEqual(plan.end, (2, 2))
        self.assertEqual(plan.waypoints_mm[0], grid_point_to_xy(config, (0, 0)))
        self.assertEqual(plan.waypoints_mm[-1], grid_point_to_xy(config, (2, 2)))
        self.assertLessEqual(len(plan.waypoints_mm), 3)

    def test_routes_around_magnet_exclusion_zone(self) -> None:
        config = AppConfig()
        config.planning.magnet_exclusion_radius_mm = 30.0

        plan = plan_move({(1, 0)}, (0, 0), (2, 0), config=config)
        obstacle = grid_point_to_xy(config, (1, 0))

        for start, end in zip(plan.waypoints_mm, plan.waypoints_mm[1:]):
            self.assertGreaterEqual(
                _distance_point_to_segment(obstacle, start, end),
                config.planning.magnet_exclusion_radius_mm,
            )

    def test_final_overshoot_avoids_nearby_piece(self) -> None:
        config = AppConfig()
        config.planning.magnet_exclusion_radius_mm = 30.0
        end = (2, 0)
        nearby = (3, 0)

        plan = plan_move({nearby}, (0, 0), end, config=config)
        end_mm = grid_point_to_xy(config, end)
        nearby_mm = grid_point_to_xy(config, nearby)

        self.assertGreaterEqual(
            _distance_point_to_segment(nearby_mm, end_mm, plan.release_mm),
            config.planning.magnet_exclusion_radius_mm,
        )
        final_segment = (
            plan.waypoints_mm[-1][0] - plan.waypoints_mm[-2][0],
            plan.waypoints_mm[-1][1] - plan.waypoints_mm[-2][1],
        )
        self.assertGreater(_cosine(final_segment, plan.overshoot_vector_mm), 0.99)

    def test_horse_opening_can_use_direct_path_with_smaller_magnet_radius(self) -> None:
        from src.scenario import load_scenario

        config = AppConfig()
        config.planning.magnet_exclusion_radius_mm = 25.0
        config.planning.soft_clearance_mm = 5.0
        scenario = load_scenario("tests/scenarios/A_pikafish_opening.json")
        state = scenario.initial_state
        for step in scenario.steps[:2]:
            state.occupied_cells.remove(step.start)
            state.occupied_cells.add(step.end)
        horse_step = scenario.steps[2]

        plan = plan_move(
            state.occupied_cells - {horse_step.start},
            horse_step.start,
            horse_step.end,
            config=config,
        )

        self.assertEqual(len(plan.waypoints_mm), 2)

    def test_tight_top_edge_move_can_use_lateral_margin(self) -> None:
        from src.scenario import load_scenario

        config = AppConfig()
        scenario = load_scenario("tests/scenarios/B_tight_paths.json")
        state = scenario.initial_state
        for step in scenario.steps[:2]:
            plan_move(
                state.occupied_cells - {step.start},
                step.start,
                step.end,
                config=config,
            )
            state.occupied_cells.remove(step.start)
            state.occupied_cells.add(step.end)
        tight_step = scenario.steps[2]

        plan = plan_move(
            state.occupied_cells - {tight_step.start},
            tight_step.start,
            tight_step.end,
            config=config,
        )

        self.assertEqual(plan.start, tight_step.start)
        self.assertEqual(plan.end, tight_step.end)
        self.assertLessEqual(max(point[1] for point in plan.waypoints_mm), 337.0 + config.planning.y_bounds_margin_mm)
        self.assertGreater(max(point[1] for point in plan.waypoints_mm), 337.0 + config.planning.x_bounds_margin_mm)


def _distance_point_to_segment(point, start, end) -> float:
    segment = (end[0] - start[0], end[1] - start[1])
    length_squared = segment[0] * segment[0] + segment[1] * segment[1]
    if length_squared <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    ratio = ((point[0] - start[0]) * segment[0] + (point[1] - start[1]) * segment[1]) / length_squared
    ratio = max(0.0, min(1.0, ratio))
    closest = (start[0] + segment[0] * ratio, start[1] + segment[1] * ratio)
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _cosine(left, right) -> float:
    left_length = math.hypot(left[0], left[1])
    right_length = math.hypot(right[0], right[1])
    if left_length <= 1e-12 or right_length <= 1e-12:
        return 0.0
    return (left[0] * right[0] + left[1] * right[1]) / (left_length * right_length)


if __name__ == "__main__":
    unittest.main()

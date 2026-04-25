"""Continuous physical move planning for magnet-driven chess pieces."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
import math

from src.config import AppConfig
from src.motion.contracts import DragPlan, GridPoint, PointMm

BoardCell = tuple[int, int]
GridCell = tuple[int, int]


class MovePlanningError(ValueError):
    """Raised when a board move cannot be planned safely."""


@dataclass(frozen=True, slots=True)
class _Obstacle:
    cell: GridCell
    center_mm: PointMm


def validate_cell(cell: GridCell, *, max_x: int = 9, max_y: int = 8) -> None:
    """Validate a cell on a bounded grid."""
    x_index, y_index = cell
    if not (0 <= x_index <= max_x and 0 <= y_index <= max_y):
        raise MovePlanningError(
            f"Cell out of range: x={x_index}, y={y_index}, bounds=(0-{max_x}, 0-{max_y})"
        )


def grid_point_to_xy(config: AppConfig, cell: GridPoint) -> PointMm:
    """Convert an extended-grid point to configured physical coordinates."""
    x_index, y_index = cell
    return (
        x_index * config.motion.x_cell_pitch_mm,
        y_index * config.motion.y_cell_pitch_mm,
    )


def plan_grid_move(
    occupied: set[GridCell],
    start: GridCell,
    end: GridCell,
    *,
    config: AppConfig,
    max_x: int = 9,
    max_y: int = 8,
) -> DragPlan:
    """Plan a continuous drag path that avoids magnetic mis-pickup."""
    validate_cell(start, max_x=max_x, max_y=max_y)
    validate_cell(end, max_x=max_x, max_y=max_y)

    if start == end:
        start_mm = grid_point_to_xy(config, start)
        return DragPlan(
            start=start,
            end=end,
            waypoints_mm=[start_mm],
            release_mm=start_mm,
            overshoot_vector_mm=(0.0, 0.0),
        )

    blocked = set(occupied)
    blocked.discard(start)
    blocked.discard(end)

    obstacles = [
        _Obstacle(cell=cell, center_mm=grid_point_to_xy(config, cell))
        for cell in sorted(blocked)
    ]
    start_mm = grid_point_to_xy(config, start)
    end_mm = grid_point_to_xy(config, end)
    route_clearance = _route_clearance(config)
    roadmap = _VisibilityRoadmap.build(
        config=config,
        start_mm=start_mm,
        obstacles=obstacles,
        clearance=route_clearance,
        max_x=max_x,
        max_y=max_y,
    )

    best_plan: DragPlan | None = None
    best_cost = math.inf

    for release_unit in _release_units(config, start_mm, end_mm):
        candidate = _plan_with_release_direction(
            config=config,
            start=start,
            end=end,
            end_mm=end_mm,
            release_unit=release_unit,
            obstacles=obstacles,
            route_clearance=route_clearance,
            roadmap=roadmap,
            max_x=max_x,
            max_y=max_y,
        )
        if candidate is None:
            continue

        cost, plan = candidate
        if cost < best_cost:
            best_cost = cost
            best_plan = plan

    if best_plan is None:
        raise MovePlanningError(
            f"No safe physical path found from x={start[0]}, y={start[1]} to x={end[0]}, y={end[1]}"
        )

    return best_plan


def plan_move(
    occupied: set[BoardCell],
    start: BoardCell,
    end: BoardCell,
    *,
    config: AppConfig,
) -> DragPlan:
    """Plan a continuous move on the 10x9 main board."""
    return plan_grid_move(occupied=occupied, start=start, end=end, config=config, max_x=9, max_y=8)


def _plan_with_release_direction(
    *,
    config: AppConfig,
    start: GridCell,
    end: GridCell,
    end_mm: PointMm,
    release_unit: PointMm,
    obstacles: list[_Obstacle],
    route_clearance: float,
    roadmap: "_VisibilityRoadmap",
    max_x: int,
    max_y: int,
) -> tuple[float, DragPlan] | None:
    overshoot_mm = config.compensation.release_overshoot_mm
    approach_mm = config.planning.release_approach_mm
    approach_mm = max(approach_mm, min(config.motion.x_cell_pitch_mm, config.motion.y_cell_pitch_mm) * 0.65)

    anchor_mm = _sub(end_mm, _scale(release_unit, approach_mm))
    release_mm = _add(end_mm, _scale(release_unit, overshoot_mm))

    bounds = _planning_bounds(config, max_x=max_x, max_y=max_y)
    if not _inside_bounds(anchor_mm, bounds) or not _inside_bounds(release_mm, bounds):
        return None

    if not _point_clear(anchor_mm, obstacles, route_clearance):
        return None
    if not _segment_clear(anchor_mm, end_mm, obstacles, route_clearance):
        return None
    if not _segment_clear(end_mm, release_mm, obstacles, config.planning.magnet_exclusion_radius_mm):
        return None

    graph_path = roadmap.find_path_to(anchor_mm)
    if graph_path is None:
        return None

    waypoints = _smooth_path(graph_path, obstacles, route_clearance)
    if _distance(waypoints[-1], end_mm) > 1e-6:
        waypoints.append(end_mm)
    waypoints = _drop_collinear_waypoints(waypoints)

    cost = _path_cost(waypoints, obstacles, route_clearance, config)
    cost += _segment_cost(end_mm, release_mm, obstacles, config.planning.magnet_exclusion_radius_mm, config)
    cost += _terminal_turn_cost(waypoints, release_unit, config)

    plan = DragPlan(
        start=start,
        end=end,
        waypoints_mm=waypoints,
        release_mm=release_mm,
        overshoot_vector_mm=_scale(release_unit, overshoot_mm),
    )
    return cost, plan


@dataclass(slots=True)
class _VisibilityRoadmap:
    nodes: list[PointMm]
    obstacles: list[_Obstacle]
    clearance: float
    config: AppConfig
    distances: list[float]
    previous: list[int | None]

    @classmethod
    def build(
        cls,
        *,
        config: AppConfig,
        start_mm: PointMm,
        obstacles: list[_Obstacle],
        clearance: float,
        max_x: int,
        max_y: int,
    ) -> "_VisibilityRoadmap":
        nodes = _candidate_nodes(
            config=config,
            start_mm=start_mm,
            obstacles=obstacles,
            clearance=clearance,
            max_x=max_x,
            max_y=max_y,
        )
        adjacency = _build_visibility_adjacency(
            nodes=nodes,
            obstacles=obstacles,
            clearance=clearance,
            config=config,
        )
        distances, previous = _shortest_paths_from_start(adjacency)
        return cls(
            nodes=nodes,
            obstacles=obstacles,
            clearance=clearance,
            config=config,
            distances=distances,
            previous=previous,
        )

    def find_path_to(self, target_mm: PointMm) -> list[PointMm] | None:
        best_node: int | None = None
        best_cost = math.inf
        for index, node in enumerate(self.nodes):
            if math.isinf(self.distances[index]):
                continue
            if not _segment_clear(node, target_mm, self.obstacles, self.clearance):
                continue
            cost = self.distances[index] + _segment_cost(
                node,
                target_mm,
                self.obstacles,
                self.clearance,
                self.config,
            )
            if cost < best_cost:
                best_cost = cost
                best_node = index

        if best_node is None:
            return None

        path = self._path_to_node(best_node)
        if _distance(path[-1], target_mm) > 1e-6:
            path.append(target_mm)
        return path

    def _path_to_node(self, node_index: int) -> list[PointMm]:
        path_indices: list[int] = []
        current: int | None = node_index
        while current is not None:
            path_indices.append(current)
            current = self.previous[current]
        path_indices.reverse()
        return [self.nodes[index] for index in path_indices]


def _candidate_nodes(
    *,
    config: AppConfig,
    start_mm: PointMm,
    obstacles: list[_Obstacle],
    clearance: float,
    max_x: int,
    max_y: int,
) -> list[PointMm]:
    bounds = _planning_bounds(config, max_x=max_x, max_y=max_y)
    nodes = [start_mm]
    orbit_radius = clearance + config.planning.waypoint_clearance_mm
    for obstacle in obstacles:
        for unit in _unit_circle(config.planning.candidate_angle_count):
            point = _add(obstacle.center_mm, _scale(unit, orbit_radius))
            if _inside_bounds(point, bounds) and _point_clear(point, obstacles, clearance):
                nodes.append(point)
    return nodes


def _build_visibility_adjacency(
    *,
    nodes: list[PointMm],
    obstacles: list[_Obstacle],
    clearance: float,
    config: AppConfig,
) -> list[list[tuple[int, float]]]:
    adjacency: list[list[tuple[int, float]]] = [[] for _ in nodes]
    for left in range(len(nodes)):
        for right in range(left + 1, len(nodes)):
            if not _segment_clear(nodes[left], nodes[right], obstacles, clearance):
                continue
            weight = _segment_cost(nodes[left], nodes[right], obstacles, clearance, config)
            adjacency[left].append((right, weight))
            adjacency[right].append((left, weight))
    return adjacency


def _shortest_paths_from_start(
    adjacency: list[list[tuple[int, float]]],
) -> tuple[list[float], list[int | None]]:
    distances = [math.inf] * len(adjacency)
    previous: list[int | None] = [None] * len(adjacency)
    distances[0] = 0.0
    queue: list[tuple[float, int]] = [(0.0, 0)]

    while queue:
        current_distance, current = heappop(queue)
        if current_distance > distances[current]:
            continue
        for neighbor, weight in adjacency[current]:
            candidate = current_distance + weight
            if candidate >= distances[neighbor]:
                continue
            distances[neighbor] = candidate
            previous[neighbor] = current
            heappush(queue, (candidate, neighbor))

    return distances, previous


def _smooth_path(path: list[PointMm], obstacles: list[_Obstacle], clearance: float) -> list[PointMm]:
    if len(path) <= 2:
        return path

    smoothed = [path[0]]
    current = 0
    while current < len(path) - 1:
        next_index = len(path) - 1
        while next_index > current + 1:
            if _segment_clear(path[current], path[next_index], obstacles, clearance):
                break
            next_index -= 1
        smoothed.append(path[next_index])
        current = next_index
    return smoothed


def _drop_collinear_waypoints(path: list[PointMm]) -> list[PointMm]:
    if len(path) <= 2:
        return path

    reduced = [path[0]]
    for current, nxt in zip(path[1:-1], path[2:]):
        previous = reduced[-1]
        incoming = _sub(current, previous)
        outgoing = _sub(nxt, current)
        if _dot(incoming, outgoing) > 0.0 and _distance_point_to_segment(current, previous, nxt) < 1e-6:
            continue
        reduced.append(current)
    reduced.append(path[-1])
    return reduced


def _route_clearance(config: AppConfig) -> float:
    piece_collision_clearance = (
        2.0 * config.planning.piece_radius_mm + config.planning.piece_collision_margin_mm
    )
    return max(config.planning.magnet_exclusion_radius_mm, piece_collision_clearance)


def _planning_bounds(config: AppConfig, *, max_x: int, max_y: int) -> tuple[float, float, float, float]:
    x_margin = config.planning.x_bounds_margin_mm
    y_margin = config.planning.y_bounds_margin_mm
    return (
        -x_margin,
        max_x * config.motion.x_cell_pitch_mm + x_margin,
        -y_margin,
        max_y * config.motion.y_cell_pitch_mm + y_margin,
    )


def _inside_bounds(point: PointMm, bounds: tuple[float, float, float, float]) -> bool:
    min_x, max_x, min_y, max_y = bounds
    return min_x <= point[0] <= max_x and min_y <= point[1] <= max_y


def _point_clear(point: PointMm, obstacles: list[_Obstacle], clearance: float) -> bool:
    return all(_distance(point, obstacle.center_mm) >= clearance for obstacle in obstacles)


def _segment_clear(start: PointMm, end: PointMm, obstacles: list[_Obstacle], clearance: float) -> bool:
    min_x = min(start[0], end[0]) - clearance
    max_x = max(start[0], end[0]) + clearance
    min_y = min(start[1], end[1]) - clearance
    max_y = max(start[1], end[1]) + clearance

    for obstacle in obstacles:
        obstacle_x, obstacle_y = obstacle.center_mm
        if obstacle_x < min_x or obstacle_x > max_x or obstacle_y < min_y or obstacle_y > max_y:
            continue
        if _distance_point_to_segment(obstacle.center_mm, start, end) < clearance:
            return False
    return True


def _segment_cost(
    start: PointMm,
    end: PointMm,
    obstacles: list[_Obstacle],
    clearance: float,
    config: AppConfig,
) -> float:
    length = _distance(start, end)
    soft_radius = clearance + config.planning.soft_clearance_mm
    min_x = min(start[0], end[0]) - soft_radius
    max_x = max(start[0], end[0]) + soft_radius
    min_y = min(start[1], end[1]) - soft_radius
    max_y = max(start[1], end[1]) + soft_radius
    penalty = 0.0
    for obstacle in obstacles:
        obstacle_x, obstacle_y = obstacle.center_mm
        if obstacle_x < min_x or obstacle_x > max_x or obstacle_y < min_y or obstacle_y > max_y:
            continue
        distance = _distance_point_to_segment(obstacle.center_mm, start, end)
        if distance < soft_radius:
            penalty += (soft_radius - distance) ** 2
    return length + penalty * config.planning.clearance_weight


def _path_cost(
    waypoints: list[PointMm],
    obstacles: list[_Obstacle],
    clearance: float,
    config: AppConfig,
) -> float:
    cost = 0.0
    for start, end in zip(waypoints, waypoints[1:]):
        cost += _segment_cost(start, end, obstacles, clearance, config)
    for previous, current, nxt in zip(waypoints, waypoints[1:], waypoints[2:]):
        cost += _turn_cost(previous, current, nxt, config)
    return cost


def _terminal_turn_cost(waypoints: list[PointMm], release_unit: PointMm, config: AppConfig) -> float:
    if len(waypoints) < 2:
        return 0.0
    incoming = _unit(_sub(waypoints[-1], waypoints[-2]))
    alignment = max(-1.0, min(1.0, _dot(incoming, release_unit)))
    return (1.0 - alignment) * config.planning.turn_weight


def _turn_cost(previous: PointMm, current: PointMm, nxt: PointMm, config: AppConfig) -> float:
    incoming = _unit(_sub(current, previous))
    outgoing = _unit(_sub(nxt, current))
    alignment = max(-1.0, min(1.0, _dot(incoming, outgoing)))
    return (1.0 - alignment) * config.planning.turn_weight


def _unit_circle(count: int) -> list[PointMm]:
    safe_count = max(8, count)
    return [
        (math.cos(2.0 * math.pi * index / safe_count), math.sin(2.0 * math.pi * index / safe_count))
        for index in range(safe_count)
    ]


def _release_units(config: AppConfig, start_mm: PointMm, end_mm: PointMm) -> list[PointMm]:
    units: list[PointMm] = []
    direct = _unit(_sub(end_mm, start_mm))
    if _distance((0.0, 0.0), direct) > 1e-9:
        units.append(direct)
    for unit in _unit_circle(config.planning.release_angle_count):
        if all(_distance(unit, existing) > 1e-6 for existing in units):
            units.append(unit)
    return units


def _distance(left: PointMm, right: PointMm) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _distance_point_to_segment(point: PointMm, start: PointMm, end: PointMm) -> float:
    segment = _sub(end, start)
    length_squared = _dot(segment, segment)
    if length_squared <= 1e-12:
        return _distance(point, start)
    ratio = _dot(_sub(point, start), segment) / length_squared
    ratio = max(0.0, min(1.0, ratio))
    closest = _add(start, _scale(segment, ratio))
    return _distance(point, closest)


def _unit(vector: PointMm) -> PointMm:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-12:
        return (0.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def _add(left: PointMm, right: PointMm) -> PointMm:
    return (left[0] + right[0], left[1] + right[1])


def _sub(left: PointMm, right: PointMm) -> PointMm:
    return (left[0] - right[0], left[1] - right[1])


def _scale(vector: PointMm, scalar: float) -> PointMm:
    return (vector[0] * scalar, vector[1] * scalar)


def _dot(left: PointMm, right: PointMm) -> float:
    return left[0] * right[0] + left[1] * right[1]

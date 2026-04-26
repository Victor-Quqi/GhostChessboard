"""Generate a scenario JSON by self-playing a Xiangqi engine from a start FEN.

Produces a sequence of ``move`` / ``capture`` steps in the project's internal
``(x, y)`` grid, suitable for ``python -m src.cli scenario <path>``. Captures
are detected by noticing that the UCI destination cell was occupied by the
opposing side before the move.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.engine import get_best_move
from src.vision.fen import CONTRACT_PIECE_TO_FEN, VALID_FEN_PIECE_CHARS

STANDARD_OPENING_FEN = (
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
)

UCI_FILES = "abcdefghi"


def parse_placement(fen: str) -> dict[tuple[int, int], str]:
    """Parse a Xiangqi FEN placement field into a (x, y) -> piece char map."""
    placement = fen.strip().split(" ", 1)[0]
    ranks = placement.split("/")
    if len(ranks) != 10:
        raise ValueError(f"Xiangqi FEN must have 10 ranks, got {len(ranks)}.")

    board: dict[tuple[int, int], str] = {}
    for rank_index, rank in enumerate(ranks):
        x_index = 9 - rank_index
        column_cursor = 0
        for symbol in rank:
            if symbol.isdigit():
                column_cursor += int(symbol)
                continue
            if symbol not in VALID_FEN_PIECE_CHARS:
                raise ValueError(f"Unsupported symbol {symbol!r} in rank {rank_index}.")
            y_index = 8 - column_cursor
            board[(x_index, y_index)] = symbol
            column_cursor += 1
        if column_cursor != 9:
            raise ValueError(f"FEN rank {rank_index} does not cover 9 columns: {rank!r}")
    return board


def serialize_placement(board: dict[tuple[int, int], str]) -> str:
    """Serialize a (x, y) -> piece char map back into a FEN placement field."""
    ranks: list[str] = []
    for x_index in range(9, -1, -1):
        parts: list[str] = []
        empty = 0
        for y_index in range(8, -1, -1):
            symbol = board.get((x_index, y_index))
            if symbol is None:
                empty += 1
                continue
            if empty:
                parts.append(str(empty))
                empty = 0
            parts.append(symbol)
        if empty:
            parts.append(str(empty))
        ranks.append("".join(parts) if parts else "9")
    return "/".join(ranks)


def uci_to_cells(move_uci: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """Parse a UCI move string like ``h2e2`` into two (x, y) cells.

    File ``a`` sits at y=8 and file ``i`` at y=0 (project convention places
    ``y_zero_is_red_left=True`` in the FEN serializer, which mirrors the UCCI
    file ordering relative to the rank string's left-to-right layout).
    """
    if len(move_uci) != 4:
        raise ValueError(f"Unexpected UCI move length: {move_uci!r}")
    try:
        start_y = 8 - UCI_FILES.index(move_uci[0])
        start_x = int(move_uci[1])
        end_y = 8 - UCI_FILES.index(move_uci[2])
        end_x = int(move_uci[3])
    except ValueError as exc:
        raise ValueError(f"Unparseable UCI move: {move_uci!r}") from exc
    return (start_x, start_y), (end_x, end_y)


def next_side_and_fullmove(side: str, fullmove: int) -> tuple[str, int]:
    return ("b", fullmove) if side == "w" else ("w", fullmove + 1)


def build_scenario(
    *,
    start_fen: str,
    plies: int,
    engine_path: str | Path | None,
    depth: int,
    timeout_s: float,
    carriage: tuple[int, int],
    name: str,
) -> dict:
    board = parse_placement(start_fen)
    side = start_fen.strip().split(" ")[1]
    fullmove = int(start_fen.strip().split(" ")[-1])

    steps = []
    for ply in range(plies):
        placement = serialize_placement(board)
        fen = f"{placement} {side} - - 0 {fullmove}"
        move_uci = get_best_move(
            fen,
            engine_path=engine_path,
            depth=depth,
            timeout_s=timeout_s,
        )
        start_cell, end_cell = uci_to_cells(move_uci)
        piece = board.get(start_cell)
        if piece is None:
            raise RuntimeError(
                f"Engine returned move {move_uci} but no piece at {start_cell}."
            )
        captured = board.get(end_cell)
        kind = "capture" if captured is not None else "move"
        step = {
            "kind": kind,
            "start": list(start_cell),
            "end": list(end_cell),
        }
        steps.append(step)
        print(
            f"ply {ply + 1}/{plies} side={side} uci={move_uci} "
            f"{kind} {start_cell}->{end_cell} piece={piece}"
            + (f" captures={captured}" if captured else "")
        )
        board[end_cell] = piece
        board.pop(start_cell, None)
        side, fullmove = next_side_and_fullmove(side, fullmove)

    return {
        "name": name,
        "initial": {"fen": start_fen, "carriage": list(carriage)},
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="A_pikafish_opening", help="Scenario name.")
    parser.add_argument("--start-fen", default=STANDARD_OPENING_FEN, help="Start FEN.")
    parser.add_argument("--plies", type=int, default=15, help="Number of plies to generate.")
    parser.add_argument("--depth", type=int, default=12, help="Engine search depth per ply.")
    parser.add_argument("--timeout-s", type=float, default=20.0, help="Per-ply timeout.")
    parser.add_argument("--engine", type=Path, help="Pikafish executable (or set GHOSTCHESSBOARD_PIKAFISH).")
    parser.add_argument("--carriage", default="0,0", help="Initial carriage cell as x,y.")
    parser.add_argument("--output", type=Path, required=True, help="Output scenario JSON path.")
    args = parser.parse_args()

    carriage_x, carriage_y = (int(token.strip()) for token in args.carriage.split(","))
    scenario = build_scenario(
        start_fen=args.start_fen,
        plies=args.plies,
        engine_path=args.engine,
        depth=args.depth,
        timeout_s=args.timeout_s,
        carriage=(carriage_x, carriage_y),
        name=args.name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scenario, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output} with {len(scenario['steps'])} steps.")


if __name__ == "__main__":
    main()

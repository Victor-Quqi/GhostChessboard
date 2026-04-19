"""Convert normalized external vision snapshots to Xiangqi FEN."""

from __future__ import annotations

from src.coords import validate_main_board_cell
from src.vision.contracts import ExternalVisionSnapshot

CONTRACT_PIECE_TO_FEN = {
    "b_jiang": "k",
    "b_shi": "a",
    "b_xiang": "b",
    "b_ma": "n",
    "b_ju": "r",
    "b_pao": "c",
    "b_zu": "p",
    "r_jiang": "K",
    "r_shi": "A",
    "r_xiang": "B",
    "r_ma": "N",
    "r_ju": "R",
    "r_pao": "C",
    "r_zu": "P",
}

SIDE_TO_MOVE_ALIASES = {
    "w": "w",
    "white": "w",
    "r": "w",
    "red": "w",
    "b": "b",
    "black": "b",
}


def snapshot_to_xiangqi_fen(
    snapshot: ExternalVisionSnapshot,
    *,
    side_to_move: str = "w",
    halfmove_clock: int = 0,
    fullmove_number: int = 1,
    y_zero_is_red_left: bool = True,
) -> str:
    """Serialize one normalized snapshot to a full Xiangqi FEN string."""

    side_to_move = normalize_xiangqi_side_to_move(side_to_move)
    if halfmove_clock < 0:
        raise ValueError(f"halfmove_clock must be non-negative, got {halfmove_clock}")
    if fullmove_number < 1:
        raise ValueError(f"fullmove_number must be positive, got {fullmove_number}")

    occupied: dict[tuple[int, int], str] = {}
    for piece in snapshot.board_pieces:
        validate_main_board_cell(piece.cell)
        if piece.cell in occupied:
            raise ValueError(f"Duplicate board cell in vision result: {piece.cell}")
        try:
            occupied[piece.cell] = CONTRACT_PIECE_TO_FEN[piece.piece]
        except KeyError as exc:
            raise ValueError(f"Unsupported piece label for Xiangqi FEN: {piece.piece!r}") from exc

    row_indices = range(9, -1, -1)
    col_indices = range(8, -1, -1) if y_zero_is_red_left else range(0, 9)

    ranks = []
    for x_index in row_indices:
        rank_parts: list[str] = []
        empty_count = 0
        for y_index in col_indices:
            symbol = occupied.get((x_index, y_index))
            if symbol is None:
                empty_count += 1
                continue
            if empty_count:
                rank_parts.append(str(empty_count))
                empty_count = 0
            rank_parts.append(symbol)
        if empty_count:
            rank_parts.append(str(empty_count))
        ranks.append("".join(rank_parts) if rank_parts else "9")

    placement = "/".join(ranks)
    return f"{placement} {side_to_move} - - {halfmove_clock} {fullmove_number}"


def normalize_xiangqi_side_to_move(side_to_move: str) -> str:
    """Normalize red/black aliases to the w/b FEN convention."""

    normalized = side_to_move.strip().lower()
    try:
        return SIDE_TO_MOVE_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError(
            "side_to_move must be one of 'red', 'black', 'r', 'b', 'w', or 'white', "
            f"got {side_to_move!r}"
        ) from exc

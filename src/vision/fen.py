"""Convert normalized external vision snapshots to Xiangqi FEN."""

from __future__ import annotations

from src.board_state import BoardState
from src.coords import GridPoint, validate_grid_point, validate_main_board_cell
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

VALID_FEN_PIECE_CHARS = frozenset("kabnrcpKABNRCP")

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


def board_state_from_xiangqi_fen(
    fen: str,
    *,
    carriage_cell: GridPoint | None = None,
    y_zero_is_red_left: bool = True,
) -> BoardState:
    """Parse a Xiangqi FEN placement into a BoardState occupancy set.

    The inverse of ``snapshot_to_xiangqi_fen`` but only retains which cells are
    occupied; piece identity is discarded. Capture-area slots are always empty
    because standard Xiangqi FEN does not encode them.
    """

    if carriage_cell is not None:
        validate_grid_point(carriage_cell)

    placement = fen.strip().split(" ", 1)[0]
    ranks = placement.split("/")
    if len(ranks) != 10:
        raise ValueError(f"Xiangqi FEN must have 10 ranks separated by '/', got {len(ranks)}.")

    col_indices = list(range(8, -1, -1)) if y_zero_is_red_left else list(range(0, 9))

    occupied: set[tuple[int, int]] = set()
    for rank_index, rank in enumerate(ranks):
        x_index = 9 - rank_index
        column_cursor = 0
        for symbol in rank:
            if symbol.isdigit():
                column_cursor += int(symbol)
                continue
            if symbol not in VALID_FEN_PIECE_CHARS:
                raise ValueError(f"Unsupported FEN symbol {symbol!r} in rank {rank_index}.")
            if column_cursor >= 9:
                raise ValueError(f"FEN rank {rank_index} overflows 9 columns: {rank!r}")
            y_index = col_indices[column_cursor]
            cell = (x_index, y_index)
            validate_main_board_cell(cell)
            occupied.add(cell)
            column_cursor += 1
        if column_cursor != 9:
            raise ValueError(f"FEN rank {rank_index} does not cover 9 columns: {rank!r}")

    return BoardState(occupied_cells=occupied, carriage_cell=carriage_cell)

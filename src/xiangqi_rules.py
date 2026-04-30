"""Xiangqi move validation with GhostVision piece labels."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.board_state import BoardCell
from src.coords import validate_main_board_cell

PieceMap = Mapping[BoardCell, str]

KNOWN_PIECES = frozenset(
    {
        "b_jiang",
        "b_shi",
        "b_xiang",
        "b_ma",
        "b_ju",
        "b_pao",
        "b_zu",
        "r_jiang",
        "r_shi",
        "r_xiang",
        "r_ma",
        "r_ju",
        "r_pao",
        "r_zu",
    }
)

PIECE_TO_FEN = {
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

SIDE_TO_FEN = {
    "red": "w",
    "r": "w",
    "w": "w",
    "white": "w",
    "black": "b",
    "b": "b",
}

SIDE_ALIASES = {
    "red": "red",
    "r": "red",
    "w": "red",
    "white": "red",
    "black": "black",
    "b": "black",
}


class XiangqiRuleError(ValueError):
    """Raised when a move violates Xiangqi rules."""


@dataclass(frozen=True, slots=True)
class XiangqiTerminalStatus:
    game_over: bool
    winner: str | None
    reason: str | None
    message: str


def normalize_side(side: str) -> str:
    """Normalize supported side aliases to ``red`` or ``black``."""

    normalized = side.strip().lower()
    try:
        return SIDE_ALIASES[normalized]
    except KeyError as exc:
        raise XiangqiRuleError(f"Unknown Xiangqi side: {side!r}") from exc


def opposite_side(side: str) -> str:
    """Return the opposing side."""

    normalized = normalize_side(side)
    return "black" if normalized == "red" else "red"


def piece_side(piece: str) -> str:
    """Return ``red`` or ``black`` for a GhostVision piece label."""

    _validate_piece(piece)
    return "red" if piece.startswith("r_") else "black"


def piece_kind(piece: str) -> str:
    """Return the Xiangqi piece kind from a GhostVision piece label."""

    _validate_piece(piece)
    return piece.split("_", 1)[1]


def validate_legal_move(
    pieces: PieceMap,
    start: BoardCell,
    end: BoardCell,
    *,
    side_to_move: str | None = None,
) -> None:
    """Validate one complete Xiangqi move on a board with piece identity.

    The check includes piece movement, blockers, same-side captures, palace and
    river limits, cannon screens, horse/elephant blocking, flying generals, and
    whether the moving side leaves its own general in check.
    """

    _validate_cell(start)
    _validate_cell(end)
    if start == end:
        raise XiangqiRuleError("Start and end must be different cells.")

    board = dict(pieces)
    for cell, piece in board.items():
        _validate_cell(cell)
        _validate_piece(piece)

    moving_piece = board.get(start)
    if moving_piece is None:
        raise XiangqiRuleError(f"No piece at start cell {start}.")

    moving_side = piece_side(moving_piece)
    if side_to_move is not None and normalize_side(side_to_move) != moving_side:
        raise XiangqiRuleError(f"It is not {moving_side}'s turn.")

    target_piece = board.get(end)
    if target_piece is not None and piece_side(target_piece) == moving_side:
        raise XiangqiRuleError("Cannot capture a same-side piece.")

    if not _piece_can_move(board, start, end, moving_piece):
        raise XiangqiRuleError(f"Illegal {moving_piece} move from {start} to {end}.")

    after = apply_move_to_pieces(board, start, end)
    if generals_face(after):
        raise XiangqiRuleError("Generals may not face each other.")
    if is_in_check(after, moving_side):
        raise XiangqiRuleError(f"Move leaves {moving_side} in check.")


def has_legal_move(pieces: PieceMap, side: str) -> bool:
    """Return whether ``side`` has at least one legal move."""

    normalized_side = normalize_side(side)
    board = dict(pieces)
    for start, piece in board.items():
        if piece_side(piece) != normalized_side:
            continue
        for x_index in range(10):
            for y_index in range(9):
                try:
                    validate_legal_move(board, start, (x_index, y_index), side_to_move=normalized_side)
                except XiangqiRuleError:
                    continue
                return True
    return False


def terminal_status(pieces: PieceMap, side_to_move: str) -> XiangqiTerminalStatus:
    """Return terminal state for the side to move."""

    normalized_side = normalize_side(side_to_move)
    if has_legal_move(pieces, normalized_side):
        return XiangqiTerminalStatus(
            game_over=False,
            winner=None,
            reason=None,
            message=f"{normalized_side} to move.",
        )

    if is_in_check(pieces, normalized_side):
        winner = opposite_side(normalized_side)
        return XiangqiTerminalStatus(
            game_over=True,
            winner=winner,
            reason="checkmate",
            message=f"{normalized_side} is checkmated; {winner} wins.",
        )

    return XiangqiTerminalStatus(
        game_over=True,
        winner=None,
        reason="stalemate",
        message=f"{normalized_side} has no legal move; game is drawn.",
    )


def apply_move_to_pieces(pieces: PieceMap, start: BoardCell, end: BoardCell) -> dict[BoardCell, str]:
    """Return a copied piece map after moving ``start`` to ``end``."""

    board = dict(pieces)
    moving_piece = board.pop(start)
    board.pop(end, None)
    board[end] = moving_piece
    return board


def is_in_check(pieces: PieceMap, side: str) -> bool:
    """Return whether ``side`` is currently attacked."""

    normalized_side = normalize_side(side)
    general_cell = _find_general(pieces, normalized_side)
    if general_cell is None:
        return False

    enemy_side = opposite_side(normalized_side)
    for cell, piece in pieces.items():
        if piece_side(piece) == enemy_side and _piece_attacks(pieces, cell, general_cell, piece):
            return True
    return False


def generals_face(pieces: PieceMap) -> bool:
    """Return whether the two generals face on the same file without blockers."""

    red_general = _find_general(pieces, "red")
    black_general = _find_general(pieces, "black")
    if red_general is None or black_general is None:
        return False
    if red_general[1] != black_general[1]:
        return False
    return _count_between(pieces, red_general, black_general) == 0


def pieces_to_xiangqi_fen(
    pieces: PieceMap,
    *,
    side_to_move: str = "red",
    halfmove_clock: int = 0,
    fullmove_number: int = 1,
    y_zero_is_red_left: bool = True,
) -> str:
    """Serialize a GhostVision-labeled piece map to a full Xiangqi FEN."""

    if halfmove_clock < 0:
        raise ValueError(f"halfmove_clock must be non-negative, got {halfmove_clock}")
    if fullmove_number < 1:
        raise ValueError(f"fullmove_number must be positive, got {fullmove_number}")

    occupied: dict[BoardCell, str] = {}
    for cell, piece in pieces.items():
        _validate_cell(cell)
        _validate_piece(piece)
        if cell in occupied:
            raise ValueError(f"Duplicate board cell: {cell}")
        occupied[cell] = PIECE_TO_FEN[piece]

    row_indices = range(9, -1, -1)
    col_indices = range(8, -1, -1) if y_zero_is_red_left else range(0, 9)

    ranks: list[str] = []
    for x_index in row_indices:
        parts: list[str] = []
        empty_count = 0
        for y_index in col_indices:
            symbol = occupied.get((x_index, y_index))
            if symbol is None:
                empty_count += 1
                continue
            if empty_count:
                parts.append(str(empty_count))
                empty_count = 0
            parts.append(symbol)
        if empty_count:
            parts.append(str(empty_count))
        ranks.append("".join(parts) if parts else "9")

    side_key = side_to_move.strip().lower()
    try:
        fen_side = SIDE_TO_FEN[side_key]
    except KeyError as exc:
        raise XiangqiRuleError(f"Unknown Xiangqi side: {side_to_move!r}") from exc
    return f"{'/'.join(ranks)} {fen_side} - - {halfmove_clock} {fullmove_number}"


def standard_starting_pieces() -> dict[BoardCell, str]:
    """Return the standard initial Xiangqi position using GhostVision labels."""

    pieces: dict[BoardCell, str] = {}
    back_rank = ["ju", "ma", "xiang", "shi", "jiang", "shi", "xiang", "ma", "ju"]
    for y_index, kind in enumerate(back_rank):
        pieces[(0, y_index)] = f"r_{kind}"
        pieces[(9, y_index)] = f"b_{kind}"
    for y_index in (1, 7):
        pieces[(2, y_index)] = "r_pao"
        pieces[(7, y_index)] = "b_pao"
    for y_index in (0, 2, 4, 6, 8):
        pieces[(3, y_index)] = "r_zu"
        pieces[(6, y_index)] = "b_zu"
    return pieces


def _piece_can_move(pieces: PieceMap, start: BoardCell, end: BoardCell, piece: str) -> bool:
    kind = piece_kind(piece)
    if kind == "ju":
        return _moves_straight(start, end) and _count_between(pieces, start, end) == 0
    if kind == "ma":
        return _horse_can_move(pieces, start, end)
    if kind == "xiang":
        return _elephant_can_move(pieces, start, end, piece_side(piece))
    if kind == "shi":
        return _advisor_can_move(start, end, piece_side(piece))
    if kind == "jiang":
        return _general_can_move(start, end, piece_side(piece))
    if kind == "pao":
        target_occupied = end in pieces
        screen_count = _count_between(pieces, start, end)
        return _moves_straight(start, end) and screen_count == (1 if target_occupied else 0)
    if kind == "zu":
        return _soldier_can_move(start, end, piece_side(piece))
    return False


def _piece_attacks(pieces: PieceMap, start: BoardCell, target: BoardCell, piece: str) -> bool:
    kind = piece_kind(piece)
    if kind == "jiang" and start[1] == target[1] and _count_between(pieces, start, target) == 0:
        return True
    return _piece_can_move(pieces, start, target, piece)


def _horse_can_move(pieces: PieceMap, start: BoardCell, end: BoardCell) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if (abs(dx), abs(dy)) not in {(2, 1), (1, 2)}:
        return False
    if abs(dx) == 2:
        leg = (start[0] + _sign(dx), start[1])
    else:
        leg = (start[0], start[1] + _sign(dy))
    return leg not in pieces


def _elephant_can_move(pieces: PieceMap, start: BoardCell, end: BoardCell, side: str) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) != 2 or abs(dy) != 2:
        return False
    eye = (start[0] + _sign(dx), start[1] + _sign(dy))
    if eye in pieces:
        return False
    if side == "red":
        return end[0] <= 4
    return end[0] >= 5


def _advisor_can_move(start: BoardCell, end: BoardCell, side: str) -> bool:
    return abs(end[0] - start[0]) == 1 and abs(end[1] - start[1]) == 1 and _in_palace(end, side)


def _general_can_move(start: BoardCell, end: BoardCell, side: str) -> bool:
    return abs(end[0] - start[0]) + abs(end[1] - start[1]) == 1 and _in_palace(end, side)


def _soldier_can_move(start: BoardCell, end: BoardCell, side: str) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if side == "red":
        if dx == 1 and dy == 0:
            return True
        return start[0] >= 5 and dx == 0 and abs(dy) == 1
    if dx == -1 and dy == 0:
        return True
    return start[0] <= 4 and dx == 0 and abs(dy) == 1


def _in_palace(cell: BoardCell, side: str) -> bool:
    x_index, y_index = cell
    if y_index not in {3, 4, 5}:
        return False
    if side == "red":
        return 0 <= x_index <= 2
    return 7 <= x_index <= 9


def _moves_straight(start: BoardCell, end: BoardCell) -> bool:
    return start[0] == end[0] or start[1] == end[1]


def _count_between(pieces: PieceMap, start: BoardCell, end: BoardCell) -> int:
    if not _moves_straight(start, end):
        return -1

    dx = _sign(end[0] - start[0])
    dy = _sign(end[1] - start[1])
    cursor = (start[0] + dx, start[1] + dy)
    count = 0
    while cursor != end:
        if cursor in pieces:
            count += 1
        cursor = (cursor[0] + dx, cursor[1] + dy)
    return count


def _find_general(pieces: PieceMap, side: str) -> BoardCell | None:
    target_piece = "r_jiang" if side == "red" else "b_jiang"
    for cell, piece in pieces.items():
        if piece == target_piece:
            return cell
    return None


def _validate_cell(cell: BoardCell) -> None:
    try:
        validate_main_board_cell(cell)
    except ValueError as exc:
        raise XiangqiRuleError(str(exc)) from exc


def _validate_piece(piece: str) -> None:
    if piece not in KNOWN_PIECES:
        raise XiangqiRuleError(f"Unsupported piece label: {piece!r}")


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0

"""Xiangqi move validation with GhostVision piece labels."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from src.board_state import BoardCell
from src.coords import validate_main_board_cell

class Side(StrEnum):
    RED = "red"
    BLACK = "black"

    @property
    def label_prefix(self) -> str:
        return "r" if self is Side.RED else "b"

    @property
    def fen_side(self) -> str:
        return "w" if self is Side.RED else "b"


class PieceKind(StrEnum):
    JIANG = "jiang"
    SHI = "shi"
    XIANG = "xiang"
    MA = "ma"
    JU = "ju"
    PAO = "pao"
    ZU = "zu"


@dataclass(frozen=True, slots=True)
class Piece:
    side: Side
    kind: PieceKind

    @classmethod
    def from_label(cls, label: str) -> "Piece":
        try:
            raw_side, raw_kind = label.split("_", 1)
        except ValueError as exc:
            raise XiangqiRuleError(f"Unsupported piece label: {label!r}") from exc

        try:
            side = LABEL_PREFIX_TO_SIDE[raw_side]
            kind = PieceKind(raw_kind)
        except KeyError as exc:
            raise XiangqiRuleError(f"Unsupported piece label: {label!r}") from exc
        except ValueError as exc:
            raise XiangqiRuleError(f"Unsupported piece label: {label!r}") from exc
        return cls(side=side, kind=kind)

    @property
    def label(self) -> str:
        return f"{self.side.label_prefix}_{self.kind.value}"

    @property
    def fen_symbol(self) -> str:
        symbol = PIECE_KIND_TO_FEN[self.kind]
        return symbol.upper() if self.side is Side.RED else symbol

    def __str__(self) -> str:
        return self.label


LABEL_PREFIX_TO_SIDE = {
    "r": Side.RED,
    "b": Side.BLACK,
}

SIDE_ALIASES = {
    "red": Side.RED,
    "r": Side.RED,
    "w": Side.RED,
    "white": Side.RED,
    "black": Side.BLACK,
    "b": Side.BLACK,
}

PIECE_KIND_TO_FEN = {
    PieceKind.JIANG: "k",
    PieceKind.SHI: "a",
    PieceKind.XIANG: "b",
    PieceKind.MA: "n",
    PieceKind.JU: "r",
    PieceKind.PAO: "c",
    PieceKind.ZU: "p",
}

KNOWN_PIECES = frozenset(Piece(side, kind).label for side in Side for kind in PieceKind)

PieceLike = Piece | str
PieceMap = Mapping[BoardCell, PieceLike]
NormalizedPieceMap = dict[BoardCell, Piece]
MoveValidator = Callable[[NormalizedPieceMap, BoardCell, BoardCell, Piece], bool]

HORSE_LEG_OFFSETS = {
    (2, 1): (1, 0),
    (2, -1): (1, 0),
    (-2, 1): (-1, 0),
    (-2, -1): (-1, 0),
    (1, 2): (0, 1),
    (-1, 2): (0, 1),
    (1, -2): (0, -1),
    (-1, -2): (0, -1),
}

ELEPHANT_EYE_OFFSETS = {
    (2, 2): (1, 1),
    (2, -2): (1, -1),
    (-2, 2): (-1, 1),
    (-2, -2): (-1, -1),
}

class XiangqiRuleError(ValueError):
    """Raised when a move violates Xiangqi rules."""


@dataclass(frozen=True, slots=True)
class XiangqiTerminalStatus:
    game_over: bool
    winner: Side | None
    reason: str | None
    message: str


def normalize_side(side: str | Side) -> Side:
    """Normalize supported side aliases to ``red`` or ``black``."""

    if isinstance(side, Side):
        return side
    normalized = side.strip().lower()
    try:
        return SIDE_ALIASES[normalized]
    except KeyError as exc:
        raise XiangqiRuleError(f"Unknown Xiangqi side: {side!r}") from exc


def opposite_side(side: str | Side) -> Side:
    """Return the opposing side."""

    normalized = normalize_side(side)
    return Side.BLACK if normalized is Side.RED else Side.RED


def normalize_piece(piece: PieceLike) -> Piece:
    """Normalize a GhostVision label or Piece object to a Piece."""

    if isinstance(piece, Piece):
        return piece
    return Piece.from_label(piece)


def piece_side(piece: PieceLike) -> Side:
    """Return ``red`` or ``black`` for a GhostVision piece label."""

    return normalize_piece(piece).side


def piece_kind(piece: PieceLike) -> PieceKind:
    """Return the Xiangqi piece kind from a GhostVision piece label."""

    return normalize_piece(piece).kind


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

    board = _normalize_piece_map(pieces)

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
        raise XiangqiRuleError(f"Illegal {moving_piece.label} move from {start} to {end}.")

    after = _apply_move_to_board(board, start, end)
    if generals_face(after):
        raise XiangqiRuleError("Generals may not face each other.")
    if is_in_check(after, moving_side):
        raise XiangqiRuleError(f"Move leaves {moving_side} in check.")


def has_legal_move(pieces: PieceMap, side: str) -> bool:
    """Return whether ``side`` has at least one legal move."""

    normalized_side = normalize_side(side)
    board = _normalize_piece_map(pieces)
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

    board = _normalize_piece_map(pieces)
    moving_piece = board.pop(start)
    board.pop(end, None)
    board[end] = moving_piece
    return {cell: piece.label for cell, piece in board.items()}


def is_in_check(pieces: PieceMap, side: str) -> bool:
    """Return whether ``side`` is currently attacked."""

    normalized_side = normalize_side(side)
    board = _normalize_piece_map(pieces)
    general_cell = _find_general(board, normalized_side)
    if general_cell is None:
        return False

    enemy_side = opposite_side(normalized_side)
    for cell, piece in board.items():
        if piece_side(piece) == enemy_side and _piece_attacks(pieces, cell, general_cell, piece):
            return True
    return False


def generals_face(pieces: PieceMap) -> bool:
    """Return whether the two generals face on the same file without blockers."""

    board = _normalize_piece_map(pieces)
    red_general = _find_general(board, Side.RED)
    black_general = _find_general(board, Side.BLACK)
    if red_general is None or black_general is None:
        return False
    if red_general[1] != black_general[1]:
        return False
    return _count_between(board, red_general, black_general) == 0


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

    occupied = {cell: piece.fen_symbol for cell, piece in _normalize_piece_map(pieces).items()}

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

    fen_side = normalize_side(side_to_move).fen_side
    return f"{'/'.join(ranks)} {fen_side} - - {halfmove_clock} {fullmove_number}"


def standard_starting_pieces() -> dict[BoardCell, Piece]:
    """Return the standard initial Xiangqi position."""

    pieces: dict[BoardCell, Piece] = {}
    back_rank = [
        PieceKind.JU,
        PieceKind.MA,
        PieceKind.XIANG,
        PieceKind.SHI,
        PieceKind.JIANG,
        PieceKind.SHI,
        PieceKind.XIANG,
        PieceKind.MA,
        PieceKind.JU,
    ]
    for y_index, kind in enumerate(back_rank):
        pieces[(0, y_index)] = Piece(Side.RED, kind)
        pieces[(9, y_index)] = Piece(Side.BLACK, kind)
    for y_index in (1, 7):
        pieces[(2, y_index)] = Piece(Side.RED, PieceKind.PAO)
        pieces[(7, y_index)] = Piece(Side.BLACK, PieceKind.PAO)
    for y_index in (0, 2, 4, 6, 8):
        pieces[(3, y_index)] = Piece(Side.RED, PieceKind.ZU)
        pieces[(6, y_index)] = Piece(Side.BLACK, PieceKind.ZU)
    return pieces


def standard_starting_piece_labels() -> dict[BoardCell, str]:
    """Return the standard initial position using GhostVision piece labels."""

    return {cell: piece.label for cell, piece in standard_starting_pieces().items()}


def _piece_can_move(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    validator = PIECE_MOVE_VALIDATORS.get(piece.kind)
    return validator is not None and validator(pieces, start, end, piece)


def _piece_attacks(pieces: NormalizedPieceMap, start: BoardCell, target: BoardCell, piece: Piece) -> bool:
    if piece.kind is PieceKind.JIANG and start[1] == target[1] and _count_between(pieces, start, target) == 0:
        return True
    return _piece_can_move(pieces, start, target, piece)


def _rook_can_move(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    return _moves_straight(start, end) and _count_between(pieces, start, end) == 0


def _horse_rule(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    return _horse_can_move(pieces, start, end)


def _elephant_rule(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    return _elephant_can_move(pieces, start, end, piece.side)


def _advisor_rule(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    return _advisor_can_move(start, end, piece.side)


def _general_rule(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    return _general_can_move(start, end, piece.side)


def _cannon_can_move(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    target_occupied = end in pieces
    screen_count = _count_between(pieces, start, end)
    return _moves_straight(start, end) and screen_count == (1 if target_occupied else 0)


def _soldier_rule(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, piece: Piece) -> bool:
    return _soldier_can_move(start, end, piece.side)


PIECE_MOVE_VALIDATORS: dict[str, MoveValidator] = {
    PieceKind.JU: _rook_can_move,
    PieceKind.MA: _horse_rule,
    PieceKind.XIANG: _elephant_rule,
    PieceKind.SHI: _advisor_rule,
    PieceKind.JIANG: _general_rule,
    PieceKind.PAO: _cannon_can_move,
    PieceKind.ZU: _soldier_rule,
}


def _horse_can_move(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    leg_offset = HORSE_LEG_OFFSETS.get((dx, dy))
    if leg_offset is None:
        return False
    leg = (start[0] + leg_offset[0], start[1] + leg_offset[1])
    return leg not in pieces


def _elephant_can_move(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell, side: Side) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    eye_offset = ELEPHANT_EYE_OFFSETS.get((dx, dy))
    if eye_offset is None:
        return False
    eye = (start[0] + eye_offset[0], start[1] + eye_offset[1])
    if eye in pieces:
        return False
    if side is Side.RED:
        return end[0] <= 4
    return end[0] >= 5


def _advisor_can_move(start: BoardCell, end: BoardCell, side: Side) -> bool:
    return abs(end[0] - start[0]) == 1 and abs(end[1] - start[1]) == 1 and _in_palace(end, side)


def _general_can_move(start: BoardCell, end: BoardCell, side: Side) -> bool:
    return abs(end[0] - start[0]) + abs(end[1] - start[1]) == 1 and _in_palace(end, side)


def _soldier_can_move(start: BoardCell, end: BoardCell, side: Side) -> bool:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if side is Side.RED:
        if dx == 1 and dy == 0:
            return True
        return start[0] >= 5 and dx == 0 and abs(dy) == 1
    if dx == -1 and dy == 0:
        return True
    return start[0] <= 4 and dx == 0 and abs(dy) == 1


def _in_palace(cell: BoardCell, side: Side) -> bool:
    x_index, y_index = cell
    if y_index not in {3, 4, 5}:
        return False
    if side is Side.RED:
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


def _apply_move_to_board(pieces: NormalizedPieceMap, start: BoardCell, end: BoardCell) -> NormalizedPieceMap:
    board = dict(pieces)
    moving_piece = board.pop(start)
    board.pop(end, None)
    board[end] = moving_piece
    return board


def _normalize_piece_map(pieces: PieceMap) -> NormalizedPieceMap:
    board: NormalizedPieceMap = {}
    for cell, piece in pieces.items():
        _validate_cell(cell)
        if cell in board:
            raise ValueError(f"Duplicate board cell: {cell}")
        board[cell] = normalize_piece(piece)
    return board


def _find_general(pieces: NormalizedPieceMap, side: Side) -> BoardCell | None:
    target_piece = Piece(side, PieceKind.JIANG)
    for cell, piece in pieces.items():
        if piece == target_piece:
            return cell
    return None


def _validate_cell(cell: BoardCell) -> None:
    try:
        validate_main_board_cell(cell)
    except ValueError as exc:
        raise XiangqiRuleError(str(exc)) from exc


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0

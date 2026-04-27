"""In-memory session management for the Web console."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import time

from src.config import WebConfig
from src.xiangqi_rules import normalize_side, opposite_side


class AuthError(RuntimeError):
    """Raised when a login or session action is rejected."""


class SeatFullError(AuthError):
    """Raised when both player seats are already occupied."""


@dataclass(slots=True)
class WebSession:
    token: str
    user_id: str
    color: str
    created_at: float
    last_seen: float


class SessionManager:
    """Small shared-password auth layer with two player seats."""

    def __init__(self, config: WebConfig, *, now=time.time) -> None:
        self._config = config
        self._now = now
        self._sessions: dict[str, WebSession] = {}

    def login(self, password: str, *, expected_password: str | None = None) -> WebSession:
        self.cleanup()
        password_to_check = expected_password if expected_password is not None else self._config.password
        if password_to_check is not None and password != password_to_check:
            raise AuthError("Invalid password.")
        if len(self._sessions) >= self._config.max_users:
            raise SeatFullError("Player seats are full.")

        if not self._sessions:
            color = "red"
        else:
            occupied_color = next(iter(self._sessions.values())).color
            color = opposite_side(occupied_color)

        now = self._now()
        session = WebSession(
            token=secrets.token_urlsafe(24),
            user_id=self._next_user_id(),
            color=color,
            created_at=now,
            last_seen=now,
        )
        self._sessions[session.token] = session
        return session

    def get(self, token: str | None) -> WebSession:
        self.cleanup()
        if not token:
            raise AuthError("Missing session.")
        try:
            session = self._sessions[token]
        except KeyError as exc:
            raise AuthError("Invalid session.") from exc
        session.last_seen = self._now()
        return session

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def switch_color(self, token: str, color: str) -> WebSession:
        session = self.get(token)
        if len(self._sessions) > 1:
            raise AuthError("Color is locked while both seats are occupied.")
        session.color = normalize_side(color)
        return session

    def cleanup(self) -> None:
        now = self._now()
        expired = [
            token
            for token, session in self._sessions.items()
            if now - session.last_seen > self._config.session_timeout_s
        ]
        for token in expired:
            del self._sessions[token]

    def active_count(self) -> int:
        self.cleanup()
        return len(self._sessions)

    def public_user(self, token: str | None) -> dict[str, object] | None:
        try:
            session = self.get(token)
        except AuthError:
            return None
        return self.session_to_dict(session)

    def session_to_dict(self, session: WebSession) -> dict[str, object]:
        self.cleanup()
        return {
            "id": session.user_id,
            "color": session.color,
            "can_switch_color": len(self._sessions) == 1,
            "seat_count": len(self._sessions),
            "seat_limit": self._config.max_users,
        }

    def seats_to_dict(self) -> list[dict[str, object]]:
        self.cleanup()
        return [
            {
                "id": session.user_id,
                "color": session.color,
                "last_seen": session.last_seen,
            }
            for session in sorted(self._sessions.values(), key=lambda item: item.created_at)
        ]

    def _next_user_id(self) -> str:
        active_ids = {session.user_id for session in self._sessions.values()}
        for index in range(1, self._config.max_users + 1):
            candidate = f"U{index}"
            if candidate not in active_ids:
                return candidate
        raise SeatFullError("Player seats are full.")

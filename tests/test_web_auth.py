"""Tests for Web console session handling."""

from __future__ import annotations

import unittest

from src.config import WebConfig
from src.web.auth import AuthError, SeatFullError, SessionManager


class WebAuthTests(unittest.TestCase):
    def test_two_players_get_opposite_colors_and_third_is_rejected(self) -> None:
        config = WebConfig(password="pw")
        sessions = SessionManager(config)

        first = sessions.login("pw")
        second = sessions.login("pw")

        self.assertEqual(first.color, "red")
        self.assertEqual(second.color, "black")
        with self.assertRaises(SeatFullError):
            sessions.login("pw")

    def test_single_user_can_switch_color_but_two_users_lock_colors(self) -> None:
        config = WebConfig(password="pw")
        sessions = SessionManager(config)

        first = sessions.login("pw")
        sessions.switch_color(first.token, "black")
        self.assertEqual(first.color, "black")

        second = sessions.login("pw")
        self.assertEqual(second.color, "red")
        with self.assertRaisesRegex(AuthError, "locked"):
            sessions.switch_color(first.token, "red")

    def test_session_timeout_releases_seat(self) -> None:
        now = [100.0]
        config = WebConfig(password="pw", session_timeout_s=5.0)
        sessions = SessionManager(config, now=lambda: now[0])

        first = sessions.login("pw")
        self.assertEqual(sessions.active_count(), 1)

        now[0] = 106.0
        with self.assertRaises(AuthError):
            sessions.get(first.token)
        self.assertEqual(sessions.active_count(), 0)

    def test_rejects_wrong_password(self) -> None:
        sessions = SessionManager(WebConfig(password="pw"))

        with self.assertRaises(AuthError):
            sessions.login("bad")

    def test_reuses_released_user_id(self) -> None:
        sessions = SessionManager(WebConfig(password="pw"))

        first = sessions.login("pw")
        sessions.logout(first.token)
        second = sessions.login("pw")

        self.assertEqual(second.user_id, "U1")


if __name__ == "__main__":
    unittest.main()

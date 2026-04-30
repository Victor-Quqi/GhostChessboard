"""FastAPI application for the GhostChessboard Web console."""

import asyncio
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Callable

from src.board_state import BoardCell
from src.config import AppConfig
from src.coords import GridPoint, validate_grid_point, validate_main_board_cell
from src.web.auth import AuthError, SeatFullError, SessionManager, WebSession
from src.web.log_buffer import LogBuffer
from src.web.runtime import HardwareRuntime
from src.web.state import WebGameState, capture_slot_from_execution
from src.xiangqi_rules import XiangqiRuleError, opposite_side

STATIC_DIR = Path(__file__).with_name("static")
COOKIE_NAME = "ghost_session"


class CommandBusyError(RuntimeError):
    """Raised when a hardware command is already running."""


class BroadcastHub:
    """Small WebSocket fan-out helper."""

    def __init__(self) -> None:
        self._clients: set[object] = set()

    async def register(self, websocket) -> None:
        self._clients.add(websocket)

    async def unregister(self, websocket) -> None:
        self._clients.discard(websocket)

    async def send(self, payload: dict[str, object]) -> None:
        stale: list[object] = []
        for websocket in list(self._clients):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self._clients.discard(websocket)


class WebConsoleService:
    """Coordinates auth, game state, logs, AI, vision, and hardware commands."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        reset_cell = _reset_carriage_cell(config)
        self.state = WebGameState(carriage_cell=reset_cell)
        self.auth = SessionManager(config.web)
        self.logs = LogBuffer(config.web.log_limit)
        self.hardware = HardwareRuntime(config)
        self.broadcast = BroadcastHub()
        self._command_lock = asyncio.Lock()
        self._password = os.environ.get("GHOSTCHESSBOARD_WEB_PASSWORD", config.web.password)
        self._ai_engine_path = os.environ.get("GHOSTCHESSBOARD_PIKAFISH", config.web.ai_engine_path)
        self._ai_engine_available = self._check_ai_engine_available()
        self._state_path = _optional_path(os.environ.get("GHOSTCHESSBOARD_WEB_STATE_PATH", config.web.state_path))
        self._load_persisted_state()
        if self._password is None:
            self.logs.append("warn", "Web password is not configured; empty-password login is enabled.")
        if not self._ai_engine_available:
            self.logs.append("warn", "AI engine is not configured; set GHOSTCHESSBOARD_PIKAFISH or web.ai_engine_path.")
        self.logs.append("info", "Web console initialized.")

    def close(self) -> None:
        self.hardware.close()

    def login(self, password: str) -> WebSession:
        return self.auth.login(password, expected_password=self._password)

    def state_payload(self, token: str | None) -> dict[str, object]:
        user = self.auth.public_user(token)
        state = self.state.to_dict(user=user, seats=self.auth.seats_to_dict())
        state["ai"]["engine_available"] = self._ai_engine_available
        state["ai"]["engine_path"] = self._ai_engine_path
        return {
            "state": state,
            "logs": self.logs.to_list(),
        }

    async def emit_state(self) -> None:
        state = self.state.to_dict(seats=self.auth.seats_to_dict())
        state["ai"]["engine_available"] = self._ai_engine_available
        state["ai"]["engine_path"] = self._ai_engine_path
        await self.broadcast.send(
            {
                "type": "state",
                "state": state,
            }
        )

    async def emit_video_restart(self) -> None:
        await self.broadcast.send({"type": "video_restart"})

    async def log(self, level: str, message: str) -> None:
        entry = self.logs.append(level, message)
        await self.broadcast.send(
            {
                "type": "log",
                "entry": {
                    "index": entry.index,
                    "level": entry.level,
                    "message": entry.message,
                    "created_at": entry.created_at,
                },
            }
        )

    async def run_command(
        self,
        label: str,
        func: Callable[[], object],
        *,
        apply_result: Callable[[object], object] | None = None,
    ) -> object:
        if self._command_lock.locked():
            raise CommandBusyError("Hardware command channel is busy.")
        async with self._command_lock:
            self.state.set_busy(True)
            await self.log("info", f"{label} started.")
            await self.emit_state()
            try:
                result = await asyncio.to_thread(func)
                if apply_result is not None:
                    result = apply_result(result)
            except Exception as exc:
                self.hardware.safe_magnet_off()
                await self.log("error", f"{label} failed: {type(exc).__name__}: {exc}")
                raise
            finally:
                self.state.set_busy(False)
                await self.emit_state()
            await self.log("info", f"{label} completed.")
            return result

    async def manual_move(self, session: WebSession, start: BoardCell, end: BoardCell) -> dict[str, object]:
        self._assert_game_active()
        self._assert_turn_permission(session)
        try:
            self.state.validate_move(start, end, side_to_move=self.state.side_to_move)
        except XiangqiRuleError as exc:
            await self.log("warn", f"Rejected illegal Web move {start}->{end}: {exc}")
            raise

        def _execute() -> tuple[object, object]:
            return self.hardware.execute_board_move(
                self.state.board_state(),
                start=start,
                end=end,
            )

        def _commit(result: object) -> dict[str, object]:
            execution, final_state = result
            return self.state.commit_hardware_move(
                start,
                end,
                final_state,
                source="web",
                capture_slot=capture_slot_from_execution(execution),
            )

        move = await self.run_command("Web move", _execute, apply_result=_commit)
        self._persist_state()
        await self.log("info", f"Accepted Web move {start}->{end}.")
        await self.emit_state()
        return move

    async def ai_move(self, session: WebSession, *, depth: int | None, timeout_s: float | None) -> dict[str, object]:
        self._assert_game_active()
        self._assert_turn_permission(session)
        fen = self.state.fen()
        side = self.state.side_to_move
        resolved_depth = depth or self.config.web.default_ai_depth
        resolved_timeout = timeout_s or self.config.web.ai_timeout_s
        self.state.set_ai_status("searching")
        await self.emit_state()

        def _execute() -> tuple[str, BoardCell, BoardCell, object, object]:
            from src.engine import EngineError, get_best_move
            from src.turn import uci_to_cells

            try:
                best_move = get_best_move(
                    fen,
                    engine_path=self._ai_engine_path,
                    depth=resolved_depth,
                    timeout_s=resolved_timeout,
                )
            except EngineError as exc:
                terminal_message = _terminal_engine_error_message(exc, side)
                if terminal_message is not None:
                    winner, message = terminal_message
                    self.state.force_terminal_status(
                        winner=winner,
                        reason="checkmate",
                        message=message,
                    )
                    raise XiangqiRuleError(message) from exc
                raise
            start, end = uci_to_cells(best_move)
            self.state.validate_move(start, end, side_to_move=side)
            execution, final_state = self.hardware.execute_board_move(
                self.state.board_state(),
                start=start,
                end=end,
            )
            return best_move, start, end, execution, final_state

        def _commit(result: object) -> dict[str, object]:
            best_move, start, end, execution, final_state = result
            return self.state.commit_hardware_move(
                start,
                end,
                final_state,
                source="ai",
                best_move=best_move,
                capture_slot=capture_slot_from_execution(execution),
            )

        try:
            move = await self.run_command("AI move", _execute, apply_result=_commit)
        finally:
            self.state.set_ai_status("idle")
            await self.emit_state()

        self._persist_state()
        await self.log("info", f"AI chose {move['best_move']} for {side}.")
        await self.emit_state()
        return move

    async def vision_sync(self, *, force: bool = False) -> dict[str, object]:
        def _capture():
            from src.web.video import stop_all_camera_streamers
            from src.vision.probe import GhostVisionCliProbe

            stop_all_camera_streamers()
            probe = GhostVisionCliProbe(config=self.config.vision.probe)
            return probe.capture_snapshot()

        def _sync(result: object) -> object:
            return self.state.sync_from_snapshot(result, force=force)

        try:
            result = await self.run_command("Vision sync", _capture, apply_result=_sync)
        finally:
            await self.emit_video_restart()
        self._persist_state()
        level = "info" if result.status in {"initialized", "no_change", "legal_move"} else "warn"
        await self.log(level, f"Vision sync: {result.message}")
        await self.emit_state()
        return result.to_dict()

    async def reset_game(self) -> None:
        if self._command_lock.locked():
            raise CommandBusyError("Hardware command channel is busy.")
        reset_cell = _reset_carriage_cell(self.config)
        self.state.reset_game(carriage_cell=reset_cell)
        self._persist_state()
        await self.log("info", f"Game reset to the standard opening; carriage recorded at {reset_cell}.")
        await self.emit_state()

    async def jog(self, *, dx_mm: float, dy_mm: float, feed_mm_min: float | None) -> None:
        await self.run_command(
            "Jog",
            lambda: self.hardware.jog(dx_mm=dx_mm, dy_mm=dy_mm, feed_mm_min=feed_mm_min),
        )

    async def magnet(self, *, enabled: bool, pwm: int | None) -> None:
        await self.run_command(
            "Magnet on" if enabled else "Magnet off",
            lambda: self.hardware.magnet(enabled=enabled, pwm=pwm),
        )

    async def read_status(self) -> str:
        status = await self.run_command("GRBL status", self.hardware.status)
        assert isinstance(status, str)
        self.state.set_hardware_status(status)
        await self.emit_state()
        return status

    async def set_carriage(self, cell: GridPoint) -> None:
        self.state.set_carriage_cell(cell)
        self._persist_state()
        await self.log("info", f"Carriage position set to {cell}.")
        await self.emit_state()

    def seat_summary(self) -> str:
        seats = self.auth.seats_to_dict()
        if not seats:
            return "seats now: empty"
        summary = ", ".join(f"{seat['id']}={seat['color']}" for seat in seats)
        return f"seats now: {summary}"

    def _check_ai_engine_available(self) -> bool:
        if self._ai_engine_path:
            return Path(self._ai_engine_path).is_file()
        return shutil.which("pikafish") is not None

    def _load_persisted_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Persisted Web state must be a JSON object.")
            self.state.restore_state(raw)
            self.logs.append("info", f"Restored Web state from {self._state_path}.")
        except Exception as exc:
            self.logs.append("error", f"Could not restore Web state from {self._state_path}: {exc}")

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(self.state.export_state(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._state_path)

    def _assert_turn_permission(self, session: WebSession) -> None:
        if session.color != self.state.side_to_move:
            raise AuthError("It is the other player's turn.")

    def _assert_game_active(self) -> None:
        terminal = self.state.refresh_terminal_status()
        if terminal["game_over"]:
            raise XiangqiRuleError(str(terminal["message"]))


def create_app(config: AppConfig):
    try:
        from fastapi import Cookie, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse, StreamingResponse
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("FastAPI, Uvicorn, and Pydantic are required for the Web console.") from exc

    class LoginRequest(BaseModel):
        password: str = ""

    class SeatRequest(BaseModel):
        color: str

    class MoveRequest(BaseModel):
        start: list[int]
        end: list[int]

    class AiMoveRequest(BaseModel):
        depth: int | None = None
        timeout_s: float | None = None

    class VisionSyncRequest(BaseModel):
        force: bool = False

    class JogRequest(BaseModel):
        dx_mm: float = 0.0
        dy_mm: float = 0.0
        feed_mm_min: float | None = None

    class MagnetRequest(BaseModel):
        state: str
        pwm: int | None = None

    class CarriageRequest(BaseModel):
        cell: list[int] | None = None
        reset: bool = False

    app = FastAPI(title="GhostChessboard Web Console")
    service = WebConsoleService(config)
    app.state.web_service = service

    def _session(token: str | None) -> WebSession:
        try:
            return service.auth.get(token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def _cell(raw: list[int]) -> BoardCell:
        try:
            if len(raw) != 2:
                raise ValueError("Cell must contain two values.")
            cell = (int(raw[0]), int(raw[1]))
            validate_main_board_cell(cell)
            return cell
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _grid_cell(raw: list[int]) -> GridPoint:
        try:
            if len(raw) != 2:
                raise ValueError("Cell must contain two values.")
            cell = (int(raw[0]), int(raw[1]))
            validate_grid_point(cell)
            return cell
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _handle_command_error(exc: Exception) -> None:
        if isinstance(exc, CommandBusyError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if isinstance(exc, AuthError):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if isinstance(exc, XiangqiRuleError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        service.close()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/assets/app.css")
    async def css() -> Response:
        return Response(
            (STATIC_DIR / "app.css").read_text(encoding="utf-8"),
            media_type="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/app.js")
    async def js() -> Response:
        return Response(
            (STATIC_DIR / "app.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/login")
    async def login(request: LoginRequest, response: Response) -> dict[str, object]:
        try:
            session = service.login(request.password)
        except SeatFullError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        response.set_cookie(COOKIE_NAME, session.token, httponly=True, samesite="lax")
        await service.log("info", f"{session.user_id} joined as {session.color}; {service.seat_summary()}.")
        await service.emit_state()
        return {"user": service.auth.session_to_dict(session)}

    @app.post("/api/logout")
    async def logout(response: Response, ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        try:
            session = service.auth.get(ghost_session)
            label = session.user_id
        except AuthError:
            label = "User"
        service.auth.logout(ghost_session)
        response.delete_cookie(COOKIE_NAME)
        await service.log("info", f"{label} logged out; {service.seat_summary()}.")
        await service.emit_state()
        return {"ok": True}

    @app.get("/api/state")
    async def state(ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        _session(ghost_session)
        return service.state_payload(ghost_session)

    @app.post("/api/seat")
    async def seat(request: SeatRequest, ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        try:
            session = service.auth.switch_color(_session(ghost_session).token, request.color)
        except AuthError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        await service.log("info", f"{session.user_id} switched to {session.color}; {service.seat_summary()}.")
        await service.emit_state()
        return {"user": service.auth.session_to_dict(session)}

    @app.post("/api/move")
    async def move(request: MoveRequest, ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        session = _session(ghost_session)
        try:
            move_result = await service.manual_move(session, _cell(request.start), _cell(request.end))
        except Exception as exc:
            await _handle_command_error(exc)
        return {"move": move_result, **service.state_payload(ghost_session)}

    @app.post("/api/ai-move")
    async def ai_move(request: AiMoveRequest, ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        session = _session(ghost_session)
        try:
            move_result = await service.ai_move(session, depth=request.depth, timeout_s=request.timeout_s)
        except Exception as exc:
            await _handle_command_error(exc)
        return {"move": move_result, **service.state_payload(ghost_session)}

    @app.post("/api/vision/sync")
    async def vision_sync(
        request: VisionSyncRequest,
        ghost_session: str | None = Cookie(default=None),
    ) -> dict[str, object]:
        _session(ghost_session)
        try:
            result = await service.vision_sync(force=request.force)
        except Exception as exc:
            await _handle_command_error(exc)
        return {"sync": result, **service.state_payload(ghost_session)}

    @app.post("/api/game/reset")
    async def reset_game(ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        _session(ghost_session)
        try:
            await service.reset_game()
        except Exception as exc:
            await _handle_command_error(exc)
        return service.state_payload(ghost_session)

    @app.post("/api/jog")
    async def jog(request: JogRequest, ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        _session(ghost_session)
        try:
            await service.jog(dx_mm=request.dx_mm, dy_mm=request.dy_mm, feed_mm_min=request.feed_mm_min)
        except Exception as exc:
            await _handle_command_error(exc)
        return service.state_payload(ghost_session)

    @app.post("/api/magnet")
    async def magnet(request: MagnetRequest, ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        _session(ghost_session)
        state = request.state.strip().lower()
        if state not in {"on", "off"}:
            raise HTTPException(status_code=400, detail="Magnet state must be 'on' or 'off'.")
        try:
            await service.magnet(enabled=state == "on", pwm=request.pwm)
        except Exception as exc:
            await _handle_command_error(exc)
        return service.state_payload(ghost_session)

    @app.get("/api/grbl/status")
    @app.post("/api/grbl/status")
    async def grbl_status(ghost_session: str | None = Cookie(default=None)) -> dict[str, object]:
        _session(ghost_session)
        try:
            status = await service.read_status()
        except Exception as exc:
            await _handle_command_error(exc)
        return {"status": status, **service.state_payload(ghost_session)}

    @app.post("/api/carriage")
    async def carriage(
        request: CarriageRequest,
        ghost_session: str | None = Cookie(default=None),
    ) -> dict[str, object]:
        _session(ghost_session)
        if request.reset:
            cell = _reset_carriage_cell(config)
        elif request.cell is not None:
            cell = _grid_cell(request.cell)
        else:
            raise HTTPException(status_code=400, detail="Provide cell or reset=true.")
        await service.set_carriage(cell)
        return service.state_payload(ghost_session)

    @app.get("/api/video.mjpg")
    async def video(ghost_session: str | None = Cookie(default=None)):
        _session(ghost_session)
        try:
            from src.web.video import mjpeg_frames

            return StreamingResponse(
                mjpeg_frames(config.web),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        token = websocket.cookies.get(COOKIE_NAME)
        try:
            service.auth.get(token)
        except AuthError:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await service.broadcast.register(websocket)
        try:
            await websocket.send_json(service.state_payload(token))
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await service.broadcast.unregister(websocket)

    return app


def run_web_app(config: AppConfig, *, host: str | None = None, port: int | None = None) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Uvicorn is required for the Web console.") from exc

    resolved_host = host or config.web.host
    resolved_port = port or config.web.port
    _print_web_access_urls(resolved_host, resolved_port)
    uvicorn.run(
        create_app(config),
        host=resolved_host,
        port=resolved_port,
    )


def _reset_carriage_cell(config: AppConfig) -> GridPoint:
    raw = config.web.reset_carriage_cell
    if len(raw) != 2:
        raise ValueError("config.web.reset_carriage_cell must contain two integers.")
    cell = (int(raw[0]), int(raw[1]))
    validate_grid_point(cell)
    return cell


def _optional_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    return Path(raw)


def _terminal_engine_error_message(exc: Exception, side_to_move: str) -> tuple[str, str] | None:
    text = str(exc).lower()
    if "king can be captured" not in text:
        return None
    loser = side_to_move
    winner = opposite_side(side_to_move)
    return winner, f"{loser} is checkmated; {winner} wins."


def _print_web_access_urls(host: str, port: int) -> None:
    print(f"GhostChessboard WebUI listening on {host}:{port}", flush=True)
    urls = _web_access_urls(host, port)
    if not urls:
        return
    print("Open from this network:", flush=True)
    for url in urls:
        print(f"  {url}", flush=True)


def _web_access_urls(host: str, port: int) -> list[str]:
    if host in {"0.0.0.0", "::", ""}:
        addresses = _local_ipv4_addresses()
        if not addresses:
            addresses = ["127.0.0.1"]
        return [f"http://{address}:{port}" for address in addresses]
    return [f"http://{host}:{port}"]


def _local_ipv4_addresses() -> list[str]:
    candidates: set[str] = set()
    candidates.update(_hostname_ipv4_addresses())
    candidates.update(_udp_probe_ipv4_addresses())
    candidates.update(_hostname_command_ipv4_addresses())
    return sorted(candidates, key=lambda item: tuple(int(part) for part in item.split(".")))


def _hostname_ipv4_addresses() -> set[str]:
    try:
        records = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return set()
    return {_clean_ipv4(record[4][0]) for record in records if _clean_ipv4(record[4][0])}


def _udp_probe_ipv4_addresses() -> set[str]:
    addresses: set[str] = set()
    for target in ("8.8.8.8", "1.1.1.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 80))
                address = _clean_ipv4(sock.getsockname()[0])
                if address:
                    addresses.add(address)
        except OSError:
            continue
    return addresses


def _hostname_command_ipv4_addresses() -> set[str]:
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    addresses: set[str] = set()
    for token in result.stdout.split():
        address = _clean_ipv4(token)
        if address:
            addresses.add(address)
    return addresses


def _clean_ipv4(raw: str) -> str | None:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback or address.is_link_local or address.is_unspecified:
        return None
    return str(address)

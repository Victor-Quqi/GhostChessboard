"""Process management for the GhostChessboard Web console."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import time
from typing import Iterable

try:
    import psutil
except ImportError:
    psutil = None


@dataclass(frozen=True)
class WebProcess:
    pid: int
    command: str
    source: str


@dataclass(frozen=True)
class WebProcessSearch:
    matches: tuple[WebProcess, ...]
    skipped: tuple[WebProcess, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.matches)

    def __iter__(self):
        return iter(self.matches)

    def __len__(self) -> int:
        return len(self.matches)


def pid_file_path(port: int) -> Path:
    return Path(__file__).resolve().parents[1] / f".ghostchessboard-web-{port}.pid"


def write_web_pid_file(port: int, *, pid: int | None = None) -> Path:
    path = pid_file_path(port)
    payload = {
        "pid": pid or os.getpid(),
        "port": port,
        "created_at": time.time(),
    }
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return path


def remove_web_pid_file(port: int, *, pid: int | None = None) -> None:
    path = pid_file_path(port)
    expected_pid = pid or os.getpid()
    recorded_pid = _read_pid_file(path)
    if recorded_pid is not None and recorded_pid != expected_pid:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def find_web_processes(port: int, allow_any_listener: bool = False) -> WebProcessSearch:
    listener_pids = _listening_pids(port)
    pid_file_process = _process_from_pid_file(port, listener_pids)
    if pid_file_process is not None:
        return WebProcessSearch(matches=(pid_file_process,))

    process_map = _processes_by_pid(listener_pids)
    matches: list[WebProcess] = []
    skipped: list[WebProcess] = []
    for pid in sorted(listener_pids):
        process = process_map.get(pid) or _process_from_pid(pid, source="port")
        if process is None:
            continue
        if allow_any_listener or _is_web_process_command(process.command):
            matches.append(process)
        else:
            skipped.append(process)
    return WebProcessSearch(matches=tuple(matches), skipped=tuple(skipped))


def stop_web_app(
    *,
    port: int,
    timeout_s: float = 5.0,
    force: bool = False,
    allow_any_listener: bool = False,
    dry_run: bool = False,
) -> None:
    search = find_web_processes(port, allow_any_listener=allow_any_listener)
    if not search.matches and not search.skipped:
        print(f"No process is listening on TCP port {port}.")
        return

    for process in search.skipped:
        print(f"Skipping PID {process.pid}: {_display_command(process)}")

    if not search.matches:
        print(f"No GhostChessboard Web process found on TCP port {port}.")
        print("Use --allow-any-listener if you intentionally want to stop the listener on that port.")
        raise SystemExit(2)

    for process in search.matches:
        label = _display_command(process)
        if dry_run:
            print(f"Would stop PID {process.pid}: {label}")
            continue

        print(f"Stopping PID {process.pid}: {label}")
        if _terminate_process(process.pid, timeout_s=timeout_s):
            remove_web_pid_file(port, pid=process.pid)
            print(f"Stopped PID {process.pid}.")
            continue

        if force and _kill_process(process.pid, timeout_s=timeout_s):
            remove_web_pid_file(port, pid=process.pid)
            print(f"Killed PID {process.pid}.")
            continue

        print(f"PID {process.pid} is still running.")
        raise SystemExit(1)


def _listening_pids(port: int) -> set[int]:
    ps = _require_psutil()
    pids: set[int] = set()
    try:
        connections = ps.net_connections(kind="tcp")
    except (ps.AccessDenied, ps.Error):
        return pids

    for connection in connections:
        if connection.status != ps.CONN_LISTEN or connection.pid is None:
            continue
        if _connection_port(connection.laddr) == port:
            pids.add(connection.pid)
    return pids


def _connection_port(local_address: object) -> int | None:
    if hasattr(local_address, "port"):
        return int(local_address.port)
    if isinstance(local_address, tuple) and len(local_address) >= 2:
        return int(local_address[1])
    return None


def _process_from_pid_file(port: int, listener_pids: set[int]) -> WebProcess | None:
    path = pid_file_path(port)
    pid = _read_pid_file(path)
    if pid is None:
        return None

    process = _process_from_pid(pid, source="pid-file")
    if process is None:
        _remove_stale_pid_file(path)
        return None

    if pid in listener_pids or _is_web_process_command(process.command):
        return process

    _remove_stale_pid_file(path)
    return None


def _read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return int(raw) if raw.isdigit() else None

    if isinstance(payload, dict):
        pid = payload.get("pid")
        if isinstance(pid, int):
            return pid
        if isinstance(pid, str) and pid.isdigit():
            return int(pid)
    if isinstance(payload, int):
        return payload
    return None


def _remove_stale_pid_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _processes_by_pid(pids: Iterable[int]) -> dict[int, WebProcess]:
    ps = _require_psutil()
    pending = set(pids)
    found: dict[int, WebProcess] = {}
    if not pending:
        return found

    try:
        for process in ps.process_iter(["pid", "name", "cmdline"]):
            pid = process.info.get("pid")
            if pid not in pending:
                continue
            found[int(pid)] = _web_process_from_info(process.info, source="port")
            pending.remove(int(pid))
            if not pending:
                break
    except ps.Error:
        return found
    return found


def _process_from_pid(pid: int, *, source: str) -> WebProcess | None:
    ps = _require_psutil()
    try:
        process = ps.Process(pid)
        info = process.as_dict(attrs=["pid", "name", "cmdline"])
    except ps.NoSuchProcess:
        return None
    except ps.AccessDenied:
        return WebProcess(pid=pid, command="", source=source)
    except ps.Error:
        return WebProcess(pid=pid, command="", source=source)
    return _web_process_from_info(info, source=source)


def _web_process_from_info(info: dict[str, object], *, source: str) -> WebProcess:
    pid = int(info["pid"])
    command = _command_from_info(info)
    return WebProcess(pid=pid, command=command, source=source)


def _command_from_info(info: dict[str, object]) -> str:
    cmdline = info.get("cmdline")
    if isinstance(cmdline, list) and cmdline:
        return " ".join(shlex.quote(str(part)) for part in cmdline)
    name = info.get("name")
    return str(name) if name else ""


def _is_web_process_command(command: str) -> bool:
    normalized = command.replace("\\", "/")
    lower = normalized.lower()
    try:
        raw_tokens = shlex.split(normalized, posix=False)
    except ValueError:
        raw_tokens = normalized.split()
    tokens = [token.strip("\"'").lower() for token in raw_tokens]
    command_names = {token.rsplit("/", 1)[-1].removesuffix(".exe") for token in tokens}
    has_web_arg = "web" in tokens
    return (
        ("src.cli" in lower and has_web_arg)
        or ("ghostchessboard" in command_names and has_web_arg)
        or ("ghostchessboard" in lower and "uvicorn" in lower)
        or ("ghostchessboard" in lower and "src.web.server" in lower)
    )


def _terminate_process(pid: int, *, timeout_s: float) -> bool:
    ps = _require_psutil()
    try:
        process = ps.Process(pid)
        process.terminate()
        process.wait(timeout=timeout_s)
    except ps.NoSuchProcess:
        return True
    except ps.TimeoutExpired:
        return False
    except ps.Error:
        return False
    return True


def _kill_process(pid: int, *, timeout_s: float) -> bool:
    ps = _require_psutil()
    try:
        process = ps.Process(pid)
        process.kill()
        process.wait(timeout=timeout_s)
    except ps.NoSuchProcess:
        return True
    except ps.TimeoutExpired:
        return False
    except ps.Error:
        return False
    return True


def _display_command(process: WebProcess) -> str:
    return process.command or "(command unavailable)"


def _require_psutil():
    if psutil is None:
        raise RuntimeError("psutil is required for web-stop; install requirements-web.txt.") from None
    return psutil

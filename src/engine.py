"""Minimal UCI engine wrapper for Xiangqi engines such as Pikafish."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import threading


class EngineError(RuntimeError):
    """Raised when the UCI engine cannot return a best move."""


def resolve_engine_command(engine_path: str | Path | None = None) -> tuple[list[str], Path | None]:
    """Resolve one engine executable together with a sensible working directory."""

    if engine_path is not None:
        explicit_path = Path(engine_path)
        return ([str(explicit_path)], explicit_path.parent)

    env_path = os.environ.get("GHOSTCHESSBOARD_PIKAFISH")
    if env_path:
        resolved = Path(env_path)
        return ([str(resolved)], resolved.parent)

    discovered = shutil.which("pikafish")
    if discovered is not None:
        return ([discovered], Path(discovered).resolve().parent)

    raise EngineError(
        "Could not find a Pikafish executable. Pass engine_path, set GHOSTCHESSBOARD_PIKAFISH, or add 'pikafish' to PATH."
    )


def get_best_move(
    fen: str,
    *,
    engine_path: str | Path | None = None,
    depth: int = 15,
    threads: int | None = None,
    hash_mb: int | None = None,
    timeout_s: float = 15.0,
    cwd: str | Path | None = None,
) -> str:
    """Run one UCI search and return the best move string.

    Uses ``Popen`` so we can wait for the engine's ``bestmove`` line before
    sending ``quit``. Passing the whole script in one go (as ``subprocess.run``
    does) races the engine: ``quit`` often arrives mid-search, which makes
    Pikafish terminate and emit whatever move was generated at depth 0.
    """

    if not fen.strip():
        raise ValueError("fen must be a non-empty string.")
    if depth < 1:
        raise ValueError(f"depth must be positive, got {depth}")
    if threads is not None and threads < 1:
        raise ValueError(f"threads must be positive when set, got {threads}")
    if hash_mb is not None and hash_mb < 1:
        raise ValueError(f"hash_mb must be positive when set, got {hash_mb}")
    if timeout_s <= 0:
        raise ValueError(f"timeout_s must be positive, got {timeout_s}")

    command, default_cwd = resolve_engine_command(engine_path)
    run_cwd = Path(cwd) if cwd is not None else default_cwd

    setup_commands = ["uci", "isready"]
    if threads is not None:
        setup_commands.append(f"setoption name Threads value {threads}")
    if hash_mb is not None:
        setup_commands.append(f"setoption name Hash value {hash_mb}")
    setup_commands.extend(
        [
            "ucinewgame",
            f"position fen {fen}",
            f"go depth {depth}",
        ]
    )

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(run_cwd) if run_cwd is not None else None,
        )
    except FileNotFoundError as exc:
        raise EngineError(f"Could not execute engine command: {command[0]}") from exc

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stderr_chunks: list[str] = []
    stdout_chunks: list[str] = []
    timed_out = False

    def _drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_chunks.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        for line in setup_commands:
            process.stdin.write(line + "\n")
        process.stdin.flush()

        best_move: str | None = None

        def _kill_on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            process.kill()

        deadline_thread = threading.Timer(timeout_s, _kill_on_timeout)
        deadline_thread.daemon = True
        deadline_thread.start()
        try:
            for raw_line in process.stdout:
                stdout_chunks.append(raw_line)
                line = raw_line.strip()
                if line.startswith("bestmove "):
                    tokens = line.split()
                    if len(tokens) >= 2 and tokens[1] != "(none)":
                        best_move = tokens[1]
                    break
        finally:
            deadline_thread.cancel()
    finally:
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.write("quit\n")
                process.stdin.flush()
                process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        stderr_thread.join(timeout=1.0)

    if best_move is None:
        stderr_text = "".join(stderr_chunks).strip()
        stdout_text = "".join(stdout_chunks).strip()
        engine_error_text = _engine_error_text(stdout_text, stderr_text)
        if timed_out:
            raise EngineError(f"Engine search timed out after {timeout_s} seconds.")
        if process.returncode not in {None, 0} and engine_error_text:
            raise EngineError(f"Engine exited with code {process.returncode}: {engine_error_text}")
        raise EngineError(engine_error_text or "Engine output did not contain a 'bestmove' line.")

    return best_move


def _engine_error_text(stdout_text: str, stderr_text: str) -> str:
    """Extract high-signal engine diagnostics for CLI users."""

    lines = [line.strip() for line in stdout_text.splitlines() + stderr_text.splitlines()]
    critical = [line for line in lines if "CRITICAL ERROR" in line or "Unsupported position" in line]
    if critical:
        return " ".join(critical)
    if stderr_text:
        return stderr_text
    return ""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ghostchessboard-engine")
    parser.add_argument("fen", help="Full Xiangqi FEN string.")
    parser.add_argument("--engine", type=Path, help="Optional engine executable path.")
    parser.add_argument("--depth", type=int, default=15, help="Search depth.")
    parser.add_argument("--threads", type=int, help="Optional engine thread count.")
    parser.add_argument("--hash-mb", type=int, help="Optional transposition-table size in MiB.")
    parser.add_argument("--timeout-s", type=float, default=15.0, help="Search timeout in seconds.")
    args = parser.parse_args(argv)

    print(
        get_best_move(
            args.fen,
            engine_path=args.engine,
            depth=args.depth,
            threads=args.threads,
            hash_mb=args.hash_mb,
            timeout_s=args.timeout_s,
        )
    )


if __name__ == "__main__":
    main()

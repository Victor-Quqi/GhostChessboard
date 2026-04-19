"""Minimal UCI engine wrapper for Xiangqi engines such as Pikafish."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess


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
    """Run one UCI search and return the best move string."""

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

    script_lines = ["uci", "isready"]
    if threads is not None:
        script_lines.append(f"setoption name Threads value {threads}")
    if hash_mb is not None:
        script_lines.append(f"setoption name Hash value {hash_mb}")
    script_lines.extend(
        [
            f"position fen {fen}",
            f"go depth {depth}",
            "quit",
        ]
    )
    script = "\n".join(script_lines) + "\n"

    try:
        completed = subprocess.run(
            command,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(run_cwd) if run_cwd is not None else None,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EngineError(f"Could not execute engine command: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"Engine search timed out after {timeout_s} seconds.") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        detail = stderr or (stdout_lines[-1] if stdout_lines else "")
        raise EngineError(detail or f"Engine exited with code {completed.returncode}.")

    for line in reversed(completed.stdout.splitlines()):
        if not line.startswith("bestmove "):
            continue
        tokens = line.split()
        if len(tokens) < 2 or tokens[1] == "(none)":
            raise EngineError(f"Engine returned no legal best move for FEN: {fen}")
        return tokens[1]

    raise EngineError("Engine output did not contain a 'bestmove' line.")


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

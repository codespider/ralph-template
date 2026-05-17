#!/usr/bin/env python3
"""Claude-only Ralph loop runner with cost accounting."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TextIO


BUDGET_REACHED_EXIT = 42
current_process: Optional[subprocess.Popen[str]] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def die(message: str) -> None:
    print(f"[ralph] FATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


def log(message: str) -> str:
    return f"[ralph] {message}"


def quote_cmd(parts: list[str]) -> str:
    return shlex.join(parts)


def append_line(handle: TextIO, line: str) -> None:
    print(line)
    handle.write(line + "\n")
    handle.flush()


def append_text(handle: TextIO, text: str) -> None:
    print(text, end="")
    handle.write(text)
    handle.flush()


@dataclass
class Config:
    repo_root: Path
    prompt_file: Path
    kernel_file: Path
    project_file: Path
    stop_file: Path
    log_dir: Path
    status_file: Path
    cost_ledger: Path
    cost_summary: Path
    cost_script: Path
    claude_bin: str
    model: str
    dangerous: bool
    claude_max_budget_usd: Optional[float]
    max_total_cost_usd: Optional[float]
    max_iter: int
    max_consecutive_failures: int
    max_consecutive_no_progress: int
    sleep_seconds: float
    dry_run: bool
    completion_phrase: str


def default_config() -> Config:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    return Config(
        repo_root=repo_root,
        prompt_file=Path(os.environ.get("RALPH_PROMPT_FILE", script_dir / "PROMPT.md")),
        kernel_file=Path(os.environ.get("RALPH_KERNEL_FILE", script_dir / "KERNEL.md")),
        project_file=Path(os.environ.get("RALPH_PROJECT_FILE", script_dir / "PROJECT.md")),
        stop_file=Path(os.environ.get("RALPH_STOP_FILE", script_dir / "STOP")),
        log_dir=Path(os.environ.get("RALPH_LOG_DIR", script_dir / "iterations")),
        status_file=Path(os.environ.get("RALPH_STATUS_FILE", script_dir / "RUN_STATUS")),
        cost_ledger=Path(os.environ.get("RALPH_COST_LEDGER", script_dir / "COSTS.jsonl")),
        cost_summary=Path(os.environ.get("RALPH_COST_SUMMARY", script_dir / "COSTS.md")),
        cost_script=Path(os.environ.get("RALPH_COST_SCRIPT", script_dir / "claude-cost-accounting.py")),
        claude_bin=os.environ.get("RALPH_CLAUDE_BIN", "claude"),
        model=os.environ.get("RALPH_MODEL", "claude-sonnet-4-6"),
        dangerous=env_bool("RALPH_ALLOW_DANGEROUS", False),
        claude_max_budget_usd=parse_optional_float(os.environ.get("RALPH_CLAUDE_MAX_BUDGET_USD")),
        max_total_cost_usd=parse_optional_float(os.environ.get("RALPH_MAX_TOTAL_COST_USD")),
        max_iter=int(os.environ.get("RALPH_MAX_ITER", "20")),
        max_consecutive_failures=int(os.environ.get("RALPH_MAX_CONSECUTIVE_FAILURES", "3")),
        max_consecutive_no_progress=int(os.environ.get("RALPH_MAX_CONSECUTIVE_NO_PROGRESS", "3")),
        sleep_seconds=float(os.environ.get("RALPH_SLEEP", "3")),
        dry_run=env_bool("RALPH_DRY_RUN", False),
        completion_phrase=os.environ.get("RALPH_COMPLETION_PHRASE", ""),
    )


def parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    parsed = float(value)
    if parsed < 0:
        die("cost values must be non-negative")
    return parsed


def parse_args() -> Config:
    cfg = default_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("positional_max", nargs="?", type=non_negative_int)
    parser.add_argument("--max", dest="max_iter", type=non_negative_int)
    parser.add_argument("--sleep", dest="sleep_seconds", type=non_negative_float)
    parser.add_argument("--prompt", dest="prompt_file", type=Path)
    parser.add_argument("--stop-file", dest="stop_file", type=Path)
    parser.add_argument("--log-dir", dest="log_dir", type=Path)
    parser.add_argument("--status-file", dest="status_file", type=Path)
    parser.add_argument("--cost-ledger", dest="cost_ledger", type=Path)
    parser.add_argument("--cost-summary", dest="cost_summary", type=Path)
    parser.add_argument("--cost-script", dest="cost_script", type=Path)
    parser.add_argument("--model", dest="model")
    parser.add_argument("--claude-bin", dest="claude_bin")
    parser.add_argument("--dangerous", dest="dangerous", action="store_true")
    parser.add_argument("--claude-max-budget", dest="claude_max_budget_usd", type=non_negative_float)
    parser.add_argument("--max-total-cost", dest="max_total_cost_usd", type=non_negative_float)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("--completion-phrase", dest="completion_phrase")

    args = parser.parse_args()
    for name, value in vars(args).items():
        if name == "positional_max":
            if value is not None:
                cfg.max_iter = value
            continue
        if value is not None:
            setattr(cfg, name, value)
    return cfg


def build_claude_cmd(cfg: Config) -> list[str]:
    cmd = [cfg.claude_bin, "-p", "--output-format", "json"]
    if cfg.model:
        cmd.extend(["--model", cfg.model])
    if cfg.claude_max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", f"{cfg.claude_max_budget_usd:g}"])
    if cfg.dangerous:
        cmd.append("--dangerously-skip-permissions")
    return cmd


def run_git(cfg: Config, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cfg.repo_root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    return completed.stdout


def git_snapshot(cfg: Config) -> str:
    inside = subprocess.run(
        ["git", "-C", str(cfg.repo_root), "rev-parse", "--is-inside-work-tree"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inside.returncode != 0:
        return "not-a-git-repo\n"
    return run_git(cfg, ["rev-parse", "HEAD"]) + run_git(cfg, ["status", "--porcelain=v1"])


def write_status(cfg: Config, state: str, iteration: int, detail: str) -> None:
    cfg.status_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.status_file.write_text(
        "\n".join(
            [
                f"state={state}",
                f"iteration={iteration}",
                f"detail={detail}",
                f"updated_at={utc_now()}",
                f"prompt_file={cfg.prompt_file}",
                f"stop_file={cfg.stop_file}",
                f"log_dir={cfg.log_dir}",
                f"claude_bin={cfg.claude_bin}",
                f"model={cfg.model}",
                f"cost_ledger={cfg.cost_ledger}",
                f"cost_summary={cfg.cost_summary}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def create_stop(cfg: Config, reason: str, runner_name: str) -> None:
    cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.stop_file.write_text(
        f"{reason}\n\nCreated by {runner_name} at {utc_now()}.\n",
        encoding="utf-8",
    )


def run_claude(
    cmd: list[str],
    prompt_file: Path,
    iteration_log: Path,
    session_handle: TextIO,
) -> int:
    global current_process

    with prompt_file.open("rb") as prompt, iteration_log.open("w", encoding="utf-8") as iter_handle:
        current_process = subprocess.Popen(
            cmd,
            stdin=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert current_process.stdout is not None
        for line in current_process.stdout:
            print(line, end="")
            iter_handle.write(line)
            session_handle.write(line)
        rc = current_process.wait()
        current_process = None
        iter_handle.flush()
        session_handle.flush()
        return rc


def record_cost(cfg: Config, iteration: int, rc: int, duration: int, iteration_log: Path, session_handle: TextIO) -> int:
    cmd = [
        sys.executable,
        str(cfg.cost_script),
        "append",
        "--log",
        str(iteration_log),
        "--ledger",
        str(cfg.cost_ledger),
        "--summary",
        str(cfg.cost_summary),
        "--iteration",
        str(iteration),
        "--model",
        cfg.model,
        "--exit-code",
        str(rc),
        "--duration-seconds",
        str(duration),
    ]
    if cfg.max_total_cost_usd is not None:
        cmd.extend(["--max-total-cost-usd", f"{cfg.max_total_cost_usd:g}"])

    completed = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    append_text(session_handle, completed.stdout)
    return completed.returncode


def handle_signal(cfg: Config, signum: int) -> None:
    global current_process
    if current_process is not None and current_process.poll() is None:
        current_process.terminate()
        try:
            current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            current_process.kill()
    write_status(cfg, "interrupted", 0, f"signal {signum} received")
    raise SystemExit(130)


def validate_config(cfg: Config) -> None:
    if cfg.kernel_file.exists() and cfg.project_file.exists():
        print(f"[ralph] building {cfg.prompt_file} from {cfg.kernel_file} + {cfg.project_file}")
        cfg.prompt_file.write_bytes(cfg.kernel_file.read_bytes() + cfg.project_file.read_bytes())
    if not cfg.prompt_file.exists():
        die(
            f"prompt file not found: {cfg.prompt_file} "
            f"(and KERNEL.md + PROJECT.md were not both present)"
        )
    if not cfg.cost_script.exists():
        die(f"cost script not found: {cfg.cost_script}")
    if not cfg.dry_run and shutil.which(cfg.claude_bin) is None:
        die(f"claude binary not found on PATH: {cfg.claude_bin}")
    cfg.log_dir.mkdir(parents=True, exist_ok=True)


def main() -> int:
    cfg = parse_args()
    validate_config(cfg)
    cmd = build_claude_cmd(cfg)

    signal.signal(signal.SIGINT, lambda signum, frame: handle_signal(cfg, signum))
    signal.signal(signal.SIGTERM, lambda signum, frame: handle_signal(cfg, signum))

    run_id = utc_stamp()
    session_log = cfg.log_dir / f"session-{run_id}.log"

    os.chdir(cfg.repo_root)

    with session_log.open("a", encoding="utf-8") as session_handle:
        for line in [
            log(f"repo: {cfg.repo_root}"),
            log(f"prompt: {cfg.prompt_file}"),
            log(f"stop file: {cfg.stop_file}"),
            log(f"logs: {cfg.log_dir}"),
            log(f"status: {cfg.status_file}"),
            log(f"claude: {quote_cmd(cmd)}"),
            log(f"cost ledger: {cfg.cost_ledger}"),
            log(f"cost summary: {cfg.cost_summary}"),
            log(f"claude max budget: {cfg.claude_max_budget_usd if cfg.claude_max_budget_usd is not None else 'none'}"),
            log(f"total cost cap: {cfg.max_total_cost_usd if cfg.max_total_cost_usd is not None else 'none'}"),
            log(f"max_iter: {cfg.max_iter}"),
            log(f"max_consecutive_failures: {cfg.max_consecutive_failures}"),
            log(f"max_consecutive_no_progress: {cfg.max_consecutive_no_progress}"),
            log(f"sleep: {cfg.sleep_seconds:g}s"),
            log(f"dangerous: {1 if cfg.dangerous else 0}"),
            log(f"dry_run: {1 if cfg.dry_run else 0}"),
            log(f"started_at: {utc_now()}"),
            "",
        ]:
            append_line(session_handle, line)

        iteration = 0
        consecutive_failures = 0
        consecutive_no_progress = 0

        while True:
            if cfg.stop_file.exists():
                append_line(session_handle, log(f"STOP file detected at {cfg.stop_file}; exiting"))
                write_status(cfg, "stopped", iteration, "STOP file detected")
                break

            if cfg.max_iter != 0 and iteration >= cfg.max_iter:
                append_line(session_handle, log(f"hit max iterations: {cfg.max_iter}"))
                write_status(cfg, "max_iter", iteration, "max iterations reached")
                break

            iteration += 1
            stamp = utc_stamp()
            iteration_log = cfg.log_dir / f"iter-{iteration:03d}-{stamp}.log"
            started = time.monotonic()
            before = git_snapshot(cfg)
            write_status(cfg, "running", iteration, "iteration started")

            for line in [
                "==================================================================",
                log(f"iteration {iteration} started at {utc_now()}"),
                log(f"log: {iteration_log}"),
                "==================================================================",
            ]:
                append_line(session_handle, line)

            if cfg.dry_run:
                dry_text = log(f"DRY_RUN=1; would run: {quote_cmd(cmd)} < {cfg.prompt_file}") + "\n\n"
                iteration_log.write_text(dry_text, encoding="utf-8")
                append_text(session_handle, dry_text)
                rc = 0
            else:
                rc = run_claude(cmd, cfg.prompt_file, iteration_log, session_handle)

            duration = int(time.monotonic() - started)
            after = git_snapshot(cfg)
            if before == after:
                consecutive_no_progress += 1
            else:
                consecutive_no_progress = 0

            if rc == 0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1

            append_line(session_handle, "")
            append_line(
                session_handle,
                log(
                    f"iteration {iteration} exit_code={rc} duration={duration}s "
                    f"no_progress_streak={consecutive_no_progress} failure_streak={consecutive_failures}"
                ),
            )
            append_line(session_handle, "")

            cost_rc = record_cost(cfg, iteration, rc, duration, iteration_log, session_handle)
            write_status(cfg, "sleeping", iteration, f"rc={rc} duration={duration}s")

            if cost_rc == BUDGET_REACHED_EXIT:
                create_stop(
                    cfg,
                    f"ESCALATE: cumulative Claude cost reached RALPH_MAX_TOTAL_COST_USD={cfg.max_total_cost_usd:g}",
                    "ralph.py",
                )
                append_line(session_handle, log("cost limit reached; STOP created"))
                break
            if cost_rc != 0:
                append_line(session_handle, log(f"cost accounting failed with exit code {cost_rc}; continuing"))

            if cfg.completion_phrase and cfg.completion_phrase in iteration_log.read_text(
                encoding="utf-8", errors="replace"
            ):
                create_stop(cfg, f"DONE: completion phrase observed: {cfg.completion_phrase}", "ralph.py")
                append_line(session_handle, log("completion phrase observed; STOP created"))
                break

            if cfg.max_consecutive_failures != 0 and consecutive_failures >= cfg.max_consecutive_failures:
                create_stop(cfg, f"ESCALATE: {consecutive_failures} consecutive agent failures", "ralph.py")
                append_line(session_handle, log("failure limit reached; STOP created"))
                break

            if (
                cfg.max_consecutive_no_progress != 0
                and consecutive_no_progress >= cfg.max_consecutive_no_progress
            ):
                create_stop(
                    cfg,
                    f"ESCALATE: {consecutive_no_progress} consecutive no-progress iterations",
                    "ralph.py",
                )
                append_line(session_handle, log("no-progress limit reached; STOP created"))
                break

            time.sleep(cfg.sleep_seconds)

        write_status(cfg, "done", iteration, "loop exited")
        append_line(session_handle, log(f"finished after {iteration} iteration(s) at {utc_now()}"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

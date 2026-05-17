#!/usr/bin/env bash
# Claude-only Ralph loop runner.
#
# Start a fresh Claude process, feed it PROMPT.md, persist state in files,
# and repeat until STOP appears or a safety limit fires.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROMPT_FILE="${RALPH_PROMPT_FILE:-$SCRIPT_DIR/PROMPT.md}"
KERNEL_FILE="${RALPH_KERNEL_FILE:-$SCRIPT_DIR/KERNEL.md}"
PROJECT_FILE="${RALPH_PROJECT_FILE:-$SCRIPT_DIR/PROJECT.md}"
STOP_FILE="${RALPH_STOP_FILE:-$SCRIPT_DIR/STOP}"
LOG_DIR="${RALPH_LOG_DIR:-$SCRIPT_DIR/iterations}"
STATUS_FILE="${RALPH_STATUS_FILE:-$SCRIPT_DIR/RUN_STATUS}"
COST_LEDGER="${RALPH_COST_LEDGER:-$SCRIPT_DIR/COSTS.jsonl}"
COST_SUMMARY="${RALPH_COST_SUMMARY:-$SCRIPT_DIR/COSTS.md}"
COST_SCRIPT="${RALPH_COST_SCRIPT:-$SCRIPT_DIR/claude-cost-accounting.py}"
PYTHON_BIN="${RALPH_PYTHON_BIN:-}"

CLAUDE_BIN="${RALPH_CLAUDE_BIN:-claude}"
MODEL="${RALPH_MODEL:-claude-sonnet-4-6}"
ALLOW_DANGEROUS="${RALPH_ALLOW_DANGEROUS:-0}"
CLAUDE_MAX_BUDGET_USD="${RALPH_CLAUDE_MAX_BUDGET_USD:-}"
MAX_TOTAL_COST_USD="${RALPH_MAX_TOTAL_COST_USD:-}"

MAX_ITER="${RALPH_MAX_ITER:-20}"
MAX_CONSECUTIVE_FAILURES="${RALPH_MAX_CONSECUTIVE_FAILURES:-3}"
MAX_CONSECUTIVE_NO_PROGRESS="${RALPH_MAX_CONSECUTIVE_NO_PROGRESS:-3}"
SLEEP_BETWEEN="${RALPH_SLEEP:-3}"
DRY_RUN="${RALPH_DRY_RUN:-0}"
COMPLETION_PHRASE="${RALPH_COMPLETION_PHRASE:-}"

usage() {
  cat <<'USAGE'
Usage:
  ralph/ralph.sh [options]
  ralph/ralph.sh 10

Options:
  --max N                 Maximum iterations. Use 0 for unlimited.
  --sleep N               Seconds between iterations.
  --prompt FILE           Prompt file to feed to the agent.
  --stop-file FILE        STOP sentinel path.
  --log-dir DIR           Iteration log directory.
  --status-file FILE      Current run status path.
  --cost-ledger FILE      JSONL cost ledger path.
  --cost-summary FILE     Markdown cost summary path.
  --python-bin PATH       Python executable for cost accounting.
  --model MODEL           Model passed to Claude.
  --claude-bin PATH       Claude executable. Default: claude.
  --dangerous             Add Claude permission-bypass flag.
  --claude-max-budget USD Per-iteration Claude Code budget.
  --max-total-cost USD    Stop after cumulative estimated cost reaches USD.
  --dry-run               Print what would run without invoking the agent.
  --completion-phrase TXT Create STOP if TXT appears in iteration output.
  --help                  Show this help.

Environment variables mirror the option names with RALPH_ prefixes.
USAGE
}

die() {
  echo "[ralph] FATAL: $*" >&2
  exit 1
}

log() {
  printf '[ralph] %s\n' "$*"
}

quote_cmd() {
  local part
  for part in "$@"; do
    printf '%q ' "$part"
  done
}

write_status() {
  local state="$1"
  local iteration="$2"
  local detail="$3"
  {
    echo "state=$state"
    echo "iteration=$iteration"
    echo "detail=$detail"
    echo "updated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "prompt_file=$PROMPT_FILE"
    echo "stop_file=$STOP_FILE"
    echo "log_dir=$LOG_DIR"
    echo "claude_bin=$CLAUDE_BIN"
    echo "model=$MODEL"
    echo "cost_ledger=$COST_LEDGER"
    echo "cost_summary=$COST_SUMMARY"
    echo "python_bin=$PYTHON_BIN"
  } > "$STATUS_FILE"
}

snapshot_git() {
  local target="$1"
  if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    {
      git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true
      git -C "$REPO_ROOT" status --porcelain=v1 2>/dev/null || true
    } > "$target"
  else
    echo "not-a-git-repo" > "$target"
  fi
}

build_claude_cmd() {
  CLAUDE_CMD=("$CLAUDE_BIN" "-p" "--output-format" "json")
  if [ -n "$MODEL" ]; then
    CLAUDE_CMD+=("--model" "$MODEL")
  fi
  if [ -n "$CLAUDE_MAX_BUDGET_USD" ]; then
    CLAUDE_CMD+=("--max-budget-usd" "$CLAUDE_MAX_BUDGET_USD")
  fi
  if [ "$ALLOW_DANGEROUS" = "1" ]; then
    CLAUDE_CMD+=("--dangerously-skip-permissions")
  fi
}

choose_python() {
  if [ -n "$PYTHON_BIN" ]; then
    "$PYTHON_BIN" -c 'import sys' >/dev/null 2>&1 || die "python binary is not usable: $PYTHON_BIN"
    return
  fi
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
    PYTHON_BIN="python3"
    return
  fi
  if [ -x /usr/bin/python3 ] && /usr/bin/python3 -c 'import sys' >/dev/null 2>&1; then
    PYTHON_BIN="/usr/bin/python3"
    return
  fi
  die "no usable python3 found; set RALPH_PYTHON_BIN"
}

create_stop() {
  local reason="$1"
  {
    echo "$reason"
    echo
    echo "Created by ralph.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ)."
  } > "$STOP_FILE"
}

on_signal() {
  log "signal received; exiting"
  write_status "interrupted" "${iter:-0}" "signal received"
  exit 130
}

while [ $# -gt 0 ]; do
  case "$1" in
    --max)
      MAX_ITER="${2:-}"
      shift 2
      ;;
    --sleep)
      SLEEP_BETWEEN="${2:-}"
      shift 2
      ;;
    --prompt)
      PROMPT_FILE="${2:-}"
      shift 2
      ;;
    --stop-file)
      STOP_FILE="${2:-}"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="${2:-}"
      shift 2
      ;;
    --status-file)
      STATUS_FILE="${2:-}"
      shift 2
      ;;
    --cost-ledger)
      COST_LEDGER="${2:-}"
      shift 2
      ;;
    --cost-summary)
      COST_SUMMARY="${2:-}"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --claude-bin)
      CLAUDE_BIN="${2:-}"
      shift 2
      ;;
    --dangerous)
      ALLOW_DANGEROUS=1
      shift
      ;;
    --claude-max-budget)
      CLAUDE_MAX_BUDGET_USD="${2:-}"
      shift 2
      ;;
    --max-total-cost)
      MAX_TOTAL_COST_USD="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --completion-phrase)
      COMPLETION_PHRASE="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    ''|*[!0-9]*)
      die "unknown argument: $1"
      ;;
    *)
      MAX_ITER="$1"
      shift
      ;;
  esac
done

[[ "$MAX_ITER" =~ ^[0-9]+$ ]] || die "MAX_ITER must be a non-negative integer"
[[ "$MAX_CONSECUTIVE_FAILURES" =~ ^[0-9]+$ ]] || die "MAX_CONSECUTIVE_FAILURES must be a non-negative integer"
[[ "$MAX_CONSECUTIVE_NO_PROGRESS" =~ ^[0-9]+$ ]] || die "MAX_CONSECUTIVE_NO_PROGRESS must be a non-negative integer"
[[ "$SLEEP_BETWEEN" =~ ^[0-9]+$ ]] || die "SLEEP_BETWEEN must be a non-negative integer"
if [ -n "$MAX_TOTAL_COST_USD" ] && ! [[ "$MAX_TOTAL_COST_USD" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  die "MAX_TOTAL_COST_USD must be a non-negative decimal"
fi
if [ -n "$CLAUDE_MAX_BUDGET_USD" ] && ! [[ "$CLAUDE_MAX_BUDGET_USD" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  die "CLAUDE_MAX_BUDGET_USD must be a non-negative decimal"
fi

if [ -f "$KERNEL_FILE" ] && [ -f "$PROJECT_FILE" ]; then
  log "building $PROMPT_FILE from $KERNEL_FILE + $PROJECT_FILE"
  cat "$KERNEL_FILE" "$PROJECT_FILE" > "$PROMPT_FILE"
fi

[ -f "$PROMPT_FILE" ] || die "prompt file not found: $PROMPT_FILE (and KERNEL.md + PROJECT.md were not both present at $SCRIPT_DIR)"
[ -f "$COST_SCRIPT" ] || die "cost script not found: $COST_SCRIPT"
mkdir -p "$LOG_DIR"

choose_python

if [ "$DRY_RUN" != "1" ] && ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  die "claude binary not found on PATH: $CLAUDE_BIN"
fi

build_claude_cmd
trap on_signal INT TERM

cd "$REPO_ROOT" || die "cannot cd to repo root: $REPO_ROOT"

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
session_log="$LOG_DIR/session-$run_id.log"
tmp_before="$(mktemp "${TMPDIR:-/tmp}/ralph-before.XXXXXX")"
tmp_after="$(mktemp "${TMPDIR:-/tmp}/ralph-after.XXXXXX")"
trap 'rm -f "$tmp_before" "$tmp_after"' EXIT

{
  log "repo: $REPO_ROOT"
  log "prompt: $PROMPT_FILE"
  log "stop file: $STOP_FILE"
  log "logs: $LOG_DIR"
  log "status: $STATUS_FILE"
  log "claude: $(quote_cmd "${CLAUDE_CMD[@]}")"
  log "cost ledger: $COST_LEDGER"
  log "cost summary: $COST_SUMMARY"
  log "python: $PYTHON_BIN"
  log "claude max budget: ${CLAUDE_MAX_BUDGET_USD:-none}"
  log "total cost cap: ${MAX_TOTAL_COST_USD:-none}"
  log "max_iter: $MAX_ITER"
  log "max_consecutive_failures: $MAX_CONSECUTIVE_FAILURES"
  log "max_consecutive_no_progress: $MAX_CONSECUTIVE_NO_PROGRESS"
  log "sleep: ${SLEEP_BETWEEN}s"
  log "dangerous: $ALLOW_DANGEROUS"
  log "dry_run: $DRY_RUN"
  log "started_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
} | tee -a "$session_log"

iter=0
consecutive_failures=0
consecutive_no_progress=0

while true; do
  if [ -f "$STOP_FILE" ]; then
    log "STOP file detected at $STOP_FILE; exiting" | tee -a "$session_log"
    write_status "stopped" "$iter" "STOP file detected"
    break
  fi

  if [ "$MAX_ITER" -ne 0 ] && [ "$iter" -ge "$MAX_ITER" ]; then
    log "hit max iterations: $MAX_ITER" | tee -a "$session_log"
    write_status "max_iter" "$iter" "max iterations reached"
    break
  fi

  iter=$((iter + 1))
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  iter_log="$LOG_DIR/iter-$(printf '%03d' "$iter")-$ts.log"
  started_epoch="$(date +%s)"

  snapshot_git "$tmp_before"
  write_status "running" "$iter" "iteration started"

  {
    echo "=================================================================="
    log "iteration $iter started at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    log "log: $iter_log"
    echo "=================================================================="
  } | tee -a "$session_log"

  if [ "$DRY_RUN" = "1" ]; then
    {
      log "DRY_RUN=1; would run: $(quote_cmd "${CLAUDE_CMD[@]}") < $PROMPT_FILE"
      echo
    } | tee "$iter_log" | tee -a "$session_log" >/dev/null
    rc=0
  else
    set +e
    "${CLAUDE_CMD[@]}" < "$PROMPT_FILE" 2>&1 | tee "$iter_log"
    rc=${PIPESTATUS[0]}
    set -e
    cat "$iter_log" >> "$session_log"
  fi

  ended_epoch="$(date +%s)"
  duration=$((ended_epoch - started_epoch))
  snapshot_git "$tmp_after"

  if cmp -s "$tmp_before" "$tmp_after"; then
    consecutive_no_progress=$((consecutive_no_progress + 1))
  else
    consecutive_no_progress=0
  fi

  if [ "$rc" -eq 0 ]; then
    consecutive_failures=0
  else
    consecutive_failures=$((consecutive_failures + 1))
  fi

  {
    echo
    log "iteration $iter exit_code=$rc duration=${duration}s no_progress_streak=$consecutive_no_progress failure_streak=$consecutive_failures"
    echo
  } | tee -a "$session_log"

  cost_rc=0
  cost_args=(
    "$COST_SCRIPT" append
    --log "$iter_log"
    --ledger "$COST_LEDGER"
    --summary "$COST_SUMMARY"
    --iteration "$iter"
    --model "$MODEL"
    --exit-code "$rc"
    --duration-seconds "$duration"
  )
  if [ -n "$MAX_TOTAL_COST_USD" ]; then
    cost_args+=(--max-total-cost-usd "$MAX_TOTAL_COST_USD")
  fi
  "$PYTHON_BIN" "${cost_args[@]}" 2>&1 | tee -a "$session_log" || cost_rc=${PIPESTATUS[0]}

  write_status "sleeping" "$iter" "rc=$rc duration=${duration}s"

  if [ "$cost_rc" -eq 42 ]; then
    create_stop "ESCALATE: cumulative Claude cost reached RALPH_MAX_TOTAL_COST_USD=$MAX_TOTAL_COST_USD"
    log "cost limit reached; STOP created" | tee -a "$session_log"
    break
  elif [ "$cost_rc" -ne 0 ]; then
    log "cost accounting failed with exit code $cost_rc; continuing" | tee -a "$session_log"
  fi

  if [ -n "$COMPLETION_PHRASE" ] && rg -F "$COMPLETION_PHRASE" "$iter_log" >/dev/null 2>&1; then
    create_stop "DONE: completion phrase observed: $COMPLETION_PHRASE"
    log "completion phrase observed; STOP created" | tee -a "$session_log"
    break
  fi

  if [ "$MAX_CONSECUTIVE_FAILURES" -ne 0 ] &&
     [ "$consecutive_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
    create_stop "ESCALATE: $consecutive_failures consecutive agent failures"
    log "failure limit reached; STOP created" | tee -a "$session_log"
    break
  fi

  if [ "$MAX_CONSECUTIVE_NO_PROGRESS" -ne 0 ] &&
     [ "$consecutive_no_progress" -ge "$MAX_CONSECUTIVE_NO_PROGRESS" ]; then
    create_stop "ESCALATE: $consecutive_no_progress consecutive no-progress iterations"
    log "no-progress limit reached; STOP created" | tee -a "$session_log"
    break
  fi

  sleep "$SLEEP_BETWEEN"
done

write_status "done" "$iter" "loop exited"
log "finished after $iter iteration(s) at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$session_log"

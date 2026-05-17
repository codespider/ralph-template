#!/usr/bin/env python3
"""Extract Claude Code invocation cost into a local Ralph ledger."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


BUDGET_REACHED_EXIT = 42
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json_objects(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        pass

    objects: list[Any] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            objects.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return objects


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def first_string(objects: list[Any], key: str) -> Optional[str]:
    for obj in reversed(objects):
        for item in walk(obj):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def extract_total_cost(objects: list[Any]) -> tuple[float, bool]:
    candidates: list[float] = []
    for obj in objects:
        for item in walk(obj):
            cost = as_float(item.get("total_cost_usd"))
            if cost is not None:
                candidates.append(cost)
    if not candidates:
        return 0.0, False
    return candidates[-1], True


def extract_model_costs(objects: list[Any]) -> Any:
    for obj in reversed(objects):
        for item in walk(obj):
            for key in ("model_costs", "cost_breakdown", "costs_by_model"):
                value = item.get(key)
                if isinstance(value, (dict, list)):
                    return value
    return None


def extract_tokens(objects: list[Any]) -> dict[str, int]:
    tokens = {field: 0 for field in TOKEN_FIELDS}
    for obj in objects:
        for item in walk(obj):
            for field in TOKEN_FIELDS:
                value = item.get(field)
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    tokens[field] += value
    return tokens


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def cumulative_cost(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        value = as_float(row.get("total_cost_usd"))
        if value is not None:
            total += value
    return total


def write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    total = cumulative_cost(rows)
    costed = [row for row in rows if row.get("cost_found")]
    lines = [
        "# Ralph Claude Cost Summary",
        "",
        f"- Updated at: `{utc_now()}`",
        f"- Iterations recorded: `{len(rows)}`",
        f"- Iterations with Claude cost metadata: `{len(costed)}`",
        f"- Estimated total cost: `${total:.6f}`",
        "",
        "| Iteration | Model | Exit | Duration | Cost | Cost Metadata | Log |",
        "|---:|---|---:|---:|---:|---|---|",
    ]

    for row in rows[-50:]:
        cost = as_float(row.get("total_cost_usd")) or 0.0
        cost_found = "yes" if row.get("cost_found") else "no"
        lines.append(
            "| {iteration} | `{model}` | {exit_code} | {duration}s | ${cost:.6f} | {cost_found} | `{log_path}` |".format(
                iteration=row.get("iteration", ""),
                model=row.get("model", ""),
                exit_code=row.get("exit_code", ""),
                duration=row.get("duration_seconds", ""),
                cost=cost,
                cost_found=cost_found,
                log_path=row.get("log_path", ""),
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_entry(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    ledger_path = Path(args.ledger)
    summary_path = Path(args.summary)

    objects = load_json_objects(log_path)
    total_cost, cost_found = extract_total_cost(objects)
    rows = read_ledger(ledger_path)

    entry = {
        "recorded_at": utc_now(),
        "iteration": args.iteration,
        "model": args.model,
        "exit_code": args.exit_code,
        "duration_seconds": args.duration_seconds,
        "log_path": str(log_path),
        "session_id": first_string(objects, "session_id"),
        "total_cost_usd": total_cost,
        "cost_found": cost_found,
        "model_costs": extract_model_costs(objects),
        "tokens": extract_tokens(objects),
    }

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")

    rows.append(entry)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_summary(summary_path, rows)

    cumulative = cumulative_cost(rows)
    print(
        "cost iteration=${:.6f} cumulative=${:.6f} metadata={}".format(
            total_cost,
            cumulative,
            "yes" if cost_found else "no",
        )
    )

    if args.max_total_cost_usd is not None and cumulative >= args.max_total_cost_usd:
        print(
            "cost budget reached: cumulative=${:.6f} limit=${:.6f}".format(
                cumulative,
                args.max_total_cost_usd,
            ),
            file=sys.stderr,
        )
        return BUDGET_REACHED_EXIT

    return 0


def print_total(args: argparse.Namespace) -> int:
    rows = read_ledger(Path(args.ledger))
    print(f"{cumulative_cost(rows):.6f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append", help="append one iteration to the cost ledger")
    append_parser.add_argument("--log", required=True)
    append_parser.add_argument("--ledger", required=True)
    append_parser.add_argument("--summary", required=True)
    append_parser.add_argument("--iteration", required=True, type=int)
    append_parser.add_argument("--model", required=True)
    append_parser.add_argument("--exit-code", required=True, type=int)
    append_parser.add_argument("--duration-seconds", required=True, type=int)
    append_parser.add_argument("--max-total-cost-usd", type=float)
    append_parser.set_defaults(func=append_entry)

    total_parser = subparsers.add_parser("total", help="print cumulative ledger cost")
    total_parser.add_argument("--ledger", required=True)
    total_parser.set_defaults(func=print_total)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

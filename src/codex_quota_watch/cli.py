from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .core import poll_once
from .notifier import dispatch_pending, launch_windows_alert
from .source import run_source, unwrap_posts
from .store import Store


def default_state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "codex-quota-watch"
    return Path.home() / ".local" / "state" / "codex-quota-watch"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-quota-watch", description="Watch author thsottiaux for Codex quota reset updates.")
    parser.add_argument("--state-dir", default=str(default_state_dir()), help="SQLite state, event files, and receipts directory")
    commands = parser.add_subparsers(dest="command", required=True)
    def add_state_option(command: argparse.ArgumentParser) -> None:
        command.add_argument("--state-dir", default=argparse.SUPPRESS, help="SQLite state, event files, and receipts directory")
    init = commands.add_parser("init", help="create local state directory and database")
    add_state_option(init)
    poll = commands.add_parser("poll", help="read one source snapshot and update state")
    watch = commands.add_parser("watch", help="poll repeatedly")
    add_state_option(poll)
    add_state_option(watch)
    for command in (poll, watch):
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--input", help="JSON file containing posts or an OpenCLI JSON envelope")
        source.add_argument("--source-command-json", help="JSON argv array to run, for example '[\"path/to/source.exe\",\"--json\"]'")
        command.add_argument("--source-timeout", type=float, default=30)
        command.add_argument("--dry-run", action="store_true", help="write validated event JSON but do not open a popup")
    watch.add_argument("--interval", type=float, default=10800, help="seconds between polls (default: 10800)")
    status = commands.add_parser("status", help="show pending and acknowledged alerts")
    add_state_option(status)
    ack = commands.add_parser("ack", help="acknowledge an alert explicitly by ID")
    add_state_option(ack)
    ack.add_argument("id")
    return parser


def _load_posts(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.input:
        try:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise RuntimeError(f"cannot read input file: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"input file is not valid JSON: {exc}") from exc
        return unwrap_posts(payload)
    try:
        command = json.loads(args.source_command_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--source-command-json must be a JSON argv array: {exc}") from exc
    if not isinstance(command, list):
        raise ValueError("--source-command-json must decode to an argv array")
    return run_source(command, timeout=args.source_timeout)


def _poll(args: argparse.Namespace, store: Store) -> dict[str, Any]:
    posts = _load_posts(args)
    created = poll_once(store, posts)
    outcomes = dispatch_pending(store, Path(args.state_dir) / "receipts", notifier=lambda alert, receipt: launch_windows_alert(alert, receipt, dry_run=args.dry_run))
    return {"new_alerts": created, "notifications": outcomes, "pending": len(store.pending())}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    state_dir = Path(args.state_dir).expanduser()
    if args.command == "init":
        state_dir.mkdir(parents=True, exist_ok=True)
        Store(state_dir / "state.sqlite3")
        (state_dir / "receipts").mkdir(exist_ok=True)
        print(json.dumps({"state_dir": str(state_dir.resolve()), "initialized": True}, ensure_ascii=False))
        return 0
    store = Store(state_dir / "state.sqlite3")
    if args.command == "ack":
        if not store.ack(args.id):
            print(f"No unacknowledged alert with ID {args.id}", file=sys.stderr)
            return 1
        print(json.dumps({"acknowledged": args.id}))
        return 0
    if args.command == "status":
        print(json.dumps({"pending": store.pending(), "alerts": store.all_alerts()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "poll":
        try:
            print(json.dumps(_poll(args, store), ensure_ascii=False, indent=2))
            return 0
        except (ValueError, RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "watch":
        if args.interval < 1:
            print("--interval must be at least 1 second", file=sys.stderr)
            return 2
        while True:
            try:
                print(json.dumps(_poll(args, store), ensure_ascii=False), flush=True)
            except (ValueError, RuntimeError, OSError) as exc:
                print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
            time.sleep(args.interval)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

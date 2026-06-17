import argparse
import json
import os
from typing import Any

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.core import Project, Worker
from dev_tools.sandbox.reset_db import reset_database
from dev_tools.sandbox.seed_runner import (
    STATUS_PATH,
    replay_scenario,
    seed_sandbox_data,
)


def _assert_development_env() -> None:
    if os.environ.get("ENV") != "development":
        raise RuntimeError("Dev CLI blocked outside development environment")


def _print_json_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _clear_last_status() -> None:
    if STATUS_PATH.exists():
        STATUS_PATH.unlink()


def reset_command(_args: argparse.Namespace) -> None:
    _assert_development_env()
    reset_database(verbose=True)
    _clear_last_status()


def seed_command(args: argparse.Namespace) -> None:
    _assert_development_env()
    print(f"[SEED] Loading scenario setup: {args.scenario}")
    summary = seed_sandbox_data(args.scenario)
    print("[OK] Seed complete")
    print(
        "[SEED] Created or updated "
        f"{len(summary['entity_registry'])} entities in project {summary['project']['id']}"
    )


def sandbox_command(args: argparse.Namespace) -> None:
    _assert_development_env()
    reset_database(verbose=True)
    _clear_last_status()
    print(f"[SEED] Loading scenario setup: {args.scenario}")
    seed_sandbox_data(args.scenario)
    print("[SCENARIO] Replaying natural language inputs...")
    summary = replay_scenario(args.scenario)
    print("[OK] Sandbox complete")
    print("[SUMMARY] Final sandbox state:")
    _print_json_summary(summary)


def replay_command(args: argparse.Namespace) -> None:
    _assert_development_env()
    print(f"[SCENARIO] Replaying natural language inputs: {args.scenario}")
    summary = replay_scenario(args.scenario)
    print("[OK] Replay complete")
    print("[SUMMARY] Final scenario state:")
    _print_json_summary(summary)


def status_command(_args: argparse.Namespace) -> None:
    _assert_development_env()
    with SessionLocal() as db:
        project_count = db.scalar(select(func.count(Project.id)))
        worker_count = db.scalar(select(func.count(Worker.id)))

    last_status = None
    if STATUS_PATH.exists():
        last_status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))

    print("[STATUS] Current development database state:")
    _print_json_summary(
        {
            "project_count": project_count,
            "worker_count": worker_count,
            "last_sandbox_run": last_status,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yara", description="Yara development CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser("reset", help="Drop and recreate local dev DB schema")
    reset_parser.set_defaults(func=reset_command)

    seed_parser = subparsers.add_parser("seed", help="Insert deterministic sandbox setup data")
    seed_parser.add_argument("--scenario", default="villa_project_basic")
    seed_parser.set_defaults(func=seed_command)

    sandbox_parser = subparsers.add_parser("sandbox", help="Reset, seed, replay, and summarize")
    sandbox_parser.add_argument("--scenario", default="villa_project_basic")
    sandbox_parser.set_defaults(func=sandbox_command)

    replay_parser = subparsers.add_parser("replay", help="Replay scenario messages without reset")
    replay_parser.add_argument("--scenario", default="villa_project_basic")
    replay_parser.set_defaults(func=replay_command)

    status_parser = subparsers.add_parser("status", help="Show current dev DB status")
    status_parser.set_defaults(func=status_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

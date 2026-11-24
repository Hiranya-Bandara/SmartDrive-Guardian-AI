"""Command-line entry point.

In Phase 1 this provides environment diagnostics and database/settings maintenance. From
Phase 2 the default command launches the desktop application; the maintenance commands remain.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from smartdrive import APP_NAME, APP_TAGLINE, __version__
from smartdrive.app import ApplicationContext, bootstrap, shutdown
from smartdrive.config.constants import SAFETY_DISCLAIMER
from smartdrive.utils.exceptions import SmartDriveError

EXIT_OK = 0
EXIT_FAILURE = 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smartdrive", description=f"{APP_NAME} — {APP_TAGLINE}")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--home",
        type=Path,
        help="Store all application data under this folder (portable mode). "
        "Overrides the SMARTDRIVE_HOME environment variable.",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("info", help="Show version, data locations and database status (default).")

    db = commands.add_parser("db", help="Database maintenance.").add_subparsers(
        dest="db_command", required=True
    )
    db.add_parser("check", help="Run an integrity check on the database.")
    backup = db.add_parser("backup", help="Write a verified backup copy of the database.")
    backup.add_argument("--output", type=Path, help="Backup file path (default: backups folder).")
    restore = db.add_parser("restore", help="Replace the database with a backup file.")
    restore.add_argument("source", type=Path)
    restore.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    settings = commands.add_parser("settings", help="Show or reset preferences.").add_subparsers(
        dest="settings_command", required=True
    )
    settings.add_parser("show", help="Print current preferences as JSON.")
    settings.add_parser("reset", help="Restore default preferences.")
    return parser


def _info(ctx: ApplicationContext) -> None:
    db = ctx.database
    lines = [
        f"{APP_NAME} {__version__}",
        APP_TAGLINE,
        "",
        f"Data folder:     {ctx.paths.data_dir}",
        f"Database:        {db.path}",
        f"Schema revision: {db.current_revision()} (latest {db.head_revision()})",
        f"Settings file:   {ctx.paths.settings_file}",
        f"Log file:        {ctx.paths.log_file}",
        f"Backups:         {ctx.paths.backup_dir}",
        f"Theme:           {ctx.settings.appearance.theme.value}",
        f"Units:           {ctx.settings.units.system.value}",
        "",
        SAFETY_DISCLAIMER,
    ]
    print("\n".join(lines))


def _run(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    command = args.command or "info"
    if command == "info":
        _info(ctx)
    elif command == "db":
        if args.db_command == "check":
            ok = ctx.database.integrity_check()
            print("Integrity check passed." if ok else "Integrity check FAILED.")
            return EXIT_OK if ok else EXIT_FAILURE
        if args.db_command == "backup":
            keep = ctx.settings.retention.keep_backups
            target = (
                ctx.database.backup(args.output)
                if args.output
                else ctx.database.backup_to_directory(ctx.paths.backup_dir, keep=keep)
            )
            print(f"Backup written: {target}")
        elif args.db_command == "restore":
            if not args.yes:
                answer = input(f"Replace the current database with {args.source}? [y/N] ")
                if answer.strip().lower() not in {"y", "yes"}:
                    print("Restore cancelled.")
                    return EXIT_OK
            safety = ctx.database.restore(
                args.source,
                safety_backup_dir=ctx.paths.backup_dir,
                keep=ctx.settings.retention.keep_backups,
            )
            print(f"Database restored. Previous database saved as: {safety}")
    elif command == "settings":
        if args.settings_command == "show":
            print(json.dumps(ctx.settings.model_dump(mode="json"), indent=2))
        else:
            ctx.settings = ctx.settings_store.reset()
            print("Preferences reset to defaults.")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        ctx = bootstrap(home=args.home)
    except SmartDriveError as exc:
        print(f"Error: {exc.user_message}\n{exc}", file=sys.stderr)
        return EXIT_FAILURE
    try:
        return _run(args, ctx)
    except SmartDriveError as exc:
        print(f"Error: {exc.user_message}\n{exc}", file=sys.stderr)
        return EXIT_FAILURE
    finally:
        shutdown(ctx)

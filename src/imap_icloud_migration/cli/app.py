"""Typer CLI for the iCloud IMAP to Gmail migration tool."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import typer

from imap_icloud_migration.config.settings import AppSettings, load_settings
from imap_icloud_migration.gmail.client import GmailClient
from imap_icloud_migration.models.state import MessageStatus
from imap_icloud_migration.models.types import SummaryReport
from imap_icloud_migration.pipeline.orchestrator import MigrationOrchestrator
from imap_icloud_migration.storage.state_db import StateDb
from imap_icloud_migration.utils.fingerprint import sha256_file_hex
from imap_icloud_migration.utils.logging import configure_logging

logger = logging.getLogger(__name__)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Deterministic iCloud IMAP → Gmail migration with .eml evidence + sqlite checkpoints.",
)


def load_app_settings(*, env_file: Path | None) -> AppSettings:
    """Load application settings from the environment and optional .env file.

    Args:
        env_file: Optional path to a .env file to load in addition to environment variables.

    Returns:
        Validated application settings.
    """
    return load_settings(env_file=env_file)


@app.command("migrate")
def migrate_cmd(
    *,
    env_file: Path | None = typer.Option(
        default=None,
        exists=True,
        dir_okay=False,
        help="Optional path to a .env file (in addition to environment variables).",
    ),
    dry_run: bool = typer.Option(
        default=False,
        help="Fetch and write .eml evidence + update sqlite state, but skip Gmail ingestion.",
    ),
    reset: bool = typer.Option(
        default=False,
        help="Reset folder checkpoints and status of skipped/failed messages to retry migration.",
    ),
) -> None:
    """Run the migration pipeline.

    Args:
        env_file: Optional path to a .env file to load configuration from.
        dry_run: Whether to skip Gmail ingestion and only write evidence/state.
        reset: Whether to reset skipped/failed messages and folder checkpoints first.
    """
    settings = load_app_settings(env_file=env_file)
    configure_logging(settings=settings.logging)

    if settings.imap is None:
        typer.echo(
            "Missing IMAP settings. Set at least MIG_IMAP__USERNAME and MIG_IMAP__APP_PASSWORD.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not dry_run and settings.gmail is None:
        typer.echo(
            "Missing Gmail settings. Set "
            "MIG_GMAIL__TARGET_USER_EMAIL and MIG_GMAIL__CREDENTIALS_FILE.",
            err=True,
        )
        raise typer.Exit(code=2)

    orchestrator = MigrationOrchestrator(settings=settings)
    try:
        asyncio.run(orchestrator.run(dry_run=dry_run, reset=reset))
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None


@app.command("gmail-auth")
def gmail_auth_cmd(
    *,
    env_file: Path | None = typer.Option(
        default=None,
        exists=True,
        dir_okay=False,
        help="Optional path to a .env file (in addition to environment variables).",
    ),
) -> None:
    """Run the Gmail OAuth flow and verify mailbox access.

    Args:
        env_file: Optional path to a .env file to load configuration from.
    """
    settings = load_app_settings(env_file=env_file)
    configure_logging(settings=settings.logging)

    if settings.gmail is None:
        typer.echo(
            "Missing Gmail settings. Set "
            "MIG_GMAIL__TARGET_USER_EMAIL and MIG_GMAIL__CREDENTIALS_FILE.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        service = GmailClient.from_settings(settings.gmail).service
        profile = service.users().getProfile(userId=settings.gmail.target_user_email).execute()
    except ValueError as exc:
        # Usually config/token file issues.
        logger.error("Gmail auth configuration error: %s", exc)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    except Exception as exc:
        logger.exception("Gmail auth failed")
        typer.echo(f"Gmail auth failed: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if not isinstance(profile, dict) or "emailAddress" not in profile:
        typer.echo(f"Unexpected Gmail profile response: {profile!r}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Gmail OAuth OK for: {profile['emailAddress']}")
    if "messagesTotal" in profile:
        typer.echo(f"messagesTotal: {profile.get('messagesTotal')}")
    if "threadsTotal" in profile:
        typer.echo(f"threadsTotal: {profile.get('threadsTotal')}")


@app.command("verify")
def verify_cmd(
    *,
    env_file: Path | None = typer.Option(
        default=None,
        exists=True,
        dir_okay=False,
        help="Optional path to a .env file (in addition to environment variables).",
    ),
) -> None:
    """Verify evidence+DB consistency and emit a summary report.

    Args:
        env_file: Optional path to a .env file to load configuration from.
    """
    settings = load_app_settings(env_file=env_file)
    db = StateDb(sqlite_path=settings.storage.sqlite_path)
    db.init_schema()

    mismatches = 0
    checked = 0
    for row in db.iter_messages(status=MessageStatus.downloaded):
        if row.eml_path is None or row.eml_sha256 is None:
            continue
        checked += 1
        if not row.eml_path.exists():
            mismatches += 1
            continue
        actual = sha256_file_hex(row.eml_path)
        if actual != row.eml_sha256:
            mismatches += 1

    counts = db.counts_by_status()
    db.close()

    typer.echo(f"Messages checked: {checked}")
    typer.echo(f"Evidence mismatches: {mismatches}")
    for status, count in sorted(counts.items(), key=lambda kv: kv[0].value):
        typer.echo(f"{status.value}: {count}")

    raise typer.Exit(code=1 if mismatches else 0)


@app.command("report")
def report_cmd(
    *,
    env_file: Path | None = typer.Option(
        default=None,
        exists=True,
        dir_okay=False,
        help="Optional path to a .env file (in addition to environment variables).",
    ),
) -> None:
    """Export migration reports (JSON) from sqlite state.

    Args:
        env_file: Optional path to a .env file to load configuration from.
    """
    settings = load_app_settings(env_file=env_file)
    db = StateDb(sqlite_path=settings.storage.sqlite_path)
    db.init_schema()

    mismatches = 0
    for row in db.iter_messages(status=MessageStatus.downloaded):
        if row.eml_path is None or row.eml_sha256 is None:
            continue
        if not row.eml_path.exists():
            mismatches += 1
            continue
        if sha256_file_hex(row.eml_path) != row.eml_sha256:
            mismatches += 1

    counts = {status.value: count for status, count in db.counts_by_status().items()}
    db.close()

    report = SummaryReport(
        created_at=datetime.now(tz=UTC),
        sqlite_path=str(settings.storage.sqlite_path),
        counts=counts,
        evidence_mismatches=mismatches,
    )

    settings.storage.reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.storage.reports_dir / f"summary-{report.created_at.isoformat()}.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote {out_path}")

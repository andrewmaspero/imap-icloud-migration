"""Tests for sqlite state database operations."""

from __future__ import annotations

from pathlib import Path

from imap_icloud_migration.models.state import MessageStatus
from imap_icloud_migration.storage.state_db import StateDb


def test_state_db_transitions(tmp_path: Path) -> None:
    """State transitions should mark messages imported and count correctly."""
    db_path = tmp_path / "state.sqlite3"
    db = StateDb(sqlite_path=db_path)
    db.init_schema()

    db.upsert_folder(name="INBOX", uidvalidity=123, last_uid_seen=10)

    row = db.upsert_message_discovered(
        folder="INBOX",
        uid=11,
        uidvalidity=123,
        message_id_norm="<a@b>",
        fingerprint="fp",
        size_bytes=42,
    )
    assert row.status == MessageStatus.discovered

    db.mark_downloaded(message_id=row.id, eml_path=tmp_path / "a.eml", eml_sha256="deadbeef")
    db.mark_imported(
        message_id=row.id,
        gmail_message_id="gid",
        gmail_thread_id=None,
        label_ids=["LBL"],
    )

    counts = db.counts_by_status()
    assert counts[MessageStatus.imported] == 1
    db.close()


def test_reset_skipped_and_failed(tmp_path: Path) -> None:
    """reset_skipped_and_failed should reset statuses and folder checkpoints."""
    db_path = tmp_path / "state.sqlite3"
    db = StateDb(sqlite_path=db_path)
    db.init_schema()

    db.upsert_folder(name="INBOX", uidvalidity=123, last_uid_seen=10)

    row = db.upsert_message_discovered(
        folder="INBOX",
        uid=11,
        uidvalidity=123,
        message_id_norm="<a@b>",
        fingerprint="fp",
        size_bytes=42,
    )
    db.mark_failed(message_id=row.id, error="boom")

    reset_count = db.reset_skipped_and_failed()
    assert reset_count == 1

    updated = db.get_folder(name="INBOX")
    assert updated is not None
    assert updated.last_uid_seen == 0
    db.close()

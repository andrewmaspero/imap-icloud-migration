"""SQLite persistence for migration state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from imap_icloud_migration.models.state import FolderRow, MessageRow, MessageStatus


def _utcnow() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(tz=UTC)


def _dt_to_iso(value: datetime) -> str:
    """Convert datetime to ISO string in UTC.

    Args:
        value: Datetime value.

    Returns:
        ISO-formatted string in UTC.
    """
    return value.astimezone(UTC).isoformat()


def _iso_to_dt(value: str) -> datetime:
    """Parse ISO datetime strings into timezone-aware datetimes.

    Args:
        value: ISO-formatted datetime string.

    Returns:
        Parsed datetime, defaulting to UTC if no timezone is present.
    """
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class StateDbPaths:
    """Filesystem paths used by the state database."""

    sqlite_path: Path


class StateDb:
    """SQLite wrapper for tracking migration progress and evidence."""

    def __init__(self, *, sqlite_path: Path) -> None:
        """Initialize the database connection.

        Args:
            sqlite_path: Path to the sqlite database file.
        """
        self._paths = StateDbPaths(sqlite_path=sqlite_path)
        self._conn = sqlite3.connect(
            sqlite_path,
            timeout=30,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row

    @property
    def sqlite_path(self) -> Path:
        """Return the sqlite database path."""
        return self._paths.sqlite_path

    def close(self) -> None:
        """Close the underlying sqlite connection."""
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Provide a transaction context manager."""
        cursor = self._conn.cursor()
        try:
            cursor.execute("BEGIN")
            yield self._conn
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

    def init_schema(self) -> None:
        """Create tables if missing and ensure sqlite PRAGMA settings."""
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        with self.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS folders (
                  name TEXT PRIMARY KEY,
                  uidvalidity INTEGER,
                  last_uid_seen INTEGER,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """,
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  folder TEXT NOT NULL,
                  uid INTEGER NOT NULL,
                  uidvalidity INTEGER,
                  status TEXT NOT NULL,
                  message_id_norm TEXT,
                  fingerprint TEXT NOT NULL,
                  eml_path TEXT,
                  eml_sha256 TEXT,
                  size_bytes INTEGER,
                  gmail_message_id TEXT,
                  gmail_thread_id TEXT,
                  labels_json TEXT,
                  attempts INTEGER NOT NULL DEFAULT 0,
                  last_error TEXT,
                  last_error_at TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(folder, uid, uidvalidity)
                )
                """,
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_msgid ON messages(message_id_norm)",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_fingerprint ON messages(fingerprint)",
            )

            conn.execute("PRAGMA user_version = 1")

    def upsert_folder(
        self,
        *,
        name: str,
        uidvalidity: int | None,
        last_uid_seen: int | None,
    ) -> FolderRow:
        """Insert or update a folder row.

        Args:
            name: Folder name.
            uidvalidity: UIDVALIDITY value for the folder.
            last_uid_seen: Highest UID seen in this folder.

        Returns:
            Updated folder row.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO folders(name, uidvalidity, last_uid_seen, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  uidvalidity=excluded.uidvalidity,
                  last_uid_seen=excluded.last_uid_seen,
                  updated_at=excluded.updated_at
                """,
                (name, uidvalidity, last_uid_seen, _dt_to_iso(now), _dt_to_iso(now)),
            )

            row = conn.execute(
                """
                SELECT name, uidvalidity, last_uid_seen, created_at, updated_at
                FROM folders
                WHERE name=?
                """,
                (name,),
            ).fetchone()
            assert row is not None
            return FolderRow(
                name=row["name"],
                uidvalidity=row["uidvalidity"],
                last_uid_seen=row["last_uid_seen"],
                created_at=_iso_to_dt(row["created_at"]),
                updated_at=_iso_to_dt(row["updated_at"]),
            )

    def get_folder(self, *, name: str) -> FolderRow | None:
        """Fetch a folder row by name.

        Args:
            name: Folder name.

        Returns:
            Folder row if present, otherwise None.
        """
        row = self._conn.execute(
            """
            SELECT name, uidvalidity, last_uid_seen, created_at, updated_at
            FROM folders
            WHERE name=?
            """,
            (name,),
        ).fetchone()
        if row is None:
            return None
        return FolderRow(
            name=row["name"],
            uidvalidity=row["uidvalidity"],
            last_uid_seen=row["last_uid_seen"],
            created_at=_iso_to_dt(row["created_at"]),
            updated_at=_iso_to_dt(row["updated_at"]),
        )

    def upsert_message_discovered(
        self,
        *,
        folder: str,
        uid: int,
        uidvalidity: int | None,
        message_id_norm: str | None,
        fingerprint: str,
        size_bytes: int | None,
    ) -> MessageRow:
        """Insert or update a discovered message row.

        Args:
            folder: Folder name.
            uid: Message UID.
            uidvalidity: UIDVALIDITY for the folder.
            message_id_norm: Normalized Message-ID if available.
            fingerprint: Fingerprint hash.
            size_bytes: Size of the message in bytes.

        Returns:
            Updated message row.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO messages(
                  folder, uid, uidvalidity, status, message_id_norm, fingerprint,
                  size_bytes, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(folder, uid, uidvalidity) DO UPDATE SET
                  message_id_norm=excluded.message_id_norm,
                  fingerprint=excluded.fingerprint,
                  size_bytes=excluded.size_bytes,
                  updated_at=excluded.updated_at,
                  status=CASE
                    WHEN status IN ('skipped_filtered', 'failed') THEN 'discovered'
                    ELSE status
                  END
                """,
                (
                    folder,
                    uid,
                    uidvalidity,
                    MessageStatus.discovered.value,
                    message_id_norm,
                    fingerprint,
                    size_bytes,
                    _dt_to_iso(now),
                    _dt_to_iso(now),
                ),
            )
            row = conn.execute(
                "SELECT * FROM messages WHERE folder=? AND uid=? AND uidvalidity IS ?",
                (folder, uid, uidvalidity),
            ).fetchone()
            assert row is not None
            return self._row_to_message(row)

    def mark_downloaded(
        self,
        *,
        message_id: int,
        eml_path: Path,
        eml_sha256: str,
    ) -> None:
        """Mark a message as downloaded with evidence metadata.

        Args:
            message_id: Message row ID.
            eml_path: Evidence file path.
            eml_sha256: SHA-256 digest of the evidence file.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE messages
                SET status=?, eml_path=?, eml_sha256=?, updated_at=?
                WHERE id=?
                """,
                (
                    MessageStatus.downloaded.value,
                    str(eml_path),
                    eml_sha256,
                    _dt_to_iso(now),
                    message_id,
                ),
            )

    def mark_imported(
        self,
        *,
        message_id: int,
        gmail_message_id: str,
        gmail_thread_id: str | None,
        label_ids: list[str],
    ) -> None:
        """Mark a message as imported into Gmail.

        Args:
            message_id: Message row ID.
            gmail_message_id: Gmail message ID.
            gmail_thread_id: Gmail thread ID (if present).
            label_ids: Applied Gmail label IDs.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE messages
                SET status=?, gmail_message_id=?, gmail_thread_id=?, labels_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    MessageStatus.imported.value,
                    gmail_message_id,
                    gmail_thread_id,
                    json.dumps(label_ids),
                    _dt_to_iso(now),
                    message_id,
                ),
            )

    def mark_failed(self, *, message_id: int, error: str) -> None:
        """Mark a message as failed.

        Args:
            message_id: Message row ID.
            error: Error message.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE messages
                SET status=?, attempts=attempts+1, last_error=?, last_error_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    MessageStatus.failed.value,
                    error,
                    _dt_to_iso(now),
                    _dt_to_iso(now),
                    message_id,
                ),
            )

    def mark_skipped_duplicate(self, *, message_id: int, reason: str) -> None:
        """Mark a message as skipped due to duplication.

        Args:
            message_id: Message row ID.
            reason: Reason for skipping.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE messages
                SET status=?, last_error=?, last_error_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    MessageStatus.skipped_duplicate.value,
                    reason,
                    _dt_to_iso(now),
                    _dt_to_iso(now),
                    message_id,
                ),
            )

    def mark_skipped_filtered(self, *, message_id: int, reason: str) -> None:
        """Mark a message as filtered out.

        Args:
            message_id: Message row ID.
            reason: Reason for skipping.
        """
        now = _utcnow()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE messages
                SET status=?, last_error=?, last_error_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    MessageStatus.skipped_filtered.value,
                    reason,
                    _dt_to_iso(now),
                    _dt_to_iso(now),
                    message_id,
                ),
            )

    def update_folder_checkpoint(
        self,
        *,
        name: str,
        uidvalidity: int | None,
        last_uid_seen: int | None,
    ) -> None:
        """Update folder checkpoint information.

        Args:
            name: Folder name.
            uidvalidity: UIDVALIDITY value.
            last_uid_seen: Last UID seen.
        """
        self.upsert_folder(name=name, uidvalidity=uidvalidity, last_uid_seen=last_uid_seen)

    def find_existing_imported(
        self,
        *,
        message_id_norm: str | None,
        fingerprint: str,
    ) -> int | None:
        """Return an imported message row ID for dedupe checks.

        Args:
            message_id_norm: Normalized Message-ID, if present.
            fingerprint: Fingerprint hash.

        Returns:
            Existing message ID if found, otherwise None.
        """
        if message_id_norm:
            row = self._conn.execute(
                """
                SELECT id FROM messages
                WHERE gmail_message_id IS NOT NULL AND message_id_norm=?
                LIMIT 1
                """,
                (message_id_norm,),
            ).fetchone()
            if row is not None:
                return int(row["id"])

        row = self._conn.execute(
            """
            SELECT id FROM messages
            WHERE gmail_message_id IS NOT NULL AND fingerprint=?
            LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def count_folder_messages(self, folder: str) -> int:
        """Return the number of imported messages for a folder.

        Args:
            folder: Folder name.

        Returns:
            Count of imported messages.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE status='imported' AND folder=?",
            (folder,),
        ).fetchone()
        return int(row["c"]) if row else 0

    def reset_skipped_and_failed(self) -> int:
        """Reset skipped/failed messages and clear folder checkpoints.

        Returns:
            Number of messages reset.
        """
        with self.transaction() as conn:
            conn.execute("UPDATE folders SET last_uid_seen = 0")
            res = conn.execute(
                """
                UPDATE messages
                SET status = 'discovered'
                WHERE status IN ('skipped_filtered', 'failed', 'skipped_duplicate')
                """,
            )
            return int(res.rowcount)

    def counts_by_status(self) -> dict[MessageStatus, int]:
        """Return counts of messages by status.

        Returns:
            Mapping of MessageStatus to count.
        """
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS c FROM messages GROUP BY status",
        ).fetchall()
        out: dict[MessageStatus, int] = {}
        for row in rows:
            out[MessageStatus(str(row["status"]))] = int(row["c"])
        return out

    def iter_messages(self, *, status: MessageStatus | None = None) -> Iterator[MessageRow]:
        """Iterate message rows optionally filtered by status.

        Args:
            status: Optional status filter.

        Yields:
            MessageRow instances.
        """
        if status is None:
            rows = self._conn.execute("SELECT * FROM messages ORDER BY id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE status=? ORDER BY id",
                (status.value,),
            ).fetchall()
        for row in rows:
            yield self._row_to_message(row)

    def _row_to_message(self, row: Mapping[str, Any]) -> MessageRow:
        """Convert a sqlite row to a MessageRow.

        Args:
            row: Row mapping from sqlite.

        Returns:
            MessageRow instance.
        """
        return MessageRow(
            id=int(row["id"]),
            folder=str(row["folder"]),
            uid=int(row["uid"]),
            uidvalidity=row["uidvalidity"],
            status=MessageStatus(str(row["status"])),
            message_id_norm=row["message_id_norm"],
            fingerprint=str(row["fingerprint"]),
            eml_path=Path(row["eml_path"]) if row["eml_path"] else None,
            eml_sha256=row["eml_sha256"],
            size_bytes=row["size_bytes"],
            gmail_message_id=row["gmail_message_id"],
            gmail_thread_id=row["gmail_thread_id"],
            attempts=int(row["attempts"]),
            last_error=row["last_error"],
            last_error_at=_iso_to_dt(row["last_error_at"]) if row["last_error_at"] else None,
            created_at=_iso_to_dt(str(row["created_at"])),
            updated_at=_iso_to_dt(str(row["updated_at"])),
        )

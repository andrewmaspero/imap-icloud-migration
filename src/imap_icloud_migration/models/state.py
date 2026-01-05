"""Pydantic models for database state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from imap_icloud_migration.models.base import AppModel


class MessageStatus(StrEnum):
    """Message lifecycle statuses tracked in sqlite."""

    discovered = "discovered"
    downloaded = "downloaded"
    imported = "imported"
    skipped_duplicate = "skipped_duplicate"
    skipped_filtered = "skipped_filtered"
    failed = "failed"


class FolderRow(AppModel):
    """Row model for the folders table."""

    name: str = Field(min_length=1)
    uidvalidity: int | None = Field(default=None, ge=1)
    last_uid_seen: int | None = Field(default=None, ge=0)
    created_at: datetime
    updated_at: datetime


class MessageRow(AppModel):
    """Row model for the messages table."""

    id: int = Field(ge=1)
    folder: str = Field(min_length=1)
    uid: int = Field(ge=1)
    uidvalidity: int | None = Field(default=None, ge=1)

    status: MessageStatus
    message_id_norm: str | None = None
    fingerprint: str = Field(min_length=1)

    eml_path: Path | None = None
    eml_sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)

    gmail_message_id: str | None = None
    gmail_thread_id: str | None = None

    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None
    last_error_at: datetime | None = None

    created_at: datetime
    updated_at: datetime

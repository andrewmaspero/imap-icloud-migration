"""Shared enums and lightweight Pydantic models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from imap_icloud_migration.models.base import AppModel


class GmailIngestMode(StrEnum):
    """Supported Gmail ingestion modes."""

    import_ = "import"
    insert = "insert"


class GmailInternalDateSource(StrEnum):
    """Sources for Gmail internalDate when ingesting messages."""

    date_header = "dateHeader"
    received_time = "receivedTime"


class GmailSystemLabelId(StrEnum):
    """Gmail system label identifiers used when mapping IMAP folders."""

    inbox = "INBOX"
    sent = "SENT"
    trash = "TRASH"
    spam = "SPAM"
    draft = "DRAFT"


class SummaryReport(AppModel):
    """Summarized migration report emitted by the CLI."""

    created_at: datetime
    sqlite_path: str
    counts: dict[str, int] = Field(default_factory=dict)
    evidence_mismatches: int = 0

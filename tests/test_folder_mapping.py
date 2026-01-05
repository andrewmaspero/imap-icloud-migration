"""Tests for IMAP folder → Gmail label mapping."""

from __future__ import annotations

from imap_icloud_migration.gmail.labels import folder_to_custom_label, folder_to_system_labels
from imap_icloud_migration.models.types import GmailSystemLabelId


def test_folder_to_custom_label() -> None:
    """Custom labels should preserve folder names with a prefix."""
    assert folder_to_custom_label(prefix="iCloud", folder="INBOX") == "iCloud/INBOX"
    assert folder_to_custom_label(prefix="iCloud", folder="Sent Messages") == "iCloud/Sent Messages"


def test_folder_to_system_labels() -> None:
    """System labels should match common folder names."""
    assert folder_to_system_labels("INBOX") == [GmailSystemLabelId.inbox]
    assert folder_to_system_labels("Sent Messages") == [GmailSystemLabelId.sent]
    assert folder_to_system_labels("Trash") == [GmailSystemLabelId.trash]

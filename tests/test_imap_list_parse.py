"""Tests for IMAP LIST parsing."""

from __future__ import annotations

from imap_icloud_migration.imap.client import _parse_list_response


def test_parse_list_response_handles_common_formats() -> None:
    """LIST parsing should support quoted and unquoted mailbox names."""
    lines = [
        b'* LIST (\\HasNoChildren) "/" "INBOX"\r\n',
        b'* LIST (\\HasNoChildren) "/" "Sent Messages"\r\n',
        b'* LIST (\\Noselect) NIL "Archive"\r\n',
        b'* LIST (\\HasNoChildren) "/" INBOX\r\n',
    ]

    assert _parse_list_response(lines) == ["INBOX", "Sent Messages", "Archive"]


def test_parse_list_response_handles_literal_mailbox_name() -> None:
    """LIST parsing should handle literal mailbox names."""
    lines = [
        b'* LIST (\\HasNoChildren) "/" {12}\r\n',
        b"Sent Messages\r\n",
    ]
    assert _parse_list_response(lines) == ["Sent Messages"]

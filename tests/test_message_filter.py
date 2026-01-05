"""Tests for address-based filtering."""

from __future__ import annotations

from imap_icloud_migration.utils.email import AddressFilter, parse_minimal_headers


def test_address_filter_matches_recipient() -> None:
    """AddressFilter should match recipients in To headers."""
    raw = b"From: sender@example.com\r\nTo: Andrew <andrew@vectorfy.co>\r\nSubject: Hi\r\n\r\nBody"
    headers = parse_minimal_headers(raw)
    filt = AddressFilter(target_addresses=frozenset({"andrew@vectorfy.co"}))
    assert filt.matches(headers) is True


def test_address_filter_rejects_other_mail() -> None:
    """AddressFilter should reject messages with non-matching addresses."""
    raw = b"From: sender@example.com\r\nTo: someoneelse@example.com\r\nSubject: Hi\r\n\r\nBody"
    headers = parse_minimal_headers(raw)
    filt = AddressFilter(target_addresses=frozenset({"andrew@vectorfy.co"}))
    assert filt.matches(headers) is False

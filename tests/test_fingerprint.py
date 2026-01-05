"""Tests for email normalization and fingerprinting."""

from __future__ import annotations

from pathlib import Path

from imap_icloud_migration.utils.email import (
    body_prefix,
    extract_email_addresses,
    normalize_message_id,
)
from imap_icloud_migration.utils.fingerprint import compute_fingerprint, sha256_file_hex


def test_normalize_message_id() -> None:
    """normalize_message_id should handle empty and canonical forms."""
    assert normalize_message_id(None) is None
    assert normalize_message_id("") is None
    assert normalize_message_id(" <ABC@EXAMPLE.COM> ") == "<abc@example.com>"
    assert normalize_message_id("<a@b> extra") == "<a@b>"


def test_fingerprint_stable() -> None:
    """compute_fingerprint should be deterministic for identical input."""
    raw = (
        b"Subject: Test\r\n"
        b"Message-ID: <ABC@EXAMPLE.COM>\r\n"
        b"Date: Tue, 1 Jan 2019 10:00:00 +0000\r\n"
        b"\r\n"
        b"Hello"
    )
    r1 = compute_fingerprint(raw, body_bytes=16)
    r2 = compute_fingerprint(raw, body_bytes=16)
    assert r1.fingerprint == r2.fingerprint
    assert r1.message_id_norm == "<abc@example.com>"


def test_body_prefix_splits_headers() -> None:
    """body_prefix should return the body portion after headers."""
    raw = b"Header: Value\r\n\r\nBodyContent"
    assert body_prefix(raw, max_bytes=4) == b"Body"


def test_extract_email_addresses() -> None:
    """extract_email_addresses should normalize display-name addresses."""
    value = "Alice <ALICE@example.com>, bob@example.com"
    assert extract_email_addresses(value) == {"alice@example.com", "bob@example.com"}


def test_sha256_file_hex(tmp_path: Path) -> None:
    """sha256_file_hex should compute a stable file digest."""
    path = tmp_path / "sample.txt"
    path.write_text("hello", encoding="utf-8")
    assert sha256_file_hex(path) == sha256_file_hex(path)

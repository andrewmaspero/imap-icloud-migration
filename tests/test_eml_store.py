"""Tests for EML evidence storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from imap_icloud_migration.storage.eml_store import EMLStore


def test_eml_store_write_and_idempotent(tmp_path: Path) -> None:
    """EMLStore should write immutable files and be idempotent."""
    store = EMLStore(evidence_dir=tmp_path / "evidence")
    raw = b"Subject: Test\r\n\r\nHello"

    res1 = store.write_immutable(folder="INBOX", uidvalidity=1, uid=10, raw_rfc822=raw)
    assert res1.path.exists()
    assert (res1.path.stat().st_mode & 0o777) == 0o444

    res2 = store.write_immutable(folder="INBOX", uidvalidity=1, uid=10, raw_rfc822=raw)
    assert res2.sha256 == res1.sha256
    assert res2.path == res1.path


def test_eml_store_detects_mismatch(tmp_path: Path) -> None:
    """EMLStore should detect hash mismatches for existing evidence files."""
    store = EMLStore(evidence_dir=tmp_path / "evidence")
    raw1 = b"Subject: Test\r\n\r\nHello"
    raw2 = b"Subject: Test\r\n\r\nDifferent"

    _ = store.write_immutable(folder="INBOX", uidvalidity=1, uid=10, raw_rfc822=raw1)
    with pytest.raises(ValueError):
        store.write_immutable(folder="INBOX", uidvalidity=1, uid=10, raw_rfc822=raw2)

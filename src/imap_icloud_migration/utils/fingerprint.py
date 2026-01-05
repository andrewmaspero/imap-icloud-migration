"""Message fingerprinting and hashing utilities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from imap_icloud_migration.utils.email import (
    MinimalHeaders,
    body_prefix,
    parse_minimal_headers,
)


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest for raw bytes.

    Args:
        data: Input bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()


def sha256_file_hex(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hex digest for a file on disk.

    Args:
        path: Path to the file.
        chunk_size: Chunk size for streaming reads.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass(frozen=True)
class FingerprintResult:
    """Fingerprint result with normalized headers and hash."""

    fingerprint: str
    message_id_norm: str | None
    headers: MinimalHeaders


def compute_fingerprint(raw_rfc822: bytes, *, body_bytes: int) -> FingerprintResult:
    """Compute a stable fingerprint for a raw RFC822 message.

    Args:
        raw_rfc822: Raw RFC822 message bytes.
        body_bytes: Number of body bytes to include in the fingerprint.

    Returns:
        Fingerprint result including normalized headers.
    """
    headers = parse_minimal_headers(raw_rfc822)
    body = body_prefix(raw_rfc822, max_bytes=body_bytes)

    canonical = "\n".join(
        [
            headers.date_dt_iso or headers.date_raw or "",
            headers.from_ or "",
            headers.to or "",
            headers.subject or "",
            str(len(raw_rfc822)),
        ],
    ).encode("utf-8", errors="replace")

    fp = sha256_hex(canonical + b"\n" + body)
    return FingerprintResult(
        fingerprint=fp,
        message_id_norm=headers.message_id_norm,
        headers=headers,
    )

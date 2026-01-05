"""Evidence store for immutable .eml files."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from imap_icloud_migration.utils.fingerprint import sha256_file_hex, sha256_hex

_FOLDER_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_folder_name(folder: str) -> str:
    """Normalize folder names for filesystem-safe evidence storage.

    Args:
        folder: IMAP folder name.

    Returns:
        Sanitized folder name suitable for directories.
    """
    sanitized = folder.strip()
    sanitized = sanitized.replace(os.sep, "_").replace("/", "_")
    sanitized = _FOLDER_SAFE_RE.sub("_", sanitized)
    sanitized = sanitized.strip("._-")
    return sanitized or "folder"


@dataclass(frozen=True)
class EmlWriteResult:
    """Result of writing an evidence file."""

    path: Path
    sha256: str
    size_bytes: int


class EMLStore:
    """Write and validate immutable .eml evidence files."""

    def __init__(self, *, evidence_dir: Path) -> None:
        """Initialize the store.

        Args:
            evidence_dir: Base directory for evidence files.
        """
        self._evidence_dir = evidence_dir

    @property
    def evidence_dir(self) -> Path:
        """Return the root evidence directory."""
        return self._evidence_dir

    def write_immutable(
        self,
        *,
        folder: str,
        uidvalidity: int | None,
        uid: int,
        raw_rfc822: bytes,
    ) -> EmlWriteResult:
        """Write RFC822 bytes to an immutable `.eml` evidence file.

        Args:
            folder: IMAP folder name.
            uidvalidity: UIDVALIDITY of the folder if known.
            uid: Message UID within the folder.
            raw_rfc822: Raw RFC822 message bytes.

        Returns:
            Details about the written or verified evidence file.

        Raises:
            ValueError: If an existing evidence file does not match the expected hash.
        """
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

        folder_dir = self._evidence_dir / _safe_folder_name(folder)
        folder_dir.mkdir(parents=True, exist_ok=True)

        uv = uidvalidity or 0
        target = folder_dir / f"{uv}-{uid}.eml"
        expected_sha = sha256_hex(raw_rfc822)

        if target.exists():
            actual_sha = sha256_file_hex(target)
            if actual_sha != expected_sha:
                msg = f"Evidence file already exists but differs: {target}"
                raise ValueError(msg)
            return EmlWriteResult(path=target, sha256=actual_sha, size_bytes=target.stat().st_size)

        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=str(folder_dir),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw_rfc822)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(tmp_path, target)

            dir_fd = os.open(str(folder_dir), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            os.chmod(target, 0o444)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

        return EmlWriteResult(path=target, sha256=expected_sha, size_bytes=len(raw_rfc822))

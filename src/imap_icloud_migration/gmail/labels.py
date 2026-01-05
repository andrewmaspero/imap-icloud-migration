"""Gmail label helpers and IMAP-to-label mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from imap_icloud_migration.models.types import GmailSystemLabelId

_SAFE_LABEL_RE = re.compile(r"[^\w./ -]+", re.UNICODE)


class GmailLabelError(RuntimeError):
    """Raised when label operations fail."""


@dataclass
class GmailLabelCache:
    """Caches label name → label id."""

    service: Any
    user_id: str
    _name_to_id: dict[str, str]

    @classmethod
    def from_service(cls, service: Any, *, user_id: str) -> GmailLabelCache:
        """Create a cache from a Gmail API service.

        Args:
            service: Gmail API service.
            user_id: Target Gmail user.

        Returns:
            Initialized GmailLabelCache.
        """
        cache = cls(service=service, user_id=user_id, _name_to_id={})
        cache.refresh()
        return cache

    def refresh(self) -> None:
        """Refresh the cached label mapping from Gmail."""
        resp = self.service.users().labels().list(userId=self.user_id).execute()
        labels = resp.get("labels", []) if isinstance(resp, dict) else []
        self._name_to_id = {
            str(label["name"]): str(label["id"])
            for label in labels
            if "name" in label and "id" in label
        }

    def ensure(self, *, name: str) -> str:
        """Ensure a label exists and return its ID.

        Args:
            name: Label name.

        Returns:
            Gmail label ID.

        Raises:
            GmailLabelError: If the label name is invalid or create fails.
        """
        normalized = name.strip()
        if not normalized:
            raise GmailLabelError("Label name must not be blank")

        existing = self._name_to_id.get(normalized)
        if existing:
            return existing

        body = {
            "name": normalized,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = self.service.users().labels().create(userId=self.user_id, body=body).execute()
        if not isinstance(created, dict) or "id" not in created:
            raise GmailLabelError(f"Unexpected label create response: {created!r}")
        label_id = str(created["id"])
        self._name_to_id[normalized] = label_id
        return label_id


def folder_to_custom_label(*, prefix: str, folder: str) -> str:
    """Map an IMAP folder to a Gmail custom label name.

    Args:
        prefix: Label prefix to namespace labels.
        folder: IMAP folder name.

    Returns:
        Gmail label name.
    """
    trimmed = folder.strip().strip("/")
    safe = _SAFE_LABEL_RE.sub("_", trimmed)
    safe = safe.replace("\\", "_")
    return f"{prefix}/{safe}" if prefix else safe


def folder_to_system_labels(folder: str) -> list[GmailSystemLabelId]:
    """Map an IMAP folder to Gmail system labels.

    Args:
        folder: IMAP folder name.

    Returns:
        List of GmailSystemLabelId values.
    """
    lowered = folder.strip().lower()

    if lowered in {"inbox"}:
        return [GmailSystemLabelId.inbox]
    if lowered == "sent" or lowered.startswith("sent") or "sent messages" in lowered:
        return [GmailSystemLabelId.sent]
    if "trash" in lowered or lowered in {"deleted messages", "deleted"}:
        return [GmailSystemLabelId.trash]
    if "junk" in lowered or "spam" in lowered:
        return [GmailSystemLabelId.spam]
    if "draft" in lowered:
        return [GmailSystemLabelId.draft]

    return []

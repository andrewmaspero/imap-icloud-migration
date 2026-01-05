"""Gmail API client creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from imap_icloud_migration.config.settings import GmailSettings
from imap_icloud_migration.gmail.auth import load_credentials


@dataclass(frozen=True)
class GmailClient:
    """Thin wrapper holding the Gmail API service object."""

    service: Any

    @classmethod
    def from_settings(cls, settings: GmailSettings) -> GmailClient:
        """Create a Gmail client using configured OAuth settings.

        Args:
            settings: Gmail settings with credential paths.

        Returns:
            GmailClient instance.
        """
        creds: Credentials = load_credentials(settings=settings)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return cls(service=service)

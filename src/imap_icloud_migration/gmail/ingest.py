"""Gmail message ingestion helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from imap_icloud_migration.models.types import GmailIngestMode, GmailInternalDateSource


class GmailIngestError(RuntimeError):
    """Raised when Gmail ingest calls fail."""


@dataclass(frozen=True)
class IngestResult:
    """Result of a Gmail import/insert call."""

    gmail_message_id: str
    gmail_thread_id: str | None
    label_ids: list[str]


class GmailIngester:
    """Wrapper around Gmail API message import/insert endpoints."""

    def __init__(self, *, service: Any, user_id: str) -> None:
        """Initialize the ingester.

        Args:
            service: Gmail API service object.
            user_id: Target Gmail user identifier (email or "me").
        """
        self._service = service
        self._user_id = user_id

    def ingest_eml(
        self,
        *,
        eml_path: Path,
        label_ids: list[str],
        mode: GmailIngestMode,
        internal_date_source: GmailInternalDateSource,
    ) -> IngestResult:
        """Dispatch to import or insert based on mode.

        Args:
            eml_path: Path to the .eml file.
            label_ids: Gmail label IDs to apply.
            mode: Ingestion mode (import or insert).
            internal_date_source: Source for Gmail internalDate.

        Returns:
            IngestResult with Gmail IDs.
        """
        if mode == GmailIngestMode.import_:
            return self.import_eml(
                eml_path=eml_path,
                label_ids=label_ids,
                internal_date_source=internal_date_source,
            )
        return self.insert_eml(
            eml_path=eml_path,
            label_ids=label_ids,
            internal_date_source=internal_date_source,
        )

    def import_eml(
        self,
        *,
        eml_path: Path,
        label_ids: list[str],
        internal_date_source: GmailInternalDateSource,
    ) -> IngestResult:
        """Call Gmail import endpoint.

        Args:
            eml_path: Path to the .eml file.
            label_ids: Gmail label IDs to apply.
            internal_date_source: Source for Gmail internalDate.

        Returns:
            IngestResult with Gmail IDs.
        """
        return self._call(
            endpoint="import",
            eml_path=eml_path,
            label_ids=label_ids,
            internal_date_source=internal_date_source,
        )

    def insert_eml(
        self,
        *,
        eml_path: Path,
        label_ids: list[str],
        internal_date_source: GmailInternalDateSource,
    ) -> IngestResult:
        """Call Gmail insert endpoint.

        Args:
            eml_path: Path to the .eml file.
            label_ids: Gmail label IDs to apply.
            internal_date_source: Source for Gmail internalDate.

        Returns:
            IngestResult with Gmail IDs.
        """
        return self._call(
            endpoint="insert",
            eml_path=eml_path,
            label_ids=label_ids,
            internal_date_source=internal_date_source,
        )

    def _call(
        self,
        *,
        endpoint: str,
        eml_path: Path,
        label_ids: list[str],
        internal_date_source: GmailInternalDateSource,
    ) -> IngestResult:
        """Perform the Gmail API call.

        Args:
            endpoint: Gmail endpoint name ("import" or "insert").
            eml_path: Path to the .eml file.
            label_ids: Gmail label IDs to apply.
            internal_date_source: Source for Gmail internalDate.

        Returns:
            IngestResult with Gmail IDs.

        Raises:
            GmailIngestError: If the endpoint is unknown or the request fails.
        """
        resolved_path = eml_path.expanduser().resolve()
        if not resolved_path.exists():
            raise GmailIngestError(f".eml does not exist: {resolved_path}")

        media = MediaFileUpload(
            str(resolved_path),
            mimetype="message/rfc822",
            resumable=True,
        )

        body = {"labelIds": label_ids} if label_ids else {}

        try:
            if endpoint == "import":
                req = (
                    self._service.users()
                    .messages()
                    .import_(
                        userId=self._user_id,
                        internalDateSource=internal_date_source.value,
                        body=body,
                        media_body=media,
                    )
                )
            elif endpoint == "insert":
                req = (
                    self._service.users()
                    .messages()
                    .insert(
                        userId=self._user_id,
                        internalDateSource=internal_date_source.value,
                        body=body,
                        media_body=media,
                    )
                )
            else:
                raise GmailIngestError(f"Unknown endpoint: {endpoint}")

            resp = req.execute()
        except HttpError as exc:
            raise GmailIngestError(f"Gmail {endpoint} failed: {exc}") from exc

        if not isinstance(resp, dict) or "id" not in resp:
            raise GmailIngestError(f"Unexpected Gmail {endpoint} response: {resp!r}")

        return IngestResult(
            gmail_message_id=str(resp["id"]),
            gmail_thread_id=str(resp["threadId"]) if resp.get("threadId") else None,
            label_ids=[str(x) for x in (resp.get("labelIds") or [])],
        )

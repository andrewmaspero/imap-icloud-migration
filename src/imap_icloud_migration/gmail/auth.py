"""Gmail OAuth authentication helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from imap_icloud_migration.config.settings import GmailSettings

logger = logging.getLogger(__name__)

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.insert",
]


def load_credentials(*, settings: GmailSettings) -> Credentials:
    """Load or refresh Gmail OAuth credentials.

    Args:
        settings: Gmail settings containing credentials/token paths.

    Returns:
        Validated OAuth credentials.

    Raises:
        ValueError: If token file path is invalid.
    """
    token_file: Path = settings.token_file.expanduser().resolve()
    if token_file.exists() and token_file.is_dir():
        raise ValueError(
            "token_file is a directory: "
            f"{token_file}. Set MIG_GMAIL__TOKEN_FILE to a file path, "
            "e.g. /absolute/path/to/gmail-token.json",
        )
    if token_file.exists() and not token_file.is_file():
        raise ValueError(
            "token_file is not a file: "
            f"{token_file}. Set MIG_GMAIL__TOKEN_FILE to a file path, "
            "e.g. /absolute/path/to/gmail-token.json",
        )
    token_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        raw = settings.credentials_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and "installed" not in data and "web" in data:
            raise ValueError(
                "OAuth client JSON looks like a 'Web application' client. "
                "Create a 'Desktop app' (Installed app) OAuth client in Google Cloud Console, "
                "download its JSON, and point MIG_GMAIL__CREDENTIALS_FILE to that file.",
            )
    except json.JSONDecodeError:
        pass

    creds: Credentials | None = None
    if token_file.exists():
        try:
            if token_file.stat().st_size == 0:
                logger.warning(
                    "Token file exists but is empty; will re-auth (token_file=%s)",
                    token_file,
                )
            else:
                creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                    str(token_file),
                    scopes=SCOPES,
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to load token file; will re-auth (token_file=%s, error=%r)",
                token_file,
                exc,
            )
            creds = None

    if creds is not None and creds.valid:
        return creds

    if creds is not None and creds.expired and creds.refresh_token:
        creds.refresh(Request())  # type: ignore[no-untyped-call]
        _write_token_file(token_file, creds)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(settings.credentials_file), SCOPES)
    creds = flow.run_local_server(port=0)
    _write_token_file(token_file, creds)
    return creds


def _write_token_file(path: Path, creds: Credentials) -> None:
    """Persist OAuth credentials to disk.

    Args:
        path: Target token file.
        creds: OAuth credentials to serialize.
    """
    path.write_text(creds.to_json(), encoding="utf-8")  # type: ignore[no-untyped-call]

"""Configuration and environment settings for the migration tool."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from imap_icloud_migration.models.types import GmailIngestMode, GmailInternalDateSource


class ImapSettings(BaseSettings):
    """IMAP connection and fetch settings."""

    model_config = SettingsConfigDict(extra="forbid")

    host: str = "imap.mail.me.com"
    port: int = 993
    username: Annotated[str, Field(min_length=1)]
    app_password: Annotated[str, Field(min_length=1, repr=False)]
    ssl: bool = True

    folder_include: list[str] = Field(default_factory=list)
    folder_exclude: list[str] = Field(default_factory=list)

    connections: Annotated[int, Field(ge=1, le=10)] = 2
    batch_size: Annotated[int, Field(ge=1, le=500)] = 50
    search_query: Annotated[str, Field(min_length=1)] = "ALL"


class GmailSettings(BaseSettings):
    """Gmail OAuth and ingestion settings."""

    model_config = SettingsConfigDict(extra="forbid")

    target_user_email: Annotated[str, Field(min_length=3, pattern=r".+@.+\..+")]

    credentials_file: Path
    token_file: Path = Path(".secrets/gmail-token.json")

    mode: GmailIngestMode = GmailIngestMode.import_
    internal_date_source: GmailInternalDateSource = GmailInternalDateSource.date_header

    label_prefix: Annotated[str, Field(min_length=1)] = "iCloud"

    @field_validator("credentials_file")
    @classmethod
    def _credentials_file_must_exist(cls, value: Path) -> Path:
        """Ensure the credentials file exists and is a file.

        Args:
            value: Path to the credentials file.

        Returns:
            The validated path.

        Raises:
            ValueError: If the path does not exist or is not a file.
        """
        if not value.exists():
            msg = f"credentials_file does not exist: {value}"
            raise ValueError(msg)
        if not value.is_file():
            msg = f"credentials_file is not a file: {value}"
            raise ValueError(msg)
        return value

    @field_validator("label_prefix")
    @classmethod
    def _label_prefix_not_blank(cls, value: str) -> str:
        """Normalize and validate the label prefix.

        Args:
            value: Raw label prefix.

        Returns:
            Stripped prefix.

        Raises:
            ValueError: If the label prefix is blank.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("label_prefix must not be blank")
        return stripped


class StorageSettings(BaseSettings):
    """Settings for evidence and report storage."""

    model_config = SettingsConfigDict(extra="forbid")

    root_dir: Path = Path("./data")
    evidence_dir_override: Path | None = None
    reports_dir_override: Path | None = None
    sqlite_path_override: Path | None = None

    fingerprint_body_bytes: Annotated[int, Field(ge=0, le=1024 * 1024)] = 4096

    @field_validator("root_dir")
    @classmethod
    def _root_dir_to_absolute(cls, value: Path) -> Path:
        """Resolve the storage root directory to an absolute path."""
        return value.expanduser().resolve()

    @field_validator("evidence_dir_override", "reports_dir_override", "sqlite_path_override")
    @classmethod
    def _paths_to_absolute(cls, value: Path | None) -> Path | None:
        """Resolve optional override paths to absolute paths."""
        return value.expanduser().resolve() if value is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_dir(self) -> Path:
        """Return the resolved evidence directory."""
        return (self.evidence_dir_override or (self.root_dir / "evidence")).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reports_dir(self) -> Path:
        """Return the resolved reports directory."""
        return (self.reports_dir_override or (self.root_dir / "reports")).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlite_path(self) -> Path:
        """Return the resolved sqlite database path."""
        return (self.sqlite_path_override or (self.root_dir / "state.sqlite3")).resolve()


class ConcurrencySettings(BaseSettings):
    """Concurrency limits for IMAP/Gmail operations."""

    model_config = SettingsConfigDict(extra="forbid")

    gmail_workers: Annotated[int, Field(ge=1, le=50)] = 10
    imap_fetch_concurrency: Annotated[int, Field(ge=1, le=50)] = 5
    queue_maxsize: Annotated[int, Field(ge=1, le=10_000)] = 1000


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    model_config = SettingsConfigDict(extra="forbid")

    level: Annotated[str, Field(min_length=1)] = "INFO"
    json_logs: bool = True


class FilterSettings(BaseSettings):
    """Settings for filtering messages by addresses."""

    model_config = SettingsConfigDict(extra="forbid")

    target_addresses: list[str] = Field(default_factory=list)
    include_sender: bool = True
    include_recipients: bool = True

    @field_validator("target_addresses", mode="before")
    @classmethod
    def _parse_target_addresses(cls, value: object) -> object:
        """Parse addresses from JSON or comma-separated values.

        Args:
            value: Raw env value.

        Returns:
            Parsed value (list or original).
        """
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return value

    @field_validator("target_addresses")
    @classmethod
    def _normalize_addresses(cls, value: list[str]) -> list[str]:
        """Normalize and validate address list entries.

        Args:
            value: List of raw addresses.

        Returns:
            Normalized list of addresses.

        Raises:
            ValueError: If any address does not look like an email.
        """
        normalized: list[str] = []
        for addr in value:
            lowered = addr.strip().lower()
            if not lowered:
                continue
            if "@" not in lowered:
                raise ValueError(f"Invalid email address in target_addresses: {addr!r}")
            normalized.append(lowered)

        seen: set[str] = set()
        result: list[str] = []
        for addr in normalized:
            if addr in seen:
                continue
            seen.add(addr)
            result.append(addr)
        return result


class AppSettings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_prefix="MIG_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    imap: ImapSettings | None = None
    gmail: GmailSettings | None = None
    storage: StorageSettings = Field(default_factory=StorageSettings)
    concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    filter: FilterSettings = Field(default_factory=FilterSettings)


def load_settings(*, env_file: Path | None) -> AppSettings:
    """Load validated settings from environment and optional file.

    Args:
        env_file: Optional .env file path.

    Returns:
        Validated AppSettings instance.
    """
    if env_file is None:
        return AppSettings()
    return AppSettings(_env_file=env_file)  # type: ignore[call-arg]

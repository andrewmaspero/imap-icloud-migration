"""Console entrypoint for `imap-icloud-migration`."""

from __future__ import annotations

from imap_icloud_migration.cli.app import app


def main() -> int:
    """Run the Typer CLI application.

    Returns:
        Process exit code.
    """
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

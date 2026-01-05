# Repository Guidelines

## Project Structure & Module Organization
- `src/imap_icloud_migration/` contains the application code. Key areas include `cli/` (Typer commands), `imap/` (IMAP fetching/mapping), `gmail/` (Gmail API ingest/auth), `storage/` (evidence + sqlite), and `pipeline/` (orchestration/retry).
- `tests/` holds pytest suites (e.g., `tests/test_*.py`).
- `example.env` is the configuration template. Do not store real secrets in the repo.
- `migration_storage/` is local output state/evidence; treat it as generated data.

## Build, Test, and Development Commands
- `uv sync` installs dependencies from `pyproject.toml` and `uv.lock`.
- `uv run imap-icloud-migration --help` shows CLI usage.
- `uv run imap-icloud-migration gmail-auth` runs Gmail OAuth (opens a browser on first use).
- `uv run imap-icloud-migration migrate --dry-run` downloads IMAP + writes evidence/state only.
- `uv run imap-icloud-migration migrate` performs a full migration.
- `uv run imap-icloud-migration verify` validates `.eml` checksums vs sqlite.
- `uv run ruff check .` and `uv run ruff format .` lint/format.
- `uv run mypy src` runs strict type checks.
- `uv run pytest` executes tests.

## Coding Style & Naming Conventions
- Python 3.13+, 4-space indentation, and line length 100 (Ruff).
- Use double quotes (Ruff format).
- Prefer type hints; mypy is strict.
- Files and modules follow `snake_case`.

## Testing Guidelines
- Framework: `pytest` with `pytest-asyncio` (`asyncio_mode = auto`).
- Tests live in `tests/` and use `test_*.py` naming.
- No explicit coverage target is defined; add tests for new behavior and bug fixes.

## Commit & Pull Request Guidelines
- No commit history exists yet, so no established convention. If adding commits, use clear, imperative messages (e.g., "Add Gmail label mapping").
- PRs should include a concise summary, test results (commands run), and any config notes (never include secrets).

## Security & Configuration Tips
- Secrets belong in `.env` (from `example.env`); do not commit `credentials.json` or `token.json`.
- Output data under `MIG_STORAGE__ROOT_DIR` is generated; keep it out of version control.

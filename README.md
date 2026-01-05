# ![imap-icloud-migration](https://img.shields.io/badge/imap--icloud--migration-Deterministic%20IMAP%20to%20Gmail-1D4ED8?style=for-the-badge&logo=python&logoColor=white)

Deterministic iCloud IMAP -> Gmail migration tool that writes immutable `.eml` evidence and
tracks state in sqlite for restart safety and auditability.

<div align="left">
  <table>
    <tr>
      <td><strong>Lifecycle</strong></td>
      <td>
        <img src="https://img.shields.io/badge/Status-0.1.x-0ea5e9?style=flat&logo=github&logoColor=white" alt="Status 0.1.x" />
        <a href=".github/workflows/ci.yml"><img src="https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?style=flat&logo=githubactions&logoColor=white" alt="CI/CD GitHub Actions" /></a>
        <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-D22128?style=flat&logo=apache&logoColor=white" alt="Apache-2.0 license" /></a>
      </td>
    </tr>
    <tr>
      <td><strong>Core Stack</strong></td>
      <td>
        <img src="https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.13+" />
        <img src="https://img.shields.io/badge/IMAP-async-0f766e?style=flat" alt="Async IMAP" />
        <img src="https://img.shields.io/badge/Gmail%20API-import%2Finsert-ea4335?style=flat&logo=gmail&logoColor=white" alt="Gmail API" />
        <img src="https://img.shields.io/badge/iCloud%2B-custom%20domain-111827?style=flat&logo=apple&logoColor=white" alt="iCloud+ custom domain" />
        <img src="https://img.shields.io/badge/SQLite-state%20db-003b57?style=flat&logo=sqlite&logoColor=white" alt="SQLite state db" />
        <img src="https://img.shields.io/badge/CLI-Typer-4b5563?style=flat&logo=gnubash&logoColor=white" alt="Typer CLI" />
      </td>
    </tr>
    <tr>
      <td><strong>Navigation</strong></td>
      <td>
        <a href="#quick-start"><img src="https://img.shields.io/badge/Local%20Setup-Quick%20Start-059669?style=flat&logo=serverless&logoColor=white" alt="Quick start" /></a>
        <a href="#features"><img src="https://img.shields.io/badge/Overview-Features-7c3aed?style=flat&logo=simpleicons&logoColor=white" alt="Features" /></a>
        <a href="#configuration"><img src="https://img.shields.io/badge/Config-Env-0ea5e9?style=flat&logo=gnubash&logoColor=white" alt="Configuration" /></a>
        <a href="#how-it-works"><img src="https://img.shields.io/badge/Design-How%20It%20Works-1f2937?style=flat&logo=planetscale&logoColor=white" alt="How it works" /></a>
        <a href="#icloud-origin"><img src="https://img.shields.io/badge/Origin-iCloud%2B%20Migration-0f172a?style=flat&logo=apple&logoColor=white" alt="iCloud+ origin" /></a>
        <a href="#operations"><img src="https://img.shields.io/badge/Runbook-Operations-0f766e?style=flat&logo=serverfault&logoColor=white" alt="Operations" /></a>
        <a href="#architecture"><img src="https://img.shields.io/badge/Stack-Architecture-374151?style=flat&logo=planetscale&logoColor=white" alt="Architecture" /></a>
        <a href="#troubleshooting"><img src="https://img.shields.io/badge/Help-Troubleshooting-6b7280?style=flat&logo=gnubash&logoColor=white" alt="Troubleshooting" /></a>
      </td>
    </tr>
  </table>
</div>

<a id="quick-start"></a>
<h2><img src="https://img.shields.io/badge/Quick%20Start-4%20steps-059669?style=for-the-badge&logo=serverless&logoColor=white" alt="Quick Start badge" /></h2>

1. Create a working directory (this is where `.env` and output will live).

   ```bash
   mkdir -p ~/imap-migration
   cd ~/imap-migration
   ```

2. Create a `.env` in this directory using the Configuration tables below. The repo's
   `example.env` is a template you can copy if you cloned the repo.

3. Run a dry run (evidence + sqlite only):

   ```bash
   uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration migrate --dry-run
   ```

4. When ready, run the full migration:

   ```bash
   uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration migrate
   ```

Optional helpers (same `uvx --from ...` prefix as above):
- `uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration gmail-auth`
- `uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration verify`
- `uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration report`

Version pinning: append `@<tag>` (or `@<commit>`) to the git URL, e.g.
`uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration@v0.1.0 imap-icloud-migration --help`.

<a id="features"></a>
<h2><img src="https://img.shields.io/badge/Features-Highlights-7c3aed?style=for-the-badge&logo=simpleicons&logoColor=white" alt="Features badge" /></h2>

| Feature Badge                                                                                             | Details                                                                 |
| --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| ![Evidence](https://img.shields.io/badge/Evidence-Immutable%20EML-2563eb?style=flat&logo=gnubash&logoColor=white) | Writes read-only `.eml` evidence files for every message.               |
| ![Restart](https://img.shields.io/badge/Restart-safe-sqlite-10b981?style=flat&logo=sqlite&logoColor=white)       | SQLite checkpoints allow safe resume and retries.                        |
| ![Dedupe](https://img.shields.io/badge/Dedupe-Message--ID%20%2B%20Fingerprint-0ea5e9?style=flat)                | Dedupe uses normalized Message-ID or a stable fingerprint.              |
| ![Mapping](https://img.shields.io/badge/Mapping-IMAP%20to%20Gmail-6366f1?style=flat&logo=gmail&logoColor=white)   | Maps folders to Gmail custom labels plus system labels.                  |
| ![Filter](https://img.shields.io/badge/Filter-Custom%20domain%20aliases-f97316?style=flat&logo=apple&logoColor=white) | Filter by recipient/sender headers to migrate only a specific alias. |
| ![Verify](https://img.shields.io/badge/Verify-Checksums-6b7280?style=flat&logo=gnubash&logoColor=white)          | Verify `.eml` hashes against sqlite, plus JSON summary reports.          |

<a id="icloud-origin"></a>
<h2><img src="https://img.shields.io/badge/iCloud%2B-Why%20This%20Exists-111827?style=for-the-badge&logo=apple&logoColor=white" alt="iCloud+ Origin badge" /></h2>

This tool exists because iCloud+ includes free custom domain email hosting, but moving that
mailbox elsewhere is painful. There is no one-click export to Gmail that preserves structure,
custom domain aliases, or a clear audit trail. The migration is inherently risky: you need to
read everything from IMAP, keep a verifiable copy, and ingest into Gmail in a way that can be
restarted without duplicates.

The result is a deterministic pipeline that:
- Pulls from iCloud IMAP
- Writes immutable `.eml` evidence for every message
- Tracks progress and dedupe state in sqlite
- Pushes into Gmail via official Gmail API endpoints

<a id="how-it-works"></a>
<h2><img src="https://img.shields.io/badge/How%20It%20Works-Pipeline-1f2937?style=for-the-badge&logo=planetscale&logoColor=white" alt="How It Works badge" /></h2>

1. Discover mailboxes via IMAP LIST and scan counts.
2. For each mailbox, fetch messages in UID batches using IMAP SEARCH and FETCH.
3. Parse minimal headers and compute a stable fingerprint.
4. Persist state in sqlite and write `.eml` evidence to disk (read-only files).
5. If not a dry run, enqueue work items for Gmail ingestion.
6. Gmail workers call `users.messages.import` or `users.messages.insert` with label mapping.
7. Status transitions are tracked per message: discovered -> downloaded -> imported.

<a id="configuration"></a>
<h2><img src="https://img.shields.io/badge/Configuration-Env%20Vars-0ea5e9?style=for-the-badge&logo=gnubash&logoColor=white" alt="Configuration badge" /></h2>

Configuration is validated with Pydantic Settings. All environment variables use the `MIG_`
prefix and `__` for nesting. A `.env` file is loaded automatically from the current working
directory, or pass `--env-file` to any CLI command.

### IMAP + storage (required for all runs)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_IMAP__USERNAME | yes | - | email | iCloud IMAP login (primary address or alias). |
| MIG_IMAP__APP_PASSWORD | yes | - | app-specific password | Required by iCloud for third-party IMAP access. |
| MIG_IMAP__HOST | no | imap.mail.me.com | hostname | IMAP host. |
| MIG_IMAP__PORT | no | 993 | int | IMAP port. |
| MIG_IMAP__SSL | no | true | bool | Use SSL/TLS for IMAP. |
| MIG_STORAGE__ROOT_DIR | no | ./data | path | Root output directory for evidence, state, and reports. |

### Gmail ingestion (required unless --dry-run)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_GMAIL__TARGET_USER_EMAIL | yes | - | email | Gmail/Workspace mailbox to ingest into. |
| MIG_GMAIL__CREDENTIALS_FILE | yes | - | path | OAuth client JSON (Desktop/Installed app). |
| MIG_GMAIL__TOKEN_FILE | no | .secrets/gmail-token.json | path | OAuth token cache created on first auth. |
| MIG_GMAIL__MODE | no | import | enum | Ingest endpoint: import or insert. |
| MIG_GMAIL__INTERNAL_DATE_SOURCE | no | dateHeader | enum | internalDate source: dateHeader or receivedTime. |
| MIG_GMAIL__LABEL_PREFIX | no | iCloud | string | Prefix for custom Gmail labels. |

### IMAP mailbox controls (optional)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_IMAP__FOLDER_INCLUDE | no | empty | JSON list | Only include these folders. |
| MIG_IMAP__FOLDER_EXCLUDE | no | empty | JSON list | Exclude these folders. |
| MIG_IMAP__CONNECTIONS | no | 2 | int | IMAP connection pool size (1-10). |
| MIG_IMAP__BATCH_SIZE | no | 50 | int | UIDs per fetch batch (1-500). |
| MIG_IMAP__SEARCH_QUERY | no | ALL | IMAP query | Search criteria for UID SEARCH. |

### Address filtering (optional)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_FILTER__TARGET_ADDRESSES | no | empty | JSON list or CSV | Only include messages tied to these addresses. |
| MIG_FILTER__INCLUDE_SENDER | no | true | bool | Match sender (From). |
| MIG_FILTER__INCLUDE_RECIPIENTS | no | true | bool | Match To/Cc/Bcc plus Delivered-To/X-Original-To/Envelope-To. |

### Storage overrides (optional)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_STORAGE__EVIDENCE_DIR_OVERRIDE | no | empty | path | Override evidence directory. |
| MIG_STORAGE__REPORTS_DIR_OVERRIDE | no | empty | path | Override reports directory. |
| MIG_STORAGE__SQLITE_PATH_OVERRIDE | no | empty | path | Override sqlite file path. |
| MIG_STORAGE__FINGERPRINT_BODY_BYTES | no | 4096 | int | Body bytes used for fingerprinting (0-1048576). |

### Concurrency (optional)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_CONCURRENCY__GMAIL_WORKERS | no | 10 | int | Gmail ingestion worker count (1-50). |
| MIG_CONCURRENCY__IMAP_FETCH_CONCURRENCY | no | 5 | int | Concurrent IMAP fetches per mailbox (1-50). |
| MIG_CONCURRENCY__QUEUE_MAXSIZE | no | 1000 | int | Gmail work queue size (1-10000). |

### Logging (optional)

| Name | Required | Default | Format | Description |
| --- | --- | --- | --- | --- |
| MIG_LOGGING__LEVEL | no | INFO | string | Log level (e.g., INFO, DEBUG). |
| MIG_LOGGING__JSON_LOGS | no | true | bool | Emit JSON logs when true. |

<a id="gmail-oauth"></a>
<h2><img src="https://img.shields.io/badge/Gmail-OAuth%20Setup-ea4335?style=for-the-badge&logo=gmail&logoColor=white" alt="Gmail OAuth badge" /></h2>

1. Create a Google Cloud project.
2. Enable the Gmail API.
3. Create OAuth client credentials (Desktop app / Installed app).
4. Download the JSON and point `MIG_GMAIL__CREDENTIALS_FILE` to it.
5. Run `uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration gmail-auth` to complete OAuth.

Notes:
- If your OAuth consent screen is in Testing mode, add the target user to Test users.
- The OAuth client can be owned by a different Google account than the target mailbox.
- `MIG_GMAIL__TOKEN_FILE` must be a file path, not a directory; it will be created on first run.

<a id="icloud-custom-domain"></a>
<h2><img src="https://img.shields.io/badge/iCloud%2B-Custom%20Domain%20Alias-111827?style=for-the-badge&logo=apple&logoColor=white" alt="iCloud+ Custom Domain badge" /></h2>

It is normal to authenticate IMAP using your primary iCloud address even if you primarily use
a custom domain alias in Apple Mail. To migrate only a specific alias into Gmail:

- Use your primary iCloud login + app-specific password for IMAP.
- Set `MIG_GMAIL__TARGET_USER_EMAIL` to the custom domain user.
- Filter messages with `MIG_FILTER__TARGET_ADDRESSES`.

Set `MIG_FILTER__TARGET_ADDRESSES` to a JSON list such as `["alias@yourdomain.com"]`.

Filtering matches common headers (From/To/Cc/Bcc plus Delivered-To, X-Original-To,
Envelope-To). Messages that do not reference the target address are skipped.

<a id="operations"></a>
<h2><img src="https://img.shields.io/badge/Operations-Runbook-0f766e?style=for-the-badge&logo=serverfault&logoColor=white" alt="Operations badge" /></h2>

### Output layout

All output is rooted at `MIG_STORAGE__ROOT_DIR`:

- `evidence/` contains immutable `.eml` files
- `state.sqlite3` stores message state and checkpoints
- `reports/` contains JSON summaries from `report`

### Reset and resume

- Migration is safe to resume; imported messages are tracked in sqlite.
- Use `migrate --reset` to reset skipped/failed messages and folder checkpoints.

```bash
uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration migrate --reset
```

### Verify evidence

```bash
uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration verify
```

Checks SHA-256 of `.eml` files against sqlite metadata and returns a non-zero exit code if
mismatches are found.

### Write a summary report

```bash
uvx --from git+https://github.com/andrewmaspero/imap-icloud-migration imap-icloud-migration report
```

Writes a JSON summary report into the `reports/` directory.

<a id="folder-mapping"></a>
<h2><img src="https://img.shields.io/badge/Folder%20Mapping-Gmail%20Labels-6366f1?style=for-the-badge&logo=gmail&logoColor=white" alt="Folder Mapping badge" /></h2>

- IMAP folders map to Gmail custom labels under `MIG_GMAIL__LABEL_PREFIX`.
- Common system folders also receive Gmail system labels:
  - `INBOX` -> `INBOX`
  - `Sent*` -> `SENT`
  - `Trash*` -> `TRASH`
  - `Spam*` / `Junk*` -> `SPAM`
  - `Draft*` -> `DRAFT`

<a id="dev-workflow"></a>
<h2><img src="https://img.shields.io/badge/Developer-Workflow-6366f1?style=for-the-badge&logo=git&logoColor=white" alt="Developer Workflow badge" /></h2>

From a cloned repo, run:

```bash
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run pytest
```

<a id="ci-cd"></a>
<h2><img src="https://img.shields.io/badge/CI%2FCD-Overview-1F4B99?style=for-the-badge&logo=gnubash&logoColor=white" alt="CI/CD badge" /></h2>

GitHub Actions runs the same checks as the local workflow on push and pull requests:

- `ruff check .`
- `ruff format --check .`
- `mypy src`
- `pytest`

<a id="architecture"></a>
<h2><img src="https://img.shields.io/badge/Architecture-Stack%20Map-374151?style=for-the-badge&logo=planetscale&logoColor=white" alt="Architecture badge" /></h2>

- CLI: Typer commands in `src/imap_icloud_migration/cli/`.
- IMAP: async fetchers and a connection pool in `src/imap_icloud_migration/imap/`.
- Evidence: immutable `.eml` storage in `src/imap_icloud_migration/storage/eml_store.py`.
- State: sqlite checkpoints and message state in `src/imap_icloud_migration/storage/state_db.py`.
- Gmail: OAuth + API ingest in `src/imap_icloud_migration/gmail/`.
- Orchestration: async pipeline and retry logic in `src/imap_icloud_migration/pipeline/`.

<a id="troubleshooting"></a>
<h2><img src="https://img.shields.io/badge/Troubleshooting-Common%20Issues-6b7280?style=for-the-badge&logo=gnubash&logoColor=white" alt="Troubleshooting badge" /></h2>

- Missing IMAP settings: set `MIG_IMAP__USERNAME` and `MIG_IMAP__APP_PASSWORD`.
- Gmail auth errors: confirm `MIG_GMAIL__CREDENTIALS_FILE` exists and is a Desktop app client.
- Token file errors: `MIG_GMAIL__TOKEN_FILE` must be a file path, not a directory.
- OAuth consent blocked: if in Testing mode, add the target user to Test users.
- Evidence mismatch: run `verify`, inspect the `.eml` on disk, and re-run with `--reset`.

<a id="notes"></a>
<h2><img src="https://img.shields.io/badge/Notes-Security%20%26%20Data-111827?style=for-the-badge&logo=gnubash&logoColor=white" alt="Notes badge" /></h2>

- Do not commit secrets, OAuth client JSON, or Gmail token files.
- `migration_storage/` and `MIG_STORAGE__ROOT_DIR` output are generated data.
- Evidence files are written as read-only; keep them immutable for auditability.

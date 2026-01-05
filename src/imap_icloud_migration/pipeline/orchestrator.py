"""Async orchestration for IMAP → Gmail migrations."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from imap_icloud_migration.config.settings import AppSettings
from imap_icloud_migration.gmail.client import GmailClient
from imap_icloud_migration.gmail.ingest import GmailIngester, IngestResult
from imap_icloud_migration.gmail.labels import (
    GmailLabelCache,
    folder_to_custom_label,
    folder_to_system_labels,
)
from imap_icloud_migration.imap.client import ImapFetcher, ImapPool
from imap_icloud_migration.models.state import MessageStatus
from imap_icloud_migration.models.types import GmailIngestMode, GmailInternalDateSource
from imap_icloud_migration.storage.eml_store import EMLStore
from imap_icloud_migration.storage.state_db import StateDb
from imap_icloud_migration.utils.email import AddressFilter
from imap_icloud_migration.utils.fingerprint import compute_fingerprint

logger = logging.getLogger(__name__)


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay_s: float = 0.5,
    max_delay_s: float = 20.0,
    jitter_s: float = 0.25,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Retry an async function with exponential backoff.

    Args:
        fn: Async callable to execute.
        attempts: Number of attempts before giving up.
        base_delay_s: Base delay in seconds.
        max_delay_s: Maximum delay between attempts.
        jitter_s: Random jitter added to delay.
        retry_on: Exception types to retry on.

    Returns:
        Result of the callable.

    Raises:
        BaseException: The last exception if retries are exhausted.
    """
    last_exc: BaseException | None = None
    for i in range(1, attempts + 1):
        try:
            return await fn()
        except retry_on as exc:
            last_exc = exc
            if i >= attempts:
                break
            delay = min(max_delay_s, base_delay_s * (2 ** (i - 1)))
            delay = delay + random.uniform(0, jitter_s)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


async def retry_to_thread[T](
    fn: Callable[[], T],
    *,
    attempts: int,
    base_delay_s: float = 0.5,
    max_delay_s: float = 20.0,
    jitter_s: float = 0.25,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Retry a sync function in a thread with exponential backoff.

    Args:
        fn: Sync callable to execute in a thread.
        attempts: Number of attempts before giving up.
        base_delay_s: Base delay in seconds.
        max_delay_s: Maximum delay between attempts.
        jitter_s: Random jitter added to delay.
        retry_on: Exception types to retry on.

    Returns:
        Result of the callable.
    """

    async def _call() -> T:
        """Run the provided function in a thread."""
        return await asyncio.to_thread(fn)

    return await retry_async(
        _call,
        attempts=attempts,
        base_delay_s=base_delay_s,
        max_delay_s=max_delay_s,
        jitter_s=jitter_s,
        retry_on=retry_on,
    )


@dataclass(frozen=True)
class GmailWorkItem:
    """Queue item for Gmail ingestion workers."""

    message_row_id: int
    eml_path: Path
    label_ids: list[str]


class MigrationOrchestrator:
    """Coordinates IMAP fetching, evidence storage, and Gmail ingestion."""

    def __init__(self, *, settings: AppSettings) -> None:
        """Initialize the orchestrator.

        Args:
            settings: Application settings.
        """
        self._s = settings

    async def run(self, *, dry_run: bool, reset: bool = False) -> None:
        """Run the migration pipeline.

        Args:
            dry_run: Whether to skip Gmail ingestion.
            reset: Whether to reset skipped/failed messages before running.

        Raises:
            ValueError: If required settings are missing.
        """
        settings = self._s
        if settings.imap is None:
            raise ValueError(
                "IMAP settings are missing. Set at least "
                "MIG_IMAP__USERNAME and MIG_IMAP__APP_PASSWORD.",
            )
        if not dry_run and settings.gmail is None:
            raise ValueError(
                "Gmail settings are missing. Set "
                "MIG_GMAIL__TARGET_USER_EMAIL and MIG_GMAIL__CREDENTIALS_FILE.",
            )

        console = Console()
        console.print(
            f"[bold blue]Migration starting[/bold blue] (dry_run={dry_run}, reset={reset})",
        )
        console.print(f"  [dim]Storage:[/dim] {settings.storage.root_dir}")
        console.print(f"  [dim]Database:[/dim] {settings.storage.sqlite_path}")

        settings.storage.root_dir.mkdir(parents=True, exist_ok=True)
        settings.storage.evidence_dir.mkdir(parents=True, exist_ok=True)
        settings.storage.reports_dir.mkdir(parents=True, exist_ok=True)

        db = StateDb(sqlite_path=settings.storage.sqlite_path)
        db.init_schema()

        if reset:
            with console.status("[bold yellow]Resetting skipped/failed messages...[/bold yellow]"):
                count = db.reset_skipped_and_failed()
            console.print(f"[yellow]✔[/yellow] Reset {count} messages and folder checkpoints.")

        eml_store = EMLStore(evidence_dir=settings.storage.evidence_dir)

        pool = ImapPool(
            host=settings.imap.host,
            port=settings.imap.port,
            ssl=settings.imap.ssl,
            username=settings.imap.username,
            app_password=settings.imap.app_password,
            size=settings.imap.connections,
        )

        with console.status("[bold green]Connecting to IMAP...[/bold green]"):
            await pool.connect()
        console.print(
            f"[green]✔[/green] IMAP connections established ({settings.imap.connections})",
        )

        label_cache: GmailLabelCache | None = None
        ingester: GmailIngester | None = None
        gmail_mode: GmailIngestMode | None = None
        gmail_internal_date_source: GmailInternalDateSource | None = None
        if not dry_run:
            assert settings.gmail is not None
            settings.gmail.token_file.expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with console.status("[bold green]Initializing Gmail API...[/bold green]"):
                gmail_service = GmailClient.from_settings(settings.gmail).service
                label_cache = GmailLabelCache.from_service(
                    gmail_service,
                    user_id=settings.gmail.target_user_email,
                )
                ingester = GmailIngester(
                    service=gmail_service,
                    user_id=settings.gmail.target_user_email,
                )
                gmail_mode = settings.gmail.mode
                gmail_internal_date_source = settings.gmail.internal_date_source
            console.print(
                f"[green]✔[/green] Gmail API client ready ({settings.gmail.target_user_email})",
            )

        queue: asyncio.Queue[GmailWorkItem | None] = asyncio.Queue(
            maxsize=settings.concurrency.queue_maxsize,
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            expand=True,
        )

        overall_task = progress.add_task("[bold magenta]Overall Progress", total=None)

        with progress:
            workers: list[asyncio.Task[None]] = []
            if not dry_run:
                assert ingester is not None
                assert gmail_mode is not None
                assert gmail_internal_date_source is not None
                for idx in range(settings.concurrency.gmail_workers):
                    workers.append(
                        asyncio.create_task(
                            self._gmail_worker(
                                worker_idx=idx,
                                queue=queue,
                                db=db,
                                ingester=ingester,
                                mode=gmail_mode,
                                internal_date_source=gmail_internal_date_source,
                                progress=progress,
                                overall_task=overall_task,
                            ),
                        ),
                    )

            try:
                async with pool.acquire() as client:
                    fetcher = ImapFetcher(client=client)
                    mailboxes = await fetcher.list_mailboxes()

                mailboxes = self._filter_mailboxes(mailboxes)
                if not mailboxes:
                    console.print("[yellow]⚠[/yellow] No mailboxes discovered.")
                    return

                total_emails = 0
                mailbox_counts: dict[str, int] = {}

                scan_task = progress.add_task("[cyan]Scanning mailboxes...", total=len(mailboxes))
                for mailbox in mailboxes:
                    async with pool.acquire() as client:
                        fetcher = ImapFetcher(client=client)
                        await client.select(mailbox)
                        uids = await client.uid_search(["ALL"])
                        count = len(uids)
                        mailbox_counts[mailbox] = count
                        total_emails += count
                    progress.update(scan_task, advance=1)
                progress.remove_task(scan_task)

                progress.update(overall_task, total=total_emails)

                async def _mailbox_worker(mailbox_name: str) -> None:
                    """Process a mailbox with its own progress task."""
                    mailbox_count = mailbox_counts.get(mailbox_name, 0)
                    done_in_db = db.count_folder_messages(mailbox_name)

                    mailbox_task = progress.add_task(
                        f"[blue]IMAP: {mailbox_name}",
                        total=mailbox_count,
                        completed=done_in_db,
                    )
                    progress.advance(overall_task, advance=done_in_db)

                    async with pool.acquire() as client:
                        fetcher = ImapFetcher(client=client)
                        await self._process_mailbox(
                            mailbox=mailbox_name,
                            fetcher=fetcher,
                            db=db,
                            eml_store=eml_store,
                            label_cache=label_cache,
                            queue=queue,
                            dry_run=dry_run,
                            progress=progress,
                            mb_task=mailbox_task,
                            overall_task=overall_task,
                        )
                    progress.remove_task(mailbox_task)

                mailbox_tasks = [asyncio.create_task(_mailbox_worker(mbox)) for mbox in mailboxes]
                if mailbox_tasks:
                    await asyncio.gather(*mailbox_tasks)
            finally:
                if not dry_run:
                    for _ in workers:
                        await queue.put(None)
                    await asyncio.gather(*workers, return_exceptions=True)

        await pool.logout()
        try:
            counts = db.counts_by_status()
            console.print("\n[bold green]Migration finished![/bold green]")
            for status, count in sorted(counts.items(), key=lambda kv: kv[0].value):
                console.print(f"  [dim]{status.value}:[/dim] [bold]{count}[/bold]")
        except Exception as exc:
            logger.warning("Failed to compute final counts: %r", exc)
        db.close()

    def _filter_mailboxes(self, mailboxes: list[str]) -> list[str]:
        """Apply include/exclude filters to a mailbox list.

        Args:
            mailboxes: Mailbox names.

        Returns:
            Filtered mailbox list.
        """
        imap_settings = self._s.imap
        assert imap_settings is not None

        include = {name.strip() for name in imap_settings.folder_include if name.strip()}
        exclude = {name.strip() for name in imap_settings.folder_exclude if name.strip()}

        out: list[str] = []
        for mailbox in mailboxes:
            if include and mailbox not in include:
                continue
            if mailbox in exclude:
                continue
            out.append(mailbox)
        return out

    async def _process_mailbox(
        self,
        *,
        mailbox: str,
        fetcher: ImapFetcher,
        db: StateDb,
        eml_store: EMLStore,
        label_cache: GmailLabelCache | None,
        queue: asyncio.Queue[GmailWorkItem | None],
        dry_run: bool,
        progress: Progress,
        mb_task: TaskID,
        overall_task: TaskID,
    ) -> None:
        """Process a single mailbox.

        Args:
            mailbox: Mailbox name.
            fetcher: IMAP fetch helper.
            db: State database.
            eml_store: Evidence store.
            label_cache: Gmail label cache (optional for dry-run).
            queue: Gmail work queue.
            dry_run: Whether Gmail ingestion is skipped.
            progress: Rich progress instance.
            mb_task: Mailbox task ID for progress.
            overall_task: Overall task ID for progress.
        """
        imap_settings = self._s.imap
        assert imap_settings is not None

        folder_row = db.get_folder(name=mailbox)
        start_uid = (folder_row.last_uid_seen + 1) if folder_row and folder_row.last_uid_seen else 1

        db.update_folder_checkpoint(
            name=mailbox,
            uidvalidity=folder_row.uidvalidity if folder_row else None,
            last_uid_seen=folder_row.last_uid_seen if folder_row else None,
        )

        processed = 0
        downloaded = 0
        skipped_filtered = 0
        skipped_duplicate = 0

        addr_filter = AddressFilter(
            target_addresses=frozenset(self._s.filter.target_addresses),
            include_sender=self._s.filter.include_sender,
            include_recipients=self._s.filter.include_recipients,
        )

        sem = asyncio.Semaphore(self._s.concurrency.imap_fetch_concurrency)

        async def _process_uid(uid: int, uidvalidity: int | None) -> None:
            """Process an individual UID from the mailbox."""
            nonlocal processed, downloaded, skipped_filtered, skipped_duplicate

            async with sem:

                async def _fetch() -> bytes:
                    """Fetch RFC822 bytes with retries."""
                    return await fetcher.fetch_rfc822(uid=uid)

                try:
                    raw = await retry_async(_fetch, attempts=5)
                except Exception as exc:
                    logger.error("Failed to fetch UID %s from %s: %r", uid, mailbox, exc)
                    progress.advance(mb_task)
                    progress.advance(overall_task)
                    return

            processed += 1
            progress.advance(mb_task)

            fp = compute_fingerprint(raw, body_bytes=self._s.storage.fingerprint_body_bytes)
            msg_row = db.upsert_message_discovered(
                folder=mailbox,
                uid=uid,
                uidvalidity=uidvalidity,
                message_id_norm=fp.message_id_norm,
                fingerprint=fp.fingerprint,
                size_bytes=len(raw),
            )

            if msg_row.status == MessageStatus.imported:
                progress.advance(overall_task)
                return

            if not addr_filter.matches(fp.headers):
                db.mark_skipped_filtered(
                    message_id=msg_row.id,
                    reason=(
                        f"Filtered out by target_addresses={self._s.filter.target_addresses!r}"
                    ),
                )
                skipped_filtered += 1
                progress.advance(overall_task)
                return

            existing = db.find_existing_imported(
                message_id_norm=fp.message_id_norm,
                fingerprint=fp.fingerprint,
            )
            if existing is not None and existing != msg_row.id:
                db.mark_skipped_duplicate(
                    message_id=msg_row.id,
                    reason=f"Duplicate of imported row id={existing}",
                )
                skipped_duplicate += 1
                progress.advance(overall_task)
                return

            written = eml_store.write_immutable(
                folder=mailbox,
                uidvalidity=uidvalidity,
                uid=uid,
                raw_rfc822=raw,
            )
            db.mark_downloaded(
                message_id=msg_row.id,
                eml_path=written.path,
                eml_sha256=written.sha256,
            )
            downloaded += 1

            if dry_run:
                progress.advance(overall_task)
                return

            assert label_cache is not None
            gmail_settings = self._s.gmail
            assert gmail_settings is not None
            label_ids: list[str] = []
            for sys_label in folder_to_system_labels(mailbox):
                label_ids.append(sys_label.value)

            custom_name = folder_to_custom_label(
                prefix=gmail_settings.label_prefix,
                folder=mailbox,
            )
            custom_id = label_cache.ensure(name=custom_name)
            label_ids.append(custom_id)

            await queue.put(
                GmailWorkItem(
                    message_row_id=msg_row.id,
                    eml_path=written.path,
                    label_ids=sorted(set(label_ids)),
                ),
            )

        async for batch in fetcher.iter_uid_batches(
            mailbox=mailbox,
            start_uid=start_uid,
            batch_size=imap_settings.batch_size,
            search_query=imap_settings.search_query,
        ):
            current_folder = db.get_folder(name=mailbox)
            db.update_folder_checkpoint(
                name=mailbox,
                uidvalidity=batch.uidvalidity,
                last_uid_seen=current_folder.last_uid_seen if current_folder else None,
            )

            tasks = [_process_uid(uid, batch.uidvalidity) for uid in batch.uids]
            if tasks:
                await asyncio.gather(*tasks)

            if batch.uids:
                max_uid = max(batch.uids)
                db.update_folder_checkpoint(
                    name=mailbox,
                    uidvalidity=batch.uidvalidity,
                    last_uid_seen=max_uid,
                )

    async def _gmail_worker(
        self,
        *,
        worker_idx: int,
        queue: asyncio.Queue[GmailWorkItem | None],
        db: StateDb,
        ingester: GmailIngester,
        mode: GmailIngestMode,
        internal_date_source: GmailInternalDateSource,
        progress: Progress,
        overall_task: TaskID,
    ) -> None:
        """Background worker consuming Gmail ingestion tasks."""
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return

                res = await retry_to_thread(
                    _ingest_call(
                        item=item,
                        ingester=ingester,
                        mode=mode,
                        internal_date_source=internal_date_source,
                    ),
                    attempts=5,
                )

                db.mark_imported(
                    message_id=item.message_row_id,
                    gmail_message_id=res.gmail_message_id,
                    gmail_thread_id=res.gmail_thread_id,
                    label_ids=item.label_ids,
                )
                progress.advance(overall_task)
            except Exception as exc:
                if item is not None:
                    db.mark_failed(
                        message_id=item.message_row_id,
                        error=f"[gmail_worker={worker_idx}] {exc!r}",
                    )
                progress.advance(overall_task)
            finally:
                queue.task_done()


def _ingest_call(
    *,
    item: GmailWorkItem,
    ingester: GmailIngester,
    mode: GmailIngestMode,
    internal_date_source: GmailInternalDateSource,
) -> Callable[[], IngestResult]:
    """Build a callable for Gmail ingestion to use with retry helpers."""

    def _call() -> IngestResult:
        """Invoke Gmail ingestion for a single work item."""
        return ingester.ingest_eml(
            eml_path=item.eml_path,
            label_ids=item.label_ids,
            mode=mode,
            internal_date_source=internal_date_source,
        )

    return _call

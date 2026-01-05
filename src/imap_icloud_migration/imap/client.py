"""IMAP client wrappers and mailbox fetching helpers."""

from __future__ import annotations

import asyncio
import imaplib
import logging
import re
import shlex
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aioimaplib

_LIST_MAILBOX_RE = re.compile(
    rb'^\* LIST \([^\)]*\)\s+(?P<delim>NIL|"[^"]*"|[^\s]+)\s+(?P<name>.+)$',
)
_LITERAL_RE = re.compile(rb"^\{(?P<n>\d+)\}$")
_FETCH_LITERAL_RE = re.compile(rb"\{(?P<n>\d+)\}$")
_UIDVALIDITY_RE = re.compile(rb"\[UIDVALIDITY (?P<uidvalidity>\d+)\]")
_UIDNEXT_RE = re.compile(rb"\[UIDNEXT (?P<uidnext>\d+)\]")
_EXISTS_RE = re.compile(rb"(?i)\* (?P<exists>\d+) EXISTS")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SelectInfo:
    """IMAP SELECT response metadata."""

    mailbox: str
    uidvalidity: int | None
    uidnext: int | None
    exists: int | None


class ImapError(RuntimeError):
    """Raised for IMAP command errors."""


class ImapClient:
    """Async IMAP client with basic helpers."""

    def __init__(self, *, host: str, port: int, ssl: bool, timeout_seconds: float = 120.0) -> None:
        """Initialize the IMAP client.

        Args:
            host: IMAP host.
            port: IMAP port.
            ssl: Whether to use SSL.
            timeout_seconds: Network timeout for IMAP operations.
        """
        self._host = host
        self._port = port
        self._ssl = ssl
        self._timeout = timeout_seconds
        self._imap: aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Connect to the IMAP server."""
        async with self._lock:
            if self._imap is not None:
                return
            if self._ssl:
                self._imap = aioimaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout)
            else:
                self._imap = aioimaplib.IMAP4(self._host, self._port, timeout=self._timeout)
            await asyncio.wait_for(self._imap.wait_hello_from_server(), timeout=self._timeout)

    async def login(self, *, username: str, app_password: str) -> None:
        """Login to the IMAP server.

        Args:
            username: IMAP username.
            app_password: IMAP app-specific password.

        Raises:
            ImapError: If authentication fails.
        """
        async with self._lock:
            imap = self._require()
            resp = await asyncio.wait_for(imap.login(username, app_password), timeout=self._timeout)
            if resp.result != "OK":
                raise ImapError(f"IMAP login failed: {resp.result} {resp.lines!r}")

    async def logout(self) -> None:
        """Logout and close the IMAP connection."""
        async with self._lock:
            if self._imap is None:
                return
            try:
                await self._imap.logout()
            finally:
                self._imap = None

    async def list_mailboxes(self) -> list[str]:
        """List available IMAP mailboxes.

        Returns:
            List of mailbox names.

        Raises:
            ImapError: If the LIST command fails.
        """
        async with self._lock:
            imap = self._require()
            resp = await asyncio.wait_for(imap.list('""', "*"), timeout=self._timeout)
            if resp.result != "OK":
                raise ImapError(f"IMAP LIST failed: {resp.result} {resp.lines!r}")
            mailboxes = _parse_list_response(resp.lines)
            if not mailboxes:
                logger.debug("IMAP LIST raw lines: %r", resp.lines)
            return mailboxes

    async def select(self, mailbox: str) -> SelectInfo:
        """Select a mailbox and return metadata.

        Args:
            mailbox: Mailbox name.

        Returns:
            SelectInfo with UIDVALIDITY and EXISTS info.

        Raises:
            ImapError: If the SELECT command fails.
        """
        async with self._lock:
            imap = self._require()
            mbx = _imap_quote(mailbox)
            resp = await asyncio.wait_for(imap.select(mbx), timeout=self._timeout)
            if resp.result != "OK":
                raise ImapError(f"IMAP SELECT failed ({mailbox}): {resp.result} {resp.lines!r}")

            uidvalidity: int | None = None
            uidnext: int | None = None
            exists: int | None = None

            for line in resp.lines:
                match = _UIDVALIDITY_RE.search(line)
                if match:
                    uidvalidity = int(match.group("uidvalidity"))
                match = _UIDNEXT_RE.search(line)
                if match:
                    uidnext = int(match.group("uidnext"))
                match = _EXISTS_RE.search(line)
                if match:
                    exists = int(match.group("exists"))

            return SelectInfo(
                mailbox=mailbox,
                uidvalidity=uidvalidity,
                uidnext=uidnext,
                exists=exists,
            )

    async def uid_search(
        self,
        criteria: Iterable[str],
        *,
        charset: str | None = None,
    ) -> list[int]:
        """Run UID SEARCH and return matching UIDs.

        Args:
            criteria: IMAP search criteria.
            charset: Optional charset for SEARCH.

        Returns:
            List of matching UIDs.

        Raises:
            ImapError: If the SEARCH command fails.
        """
        async with self._lock:
            imap = self._require()
            if charset is None:
                coro = imap.protocol.search(*criteria, by_uid=True)
            else:
                coro = imap.protocol.search(*criteria, charset=charset, by_uid=True)
            resp = await asyncio.wait_for(coro, timeout=self._timeout)
            if resp.result != "OK":
                raise ImapError(f"IMAP UID SEARCH failed: {resp.result} {resp.lines!r}")

            uids: list[int] = []
            for line in resp.lines:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == b"*" and parts[1] == b"SEARCH":
                    parts = parts[2:]

                if parts and all(p.isdigit() for p in parts):
                    uids.extend(int(p) for p in parts)

            if uids:
                return uids

            logger.debug(
                "IMAP UID SEARCH returned no matches (criteria=%s, lines=%r)",
                list(criteria),
                resp.lines,
            )
            return []

    async def uid_fetch_rfc822(self, uid: int) -> bytes:
        """Fetch raw RFC822 bytes for a UID.

        Args:
            uid: Message UID.

        Returns:
            Raw RFC822 bytes.

        Raises:
            ImapError: If the FETCH command fails.
        """
        async with self._lock:
            imap = self._require()
            resp = await asyncio.wait_for(
                imap.uid("FETCH", str(uid), "(BODY.PEEK[])"),
                timeout=self._timeout,
            )
            if resp.result != "OK":
                raise ImapError(f"IMAP UID FETCH failed: {resp.result} {resp.lines!r}")
            return _extract_literal(resp.lines)

    def _require(self) -> aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL:
        """Return the underlying IMAP client or raise if not connected."""
        if self._imap is None:
            raise ImapError("IMAP client not connected")
        return self._imap


class ImapPool:
    """Connection pool for IMAP clients."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        ssl: bool,
        username: str,
        app_password: str,
        size: int,
    ) -> None:
        """Initialize the IMAP client pool.

        Args:
            host: IMAP host.
            port: IMAP port.
            ssl: Whether to use SSL.
            username: IMAP username.
            app_password: IMAP app-specific password.
            size: Pool size.
        """
        self._host = host
        self._port = port
        self._ssl = ssl
        self._username = username
        self._app_password = app_password
        self._size = size
        self._clients: list[ImapClient] = []
        self._queue: asyncio.Queue[ImapClient] = asyncio.Queue()
        self._connected = False

    async def connect(self) -> None:
        """Connect all IMAP clients in the pool."""
        if self._connected:
            return
        for _ in range(self._size):
            client = ImapClient(host=self._host, port=self._port, ssl=self._ssl)
            await client.connect()
            await client.login(username=self._username, app_password=self._app_password)
            self._clients.append(client)
            await self._queue.put(client)
        self._connected = True

    async def logout(self) -> None:
        """Logout all IMAP clients and clear the pool."""
        for client in self._clients:
            await client.logout()
        self._clients.clear()
        self._connected = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[ImapClient]:
        """Acquire an IMAP client from the pool."""
        client = await self.get_client()
        try:
            yield client
        finally:
            await self.release_client(client)

    async def get_client(self) -> ImapClient:
        """Get a client from the pool queue."""
        return await self._queue.get()

    async def release_client(self, client: ImapClient) -> None:
        """Return a client to the pool queue."""
        await self._queue.put(client)


@dataclass(frozen=True)
class FolderBatch:
    """Batch of UIDs for a mailbox."""

    mailbox: str
    uidvalidity: int | None
    uids: list[int]


class ImapFetcher:
    """High-level IMAP fetch helpers built on ImapClient."""

    def __init__(self, *, client: ImapClient) -> None:
        """Initialize the fetcher.

        Args:
            client: Connected ImapClient instance.
        """
        self._client = client

    async def list_mailboxes(self) -> list[str]:
        """List mailboxes using the underlying client."""
        return await self._client.list_mailboxes()

    async def iter_uid_batches(
        self,
        *,
        mailbox: str,
        start_uid: int,
        batch_size: int,
        search_query: str = "ALL",
    ) -> AsyncIterator[FolderBatch]:
        """Yield UID batches for a mailbox.

        Args:
            mailbox: Mailbox name.
            start_uid: UID to start from.
            batch_size: Number of UIDs per batch.
            search_query: IMAP search query string.

        Yields:
            FolderBatch items.
        """
        select_info: SelectInfo = await self._client.select(mailbox)

        try:
            criteria = shlex.split(search_query) if search_query.strip() else ["ALL"]
        except ValueError:
            criteria = ["ALL"]

        uids = await self._client.uid_search(criteria)
        if start_uid > 1:
            uids = [uid for uid in uids if uid >= start_uid]
        uids.sort()

        for idx in range(0, len(uids), batch_size):
            batch = uids[idx : idx + batch_size]
            yield FolderBatch(mailbox=mailbox, uidvalidity=select_info.uidvalidity, uids=batch)

    async def fetch_rfc822(self, *, uid: int) -> bytes:
        """Fetch RFC822 bytes for a UID."""
        return await self._client.uid_fetch_rfc822(uid)


def _extract_literal(lines: list[bytes]) -> bytes:
    """Extract the literal payload from an IMAP FETCH response.

    Args:
        lines: IMAP response lines.

    Returns:
        Literal payload bytes.

    Raises:
        ImapError: If no literal payload can be extracted.
    """
    if not lines:
        raise ImapError("IMAP response had no lines")

    for idx, line in enumerate(lines):
        match = _FETCH_LITERAL_RE.search(line)
        if not match:
            continue
        size = int(match.group("n"))
        if idx + 1 >= len(lines):
            break
        literal = lines[idx + 1]
        if len(literal) == size:
            return bytes(literal)

    candidates = [
        line for line in lines if b"FETCH" not in line and line.strip() not in {b")", b""}
    ]
    literal = max(candidates or lines, key=len)
    if not literal or len(literal) < 64:
        raise ImapError(f"IMAP response contained no literal payload: {lines!r}")
    return bytes(literal)


def _parse_list_response(lines: list[bytes]) -> list[str]:
    """Parse mailbox names from an IMAP LIST response.

    Args:
        lines: IMAP LIST response lines.

    Returns:
        Mailbox names.
    """
    out: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith(b"+"):
            idx += 1
            continue
        if line.startswith(b"("):
            line = b"* LIST " + line
        match = _LIST_MAILBOX_RE.match(line)
        if not match:
            idx += 1
            continue

        name_token = match.group("name").strip()
        if b'"' in name_token:
            first_quote = name_token.find(b'"')
            if first_quote != -1:
                second_quote = name_token.find(b'"', first_quote + 1)
                if second_quote != -1:
                    last_quote = name_token.rfind(b'"')
                    if last_quote > first_quote:
                        name_token = name_token[first_quote : last_quote + 1]
        else:
            parts = name_token.split()
            if parts:
                name_token = parts[-1]

        literal_match = _LITERAL_RE.match(name_token)
        if literal_match:
            if idx + 1 >= len(lines):
                break
            raw_name = lines[idx + 1].strip()
            idx += 2
        else:
            raw_name = name_token
            idx += 1

        name = _decode_mailbox_name(raw_name)
        if name:
            out.append(name)

    seen: set[str] = set()
    result: list[str] = []
    for name in out:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _decode_mailbox_name(raw: bytes) -> str:
    """Decode an IMAP mailbox name with modified UTF-7 if needed.

    Args:
        raw: Raw mailbox token.

    Returns:
        Decoded mailbox name, or empty string if invalid.
    """
    value = raw.strip()
    if not value or value.upper() == b"NIL":
        return ""

    if value.startswith(b'"') and value.endswith(b'"') and len(value) >= 2:
        value = value[1:-1]
        value = value.replace(b'\\"', b'"').replace(b"\\\\", b"\\")

    decoded = value.decode("ascii", errors="replace")
    decoder = getattr(imaplib, "DecodeUTF7", None)
    if callable(decoder):
        try:
            return str(decoder(decoded))
        except Exception:
            return decoded
    return decoded


def _imap_quote(value: str) -> str:
    """Quote a string for use in IMAP commands.

    Args:
        value: Raw mailbox name.

    Returns:
        Quoted string safe for IMAP commands.
    """
    stripped = value.strip()
    if not stripped:
        return '""'
    escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

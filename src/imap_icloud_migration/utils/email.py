"""Email parsing, normalization, and address filtering utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

_HEADER_BODY_SPLIT_RE = re.compile(rb"\r?\n\r?\n")


def extract_email_addresses(value: str | None) -> set[str]:
    """Extract normalized email addresses from a header value.

    Args:
        value: Raw header value, potentially including display names.

    Returns:
        A set of lowercased email addresses.
    """
    if not value:
        return set()
    return {addr.strip().lower() for _, addr in getaddresses([value]) if addr and addr.strip()}


def _decode_header_value(value: str) -> str:
    """Decode RFC 2047-encoded header values.

    Args:
        value: Raw header value.

    Returns:
        Best-effort decoded value.
    """
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def normalize_message_id(value: str | None) -> str | None:
    """Normalize a Message-ID for stable comparisons.

    Args:
        value: Raw Message-ID header value.

    Returns:
        Normalized Message-ID in angle brackets, or None if missing/invalid.
    """
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None

    if " " in v:
        v = v.split(" ", 1)[0].strip()
    if v.startswith("<") and v.endswith(">"):
        v = v[1:-1].strip()
    if not v:
        return None
    return f"<{v.lower()}>"


@dataclass(frozen=True)
class MinimalHeaders:
    """Minimal set of headers used for fingerprinting and filtering."""

    date_raw: str | None
    date_dt_iso: str | None
    from_: str | None
    to: str | None
    cc: str | None
    bcc: str | None
    delivered_to: str | None
    x_original_to: str | None
    envelope_to: str | None
    subject: str | None
    message_id_norm: str | None


def parse_minimal_headers(raw_rfc822: bytes) -> MinimalHeaders:
    """Parse a minimal set of headers from raw RFC822 bytes.

    Args:
        raw_rfc822: Raw RFC822 message bytes.

    Returns:
        Parsed header values with best-effort decoding.
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw_rfc822)

    date_raw = msg.get("Date")
    date_dt_iso: str | None = None
    if date_raw:
        try:
            date_dt_iso = parsedate_to_datetime(date_raw).isoformat()
        except Exception:
            date_dt_iso = None

    from_raw = msg.get("From")
    to_raw = msg.get("To")
    cc_raw = msg.get("Cc")
    bcc_raw = msg.get("Bcc")
    delivered_to_raw = msg.get("Delivered-To")
    x_original_to_raw = msg.get("X-Original-To")
    envelope_to_raw = msg.get("Envelope-To")
    subj_raw = msg.get("Subject")
    mid_raw = msg.get("Message-ID")

    return MinimalHeaders(
        date_raw=_decode_header_value(date_raw) if date_raw else None,
        date_dt_iso=date_dt_iso,
        from_=_decode_header_value(from_raw) if from_raw else None,
        to=_decode_header_value(to_raw) if to_raw else None,
        cc=_decode_header_value(cc_raw) if cc_raw else None,
        bcc=_decode_header_value(bcc_raw) if bcc_raw else None,
        delivered_to=_decode_header_value(delivered_to_raw) if delivered_to_raw else None,
        x_original_to=_decode_header_value(x_original_to_raw) if x_original_to_raw else None,
        envelope_to=_decode_header_value(envelope_to_raw) if envelope_to_raw else None,
        subject=_decode_header_value(subj_raw) if subj_raw else None,
        message_id_norm=normalize_message_id(mid_raw),
    )


def body_prefix(raw_rfc822: bytes, *, max_bytes: int) -> bytes:
    """Extract up to N bytes of the message body for fingerprinting.

    Args:
        raw_rfc822: Raw RFC822 message bytes.
        max_bytes: Maximum number of bytes to return.

    Returns:
        The body prefix, or raw prefix if the header/body split is not found.
    """
    if max_bytes <= 0:
        return b""
    match = _HEADER_BODY_SPLIT_RE.search(raw_rfc822)
    if not match:
        return raw_rfc822[:max_bytes]
    start = match.end()
    return raw_rfc822[start : start + max_bytes]


@dataclass(frozen=True)
class AddressFilter:
    """Filter logic for selecting messages by address headers."""

    target_addresses: frozenset[str]
    include_sender: bool = True
    include_recipients: bool = True

    def matches(self, headers: MinimalHeaders) -> bool:
        """Return True if the headers match the configured target addresses.

        Args:
            headers: Parsed minimal headers for a message.

        Returns:
            True if the message should be included, otherwise False.
        """
        targets = self.target_addresses
        if not targets:
            return True

        if self.include_sender:
            if extract_email_addresses(headers.from_) & targets:
                return True

        if self.include_recipients:
            candidates: set[str] = set()
            candidates |= extract_email_addresses(headers.to)
            candidates |= extract_email_addresses(headers.cc)
            candidates |= extract_email_addresses(headers.bcc)
            candidates |= extract_email_addresses(headers.delivered_to)
            candidates |= extract_email_addresses(headers.x_original_to)
            candidates |= extract_email_addresses(headers.envelope_to)
            if candidates & targets:
                return True

        return False

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from discord.ext import tasks

log = logging.getLogger(__name__)

# MU's downloadpm CSV renders timestamps in US Pacific (DST-aware: PST/PDT).
PACIFIC = ZoneInfo("America/Los_Angeles")
_CSV_DATE_FMT = "%Y-%m-%d %H:%M"

DISCORD_LIMIT = 2000


def parse_pm_csv(text: str) -> list[dict]:
    """Parse a downloadpm CSV into Inbox rows, newest-first order preserved.

    Each row is ``{date, title, sender, bbcode}`` where ``date`` is a timezone-aware
    Pacific datetime. Only ``Folder == "Inbox"`` rows are returned. Message bodies
    contain commas, quotes, and newlines, so this uses the csv module rather than
    naive splitting.
    """
    if not text or not text.strip():
        return []
    rows: list[dict] = []
    for raw in csv.DictReader(io.StringIO(text)):
        if (raw.get("Folder") or "").strip() != "Inbox":
            continue
        date_str = (raw.get("Date") or "").strip()
        try:
            date = datetime.strptime(date_str, _CSV_DATE_FMT).replace(tzinfo=PACIFIC)
        except ValueError:
            log.warning("PM CSV: unparseable date %r; skipping row", date_str)
            continue
        rows.append({
            "date": date,
            "title": (raw.get("Title") or "").strip(),
            "sender": (raw.get("From") or "").strip(),
            "bbcode": raw.get("Message") or "",
        })
    return rows


def bbcode_to_text(text: str) -> str:
    """Reduce a PM's BBCode body to clean plain text for a Discord code block.

    Drops [QUOTE]/[QUOTE=Name] blocks entirely (on MU's export these hold the old
    quoted conversation), then strips every remaining tag, keeping the visible
    text. No markdown is produced — the result is shown verbatim in a code block.
    """
    if not text:
        return ""

    # Drop quote blocks and their contents, innermost-first so nesting is handled.
    quote_block = re.compile(r"\[QUOTE(?:=[^\]]*)?\](?:(?!\[QUOTE).)*?\[/QUOTE\]", re.S | re.I)
    while quote_block.search(text):
        text = quote_block.sub("", text)

    # BOX=Label keeps its label as a plain heading line above the contents.
    text = re.sub(r"\[BOX=([^\]]*)\](.*?)\[/BOX\]",
                  lambda m: f"\n{m.group(1).strip()}\n{m.group(2).strip()}\n",
                  text, flags=re.S | re.I)

    # Strip all remaining tags (TITLE, CENTER, B, COLOR, ...), keeping contents.
    text = re.sub(r"\[/?[A-Za-z][^\]]*\]", "", text)

    # Collapse whitespace-only lines and runs of blank lines left by removed blocks.
    text = re.sub(r"\n[ \t]*\n[ \t\n]*", "\n\n", text)
    return text.strip()


def format_pm_message(sender: str, title: str, bbcode: str) -> str:
    """Build the Discord message for a forwarded PM, truncated to fit the limit.

    Header is a single line (``From: X - Subject: Y``); the plain-text body follows
    in a fenced code block. If the body is empty (e.g. the PM was only quoted text),
    the code block is omitted.
    """
    header = f"**From:** {sender} - **Subject:** {title}"
    body = bbcode_to_text(bbcode)
    if not body:
        return header

    # Reserve room for the header, the code fences, and a possible truncation note.
    fences = "\n```\n" + "{}" + "\n```"
    marker = "\n… (truncated)"
    overhead = len(header) + len(fences.format(""))
    budget = DISCORD_LIMIT - overhead
    if len(body) > budget:
        body = body[: budget - len(marker)] + marker
    return header + fences.format(body)


class PMMonitor:
    """Polls the MU PM inbox (via the downloadpm CSV export) and forwards PMs that
    arrived after monitoring started to a Discord channel.

    "New" is decided by timestamp: ``start()`` records a UTC cutoff, and each tick
    forwards Inbox rows whose (Pacific) date is at or after that cutoff. A small
    seen-set keyed on (date, sender, title) prevents reposting the same row on
    later ticks. Reading the CSV never opens individual PMs, so MU read/unread
    state is left untouched. State is in-process only and not persisted.
    """

    def __init__(self, *, bot, mu_client, interval_seconds: int = 60):
        self.bot = bot
        self.mu_client = mu_client
        self.destination_channel_id: int | None = None
        self.cutoff: datetime | None = None
        self.seen_keys: set[tuple] = set()
        self.forwarded_count = 0
        self._loop = tasks.loop(seconds=interval_seconds)(self._tick)

    @property
    def is_running(self) -> bool:
        return self._loop.is_running()

    def status(self) -> str:
        if not self.is_running:
            return "PM monitoring is **off**. Use `!monitor #channel` to start."
        return (
            f"PM monitoring is **on** → <#{self.destination_channel_id}>. "
            f"Forwarded {self.forwarded_count} PM(s) since it started."
        )

    async def start(self, destination_channel_id: int) -> None:
        """Set the destination, record the cutoff time, and start the loop."""
        if self.is_running:
            self._loop.cancel()
        self.destination_channel_id = destination_channel_id
        self.cutoff = datetime.now(timezone.utc)
        self.seen_keys = set()
        self.forwarded_count = 0
        self._loop.start()

    def stop(self) -> None:
        self._loop.cancel()
        self.destination_channel_id = None
        self.cutoff = None
        self.seen_keys = set()

    async def _tick(self) -> None:
        try:
            text = await asyncio.to_thread(self.mu_client.fetch_pm_csv)
            rows = parse_pm_csv(text)
        except Exception:
            log.exception("PMMonitor: failed to fetch/parse PM CSV")
            return

        channel = self.bot.get_channel(self.destination_channel_id)
        # Oldest-first so multiple new PMs post in chronological order.
        for row in sorted(rows, key=lambda r: r["date"]):
            if self.cutoff is not None and row["date"] < self.cutoff:
                continue
            key = (row["date"], row["sender"], row["title"])
            if key in self.seen_keys:
                continue

            message = format_pm_message(row["sender"], row["title"], row["bbcode"])
            try:
                if channel is None:
                    channel = self.bot.get_channel(self.destination_channel_id)
                await channel.send(message)
            except Exception:
                # Leave unseen so a transient Discord failure retries next tick.
                log.exception("PMMonitor: failed to post PM to Discord (%s)", row["title"])
                continue
            self.seen_keys.add(key)
            self.forwarded_count += 1

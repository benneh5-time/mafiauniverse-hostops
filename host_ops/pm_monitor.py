from __future__ import annotations

import asyncio
import logging
import re

from bs4 import BeautifulSoup
from discord.ext import tasks

log = logging.getLogger(__name__)

_PMID_RE = re.compile(r"pm_(\d+)")
# MU's quick-reply textarea pre-fills the body wrapped as [QUOTE=Author]...[/QUOTE].
_OUTER_QUOTE_RE = re.compile(r"^\s*\[QUOTE=[^\]]*\](.*)\[/QUOTE\]\s*$", re.S | re.I)

DISCORD_LIMIT = 2000


def parse_unread_pmids(html: str) -> list[int]:
    """Return pmids of unread messages on an inbox page, in page (newest-first) order.

    Unread messages carry ``<span class="unread">`` around the title link; read
    ones use a plain ``<span>``.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    ids: list[int] = []
    for li in soup.find_all("li", class_="pmbit"):
        title_span = li.find("span", class_="unread")
        if not title_span:
            continue
        m = _PMID_RE.search(str(li.get("id", "")))
        if m:
            ids.append(int(m.group(1)))
    return ids


def parse_pm_detail(html: str) -> dict:
    """Extract ``author``, ``subject``, and ``bbcode`` from a showpm page.

    The raw BBCode is read from MU's quick-reply textarea (already unescaped)
    with the outer ``[QUOTE=author]...[/QUOTE]`` wrapper stripped.
    """
    soup = BeautifulSoup(html, "html.parser")

    author = ""
    username = soup.select_one(".userinfo .username")
    if username:
        author = username.get_text(" ", strip=True)

    subject = ""
    title = soup.select_one("h2.title")
    if title:
        subject = title.get_text(" ", strip=True)
    elif soup.title:
        subject = soup.title.get_text(strip=True)

    bbcode = ""
    textarea = soup.find("textarea", {"name": "message"})
    if textarea:
        bbcode = textarea.get_text()
        m = _OUTER_QUOTE_RE.match(bbcode)
        if m:
            bbcode = m.group(1)
        bbcode = bbcode.strip()

    return {"author": author, "subject": subject, "bbcode": bbcode}


def bbcode_to_markdown(text: str) -> str:
    """Convert the common BBCode tags seen in host PMs to light Discord markdown.

    Bold/italic/underline map to their markdown equivalents; TITLE and BOX become
    bold header lines; every other tag is stripped with its contents preserved.
    """
    if not text:
        return ""

    # BOX=Label -> bold label header line, then contents.
    text = re.sub(r"\[BOX=([^\]]*)\](.*?)\[/BOX\]",
                  lambda m: f"\n**{m.group(1).strip()}**\n{m.group(2).strip()}\n",
                  text, flags=re.S | re.I)
    # TITLE (optionally TITLE=color) -> bold header line.
    text = re.sub(r"\[TITLE(?:=[^\]]*)?\](.*?)\[/TITLE\]",
                  lambda m: f"\n**{m.group(1).strip()}**\n",
                  text, flags=re.S | re.I)

    text = re.sub(r"\[B\](.*?)\[/B\]", r"**\1**", text, flags=re.S | re.I)
    text = re.sub(r"\[I\](.*?)\[/I\]", r"*\1*", text, flags=re.S | re.I)
    text = re.sub(r"\[U\](.*?)\[/U\]", r"__\1__", text, flags=re.S | re.I)

    # Strip any remaining tags (CENTER, QUOTE, COLOR, etc.), keeping contents.
    text = re.sub(r"\[/?[A-Za-z][^\]]*\]", "", text)

    # Collapse runs of blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_pm_message(author: str, subject: str, bbcode: str) -> str:
    """Build the Discord message for a forwarded PM, truncated to fit the limit."""
    body = bbcode_to_markdown(bbcode)
    header = f"**From:** {author}\n**Subject:** {subject}\n\n"
    message = header + body
    if len(message) > DISCORD_LIMIT:
        marker = "\n… (truncated)"
        message = message[: DISCORD_LIMIT - len(marker)] + marker
    return message


class PMMonitor:
    """Polls the MU PM inbox and forwards newly-arrived unread PMs to a channel.

    State is in-process only: the destination channel, the set of pmids already
    handled this session, and a forwarded counter. Nothing is persisted and MU's
    read state is never changed. Starting captures the current unread pmids as a
    silent baseline so the existing backlog is not forwarded.
    """

    def __init__(self, *, bot, mu_client, interval_seconds: int = 60):
        self.bot = bot
        self.mu_client = mu_client
        self.destination_channel_id: int | None = None
        self.seen_pmids: set[int] = set()
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
            f"Forwarded {self.forwarded_count} PM(s) this session."
        )

    async def start(self, destination_channel_id: int) -> None:
        """Set the destination, baseline current unread PMs, and start the loop."""
        if self.is_running:
            self._loop.cancel()
        self.destination_channel_id = destination_channel_id
        self.seen_pmids = set()
        self.forwarded_count = 0
        try:
            html = await asyncio.to_thread(self.mu_client.fetch_pm_inbox_page, 1)
            self.seen_pmids = set(parse_unread_pmids(html))
        except Exception:
            log.exception("PMMonitor: failed to baseline inbox on start")
        self._loop.start()

    def stop(self) -> None:
        self._loop.cancel()
        self.destination_channel_id = None
        self.seen_pmids = set()

    async def _tick(self) -> None:
        try:
            html = await asyncio.to_thread(self.mu_client.fetch_pm_inbox_page, 1)
            unread = parse_unread_pmids(html)
        except Exception:
            log.exception("PMMonitor: failed to fetch/parse inbox page")
            return

        channel = self.bot.get_channel(self.destination_channel_id)
        for pmid in unread:
            if pmid in self.seen_pmids:
                continue
            try:
                detail_html = await asyncio.to_thread(self.mu_client.fetch_pm, pmid)
                detail = parse_pm_detail(detail_html)
            except Exception:
                log.exception("PMMonitor: failed to fetch/parse PM %s; skipping", pmid)
                self.seen_pmids.add(pmid)  # don't retry a broken PM forever
                continue

            message = format_pm_message(detail["author"], detail["subject"], detail["bbcode"])
            try:
                if channel is None:
                    channel = self.bot.get_channel(self.destination_channel_id)
                await channel.send(message)
            except Exception:
                # Leave unseen so a transient Discord failure retries next tick.
                log.exception("PMMonitor: failed to post PM %s to Discord", pmid)
                continue
            self.seen_pmids.add(pmid)
            self.forwarded_count += 1

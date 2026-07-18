from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import discord

from ..resolver import extract_quote_author
from .rolepm import ROLEPM_CHANNEL_ID

log = logging.getLogger(__name__)

# Directory where exported spreadsheets are written (created if missing).
EXPORT_DIR = Path("data")

# Politeness delay between per-post getquotes calls, in seconds.
POST_FETCH_DELAY = 0.4

# Thread id from a MU thread URL, e.g. /threads/60309-Some-Title or /threads/60309/
# or ?t=60309. Falls back to a bare number.
_THREAD_ID_RE = re.compile(r"(?:threads/|[?&]t=)(\d+)")

# Outer quote wrapper MU adds around a fetched post: [QUOTE=author;postid] ... [/QUOTE]
_QUOTE_OPEN_RE = re.compile(r"^\s*\[QUOTE=[^\]]*\]", re.I)
_QUOTE_CLOSE_RE = re.compile(r"\[/QUOTE\]\s*$", re.I)


def extract_thread_id(link: str) -> str | None:
    """Return the thread id from a MU thread URL, or a bare number, else None."""
    raw = (link or "").strip()
    match = _THREAD_ID_RE.search(raw)
    if match:
        return match.group(1)
    return raw if raw.isdigit() else None


def unwrap_quote_bbcode(quote_bbcode: str) -> str:
    """Strip the outer ``[QUOTE=author;postid]…[/QUOTE]`` MU wraps a post in.

    getquotes returns each post's body already wrapped in a single quote tag whose
    label attributes the original author. We only want the raw body BBCode per cell,
    so remove the first opening QUOTE tag and the trailing closing one. Nested quotes
    inside the body are left untouched.
    """
    body = quote_bbcode or ""
    body = _QUOTE_OPEN_RE.sub("", body, count=1)
    body = _QUOTE_CLOSE_RE.sub("", body)
    return body.strip()


def _safe_output_path(filename: str) -> Path:
    """Resolve ``filename`` to a path inside EXPORT_DIR, forcing an .xlsx basename."""
    name = Path(filename.strip()).name  # drop any directory components
    if not name:
        name = "roles.xlsx"
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    return EXPORT_DIR / name


def write_posts_xlsx(path: Path, rows: list[tuple[str, str, str]]) -> None:
    """Write (author, post_id, bbcode) rows to an .xlsx with a header row."""
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "posts"
    ws.append(["author", "post_id", "bbcode"])
    for author, post_id, bbcode in rows:
        ws.append([author, post_id, bbcode])
    wb.save(path)


def _collect_rows(mu_client, thread_id: str) -> list[tuple[str, str, str]]:
    """Enumerate every post in the thread and fetch each one's raw BBCode.

    Runs synchronously (call via asyncio.to_thread). Returns (author, post_id,
    bbcode) tuples in thread order. Posts whose BBCode cannot be fetched are kept
    with an empty bbcode cell so the row count still matches the thread.
    """
    posts = mu_client.fetch_all_thread_posts(thread_id)
    rows: list[tuple[str, str, str]] = []
    total = len(posts)
    for i, post in enumerate(posts, start=1):
        post_id = str(post.get("post_id", ""))
        author = post.get("author") or ""
        try:
            quote = mu_client.fetch_quote_bbcode(thread_id, post_id)
            bbcode = unwrap_quote_bbcode(quote)
            # Prefer the author from the quote label when the listing lacked one.
            author = author or (extract_quote_author(quote) or "")
        except Exception as exc:  # keep going; one bad post shouldn't abort the export
            log.warning("roles export: failed to fetch bbcode for post %s: %s", post_id, exc)
            bbcode = ""
        rows.append((author, post_id, bbcode))
        if i % 25 == 0 or i == total:
            log.info("roles export: fetched %d/%d posts for thread %s", i, total, thread_id)
        time.sleep(POST_FETCH_DELAY)
    return rows


def register(bot, *, mu_client) -> None:
    @bot.command(name="roles")
    async def roles(ctx, *, args: str = ""):
        if ctx.channel.id != ROLEPM_CHANNEL_ID:
            return
        if "|" not in args:
            await ctx.reply("Usage: `!roles <thread link> | <filename.xlsx>`")
            return
        link, filename = (part.strip() for part in args.split("|", 1))
        thread_id = extract_thread_id(link)
        if not thread_id:
            await ctx.reply(f"Could not find a thread id in: `{link}`")
            return
        if not filename:
            await ctx.reply("Usage: `!roles <thread link> | <filename.xlsx>`")
            return
        path = _safe_output_path(filename)

        await ctx.reply(f"Exporting thread `{thread_id}` to `{path.name}` — this may take a while...")
        try:
            rows = await asyncio.to_thread(_collect_rows, mu_client, thread_id)
        except Exception as exc:
            await ctx.reply(f"Failed to read thread `{thread_id}`: {exc}")
            return
        if not rows:
            await ctx.reply(f"No posts found in thread `{thread_id}`.")
            return
        try:
            await asyncio.to_thread(write_posts_xlsx, path, rows)
        except Exception as exc:
            await ctx.reply(f"Fetched {len(rows)} posts but failed to write `{path}`: {exc}")
            return

        try:
            await ctx.reply(
                f"Exported {len(rows)} posts from thread `{thread_id}` to `{path}`.",
                file=discord.File(str(path)),
            )
        except Exception:
            # File too large to attach (Discord limit) — the file is still on disk.
            await ctx.reply(f"Exported {len(rows)} posts from thread `{thread_id}` to `{path}` (too large to attach).")

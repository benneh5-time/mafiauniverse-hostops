from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

from bs4 import BeautifulSoup, Tag

from .db import HostOpsDB
from .mu_client import MUClient

MANUAL_ITA_RE = re.compile(r"manual\s+ita\s*:\s*([^\n\r]+)", re.I)
POST_ID_RE = re.compile(r"(?:post_|post)(\d+)")
_PAGE_OF_RE = re.compile(r"[Pp]age\s+\d+\s+of\s+(\d+)")
_CSS_COLOR_RE = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.I)
_HEX_RE = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.I)
_RED_NAMES = {"red", "darkred", "crimson", "firebrick", "indianred", "tomato", "orangered"}

_MAX_PAGES_PER_POLL = 10


def _is_red_color(value: str) -> bool:
    v = value.strip().casefold()
    if v in _RED_NAMES:
        return True
    m = _HEX_RE.match(v)
    if not m:
        return False
    h = m.group(1)
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r >= 150 and g < 100 and b < 100


def _is_red(tag: Tag) -> bool:
    style = str(tag.get("style", ""))
    m = _CSS_COLOR_RE.search(style)
    if m and _is_red_color(m.group(1)):
        return True
    color_attr = str(tag.get("color", "")).strip()
    return bool(color_attr and _is_red_color(color_attr))


def _has_red_ancestor(tag: Tag) -> bool:
    current = tag.parent
    while isinstance(current, Tag):
        if _is_red(current):
            return True
        current = current.parent
    return False


def _has_red_content(tag: Tag) -> bool:
    """True if the tag itself, any ancestor, or any descendant is red."""
    if _is_red(tag) or _has_red_ancestor(tag):
        return True
    return any(_is_red(child) for child in tag.find_all(True))


def parse_post_ids(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    for post in soup.find_all(id=re.compile(r"^(post_?\d+|post\d+)$")):
        m = POST_ID_RE.search(str(post.get("id", "")))
        if m:
            ids.append(int(m.group(1)))
    return sorted(ids)


def parse_total_pages(html: str) -> int:
    m = _PAGE_OF_RE.search(html)
    return int(m.group(1)) if m else 1


def parse_manual_ita_posts(html: str) -> list[tuple[str, str]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []
    posts = soup.find_all(id=re.compile(r"^(post_?\d+|post\d+)$"))
    for post in posts:
        post_id_raw = str(post.get("id", ""))
        id_match = POST_ID_RE.search(post_id_raw)
        post_id = id_match.group(1) if id_match else post_id_raw
        for bold in post.find_all(["b", "strong"]):
            if not _has_red_content(bold):
                continue
            match = MANUAL_ITA_RE.search(bold.get_text(" ", strip=True))
            if match:
                results.append((post_id, match.group(1).strip()))
                break
    return results


class ManualITAPoller:
    def __init__(self, *, db: HostOpsDB, mu_client: MUClient,
                 resolve_callback: Callable[..., Awaitable[None]], interval_seconds: int = 60):
        self.db = db
        self.mu_client = mu_client
        self.resolve_callback = resolve_callback
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())

    async def run_forever(self) -> None:
        while True:
            await self.run_once_for_active_games()
            await asyncio.sleep(self.interval_seconds)

    async def run_once_for_active_games(self) -> None:
        for cfg in self.db.list_active_games():
            try:
                await self._poll_game(cfg)
            except Exception:
                continue

    async def _poll_game(self, cfg) -> None:
        checkpoint = self.db.get_ita_poll_checkpoint(cfg.host_channel_id, cfg.name)

        last_html = await asyncio.to_thread(self.mu_client.fetch_thread, cfg.thread_id, "lastpost")
        total_pages = parse_total_pages(last_html)

        # Collect pages from the end going backward until we reach our checkpoint.
        # Each entry is (page_num, html); we'll process oldest-first after collecting.
        pages: list[tuple[int, str]] = [(total_pages, last_html)]

        if checkpoint > 0:
            for page_num in range(total_pages - 1, 0, -1):
                if len(pages) >= _MAX_PAGES_PER_POLL:
                    break
                earliest = parse_post_ids(pages[-1][1])
                if not earliest or min(earliest) <= checkpoint:
                    break
                page_html = await asyncio.to_thread(self.mu_client.fetch_thread, cfg.thread_id, page_num)
                pages.append((page_num, page_html))

        new_checkpoint = checkpoint
        for _pg, html in reversed(pages):
            for post_id, player_name in parse_manual_ita_posts(html):
                if self.db.is_ita_seen(cfg.host_channel_id, cfg.name, post_id):
                    continue
                self.db.mark_ita_seen(cfg.host_channel_id, cfg.name, post_id)
                await self.resolve_callback(cfg=cfg, player_name=player_name, post_id=post_id)
            ids = parse_post_ids(html)
            if ids:
                new_checkpoint = max(new_checkpoint, max(ids))

        if new_checkpoint > checkpoint:
            self.db.set_ita_poll_checkpoint(cfg.host_channel_id, cfg.name, new_checkpoint)

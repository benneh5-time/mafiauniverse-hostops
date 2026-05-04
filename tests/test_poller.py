from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from host_ops.models import GameConfig
from host_ops.poller import ManualITAPoller, parse_manual_ita_posts, parse_total_pages


def test_bold_red_manual_ita_detected():
    html = '<div id="post_100"><div class="post_body"><span style="color: red"><b>MANUAL ITA: Alice</b></span></div></div>'
    assert parse_manual_ita_posts(html) == [("100", "Alice")]


def test_bold_wraps_color_detected():
    # [B][COLOR=red]Manual ITA: Player[/COLOR][/B] — bold is ancestor of color, not descendant
    html = '<div id="post_101"><b><span style="color: red">Manual ITA: Bob</span></b></div>'
    assert parse_manual_ita_posts(html) == [("101", "Bob")]


def test_non_red_ignored():
    html = '<div id="post_100"><div class="post_body"><b>MANUAL ITA: Alice</b></div></div>'
    assert parse_manual_ita_posts(html) == []


def test_non_bold_ignored():
    html = '<div id="post_100"><div class="post_body"><span style="color:red">MANUAL ITA: Alice</span></div></div>'
    assert parse_manual_ita_posts(html) == []


def test_case_insensitive_and_hex_red():
    html = '<div id="post100"><strong style="color:#ff0000">manual ita: Bob</strong></div>'
    assert parse_manual_ita_posts(html) == [("100", "Bob")]


def test_dark_red_hex_detected():
    html = '<div id="post_200"><span style="color:#cc0000"><b>Manual ITA: Carol</b></span></div>'
    assert parse_manual_ita_posts(html) == [("200", "Carol")]


def test_parse_total_pages_found():
    html = "<html><body>Page 3 of 7</body></html>"
    assert parse_total_pages(html) == 7


def test_parse_total_pages_missing():
    assert parse_total_pages("<html><body>no pagination here</body></html>") == 1


class FakeMU:
    def fetch_thread(self, thread_id, page="lastpost"):
        return '<div id="post_100"><span style="color:red"><b>MANUAL ITA: Alice</b></span></div>'


def test_poller_dedupes_seen_posts(db):
    db.upsert_game(GameConfig("g", 123, "sheet", 10, active=True))
    callback = AsyncMock()
    poller = ManualITAPoller(db=db, mu_client=FakeMU(), resolve_callback=callback, interval_seconds=1)
    asyncio.run(poller.run_once_for_active_games())
    asyncio.run(poller.run_once_for_active_games())
    callback.assert_called_once()
    assert db.is_ita_seen(10, "g", "100")


def test_poller_checkpoint_advances(db):
    db.upsert_game(GameConfig("g", 123, "sheet", 10, active=True))
    callback = AsyncMock()
    poller = ManualITAPoller(db=db, mu_client=FakeMU(), resolve_callback=callback, interval_seconds=1)
    assert db.get_ita_poll_checkpoint(10, "g") == 0
    asyncio.run(poller.run_once_for_active_games())
    assert db.get_ita_poll_checkpoint(10, "g") == 100

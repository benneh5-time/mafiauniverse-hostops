from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from host_ops.commands.actions import ita_action, parse_pipe_args, silent_ita_action
from host_ops.models import GameConfig


class FakeSheetReader:
    def __init__(self, state):
        self.state = state

    def load_game_state(self, sheet_id):
        return self.state


# ---- pipe parsing --------------------------------------------------------

def test_parse_pipe_args_splits_and_trims():
    assert parse_pipe_args("Alice | Bob | 18", 3) == ["Alice", "Bob", "18"]


def test_parse_pipe_args_pads_missing_trailing_fields():
    assert parse_pipe_args("Alice", 3) == ["Alice", "", ""]


def test_parse_pipe_args_preserves_spaces_in_names():
    assert parse_pipe_args("Big Mommy Meowers |  | 25", 3) == ["Big Mommy Meowers", "", "25"]


# ---- !silent_ita ---------------------------------------------------------

def _game(db):
    db.upsert_game(GameConfig("g", 123, "sheet", 10, log_channel_id=99, active=True))


def test_silent_ita_dry_run_hit_marks_dead_no_mu(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=False,
        host_channel_id=10, target_name="Alice", source="Bob", hitrate=100.0, rng=lambda: 0.0))
    assert result.success
    mu.kill.assert_not_called()
    assert db.is_dead(10, "g", "Alice")


def test_silent_ita_live_hit_kills_and_posts(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.kill.return_value = {"response": "Kill was successful"}
    reply = MagicMock(post_id="555", final_url="https://www.mafiauniverse.com/forums/threads/123?p=555#post555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, message = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=100.0, rng=lambda: 0.0))
    assert result.success
    mu.kill.assert_called_once()
    # announcement + threadmark posted
    args = mu.post_reply_with_threadmark.call_args.args
    announcement, threadmark = args[1], args[2]
    assert "[TITLE]A Silent Shot Rings Out![/TITLE]" in announcement
    assert "[B]Hit![/B]" in announcement
    assert threadmark == "A Silent Shot Rings Out! Alice is dead"
    assert db.is_dead(10, "g", "Alice")
    assert "https://www.mafiauniverse.com/forums/threads/123?p=555#post555" in message


def test_silent_ita_live_miss_posts_threadmark_no_kill(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    reply = MagicMock(post_id="555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=1.0, rng=lambda: 0.99))
    assert result.miss
    mu.kill.assert_not_called()
    args = mu.post_reply_with_threadmark.call_args.args
    announcement, threadmark = args[1], args[2]
    assert "[TITLE]A Silent Shot Rings Out![/TITLE]" in announcement
    assert "[B]Miss![/B]" in announcement
    assert threadmark == "A Silent Shot Rings Out! Miss"
    assert not db.is_dead(10, "g", "Alice")


def test_silent_ita_default_hitrate_is_18(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    # roll 0.50 -> 50 > 18 default -> miss
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=False,
        host_channel_id=10, target_name="Alice", source=None, hitrate=None, rng=lambda: 0.50))
    assert result.miss
    assert result.hit_pct == 18.0


def test_silent_ita_no_active_game_returns_message(db, basic_state):
    bot = MagicMock()
    mu = MagicMock()
    result, message = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=False,
        host_channel_id=10, target_name="Alice", source=None, hitrate=18.0))
    assert result is None
    assert "No active game" in message


# ---- !ita ---------------------------------------------------------------

def test_ita_live_quotes_kills_and_posts(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.fetch_quote_bbcode.return_value = "[QUOTE=Mashy;11042484]I shoot Alice[/QUOTE]"
    mu.kill.return_value = {"response": "Kill was successful"}
    reply = MagicMock(post_id="555", final_url="https://www.mafiauniverse.com/forums/threads/9?p=555#post555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, message = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source="Bob",
        post_link="https://www.mafiauniverse.com/forums/threads/9/page5#post11042484"))
    assert result.success
    mu.fetch_quote_bbcode.assert_called_once()
    assert mu.fetch_quote_bbcode.call_args.args[1] == "11042484"
    mu.kill.assert_called_once()
    announcement, threadmark = mu.post_reply_with_threadmark.call_args.args[1], mu.post_reply_with_threadmark.call_args.args[2]
    assert announcement.startswith("[QUOTE=Mashy;11042484]I shoot Alice[/QUOTE]")
    assert "[B]Hit![/B]" in announcement
    # threadmark names the quoted shooter, the target, and the role (Alice is town in basic_state, no role_name)
    assert threadmark == "In-Thread Attack: Mashy hit Alice"
    assert db.is_dead(10, "g", "Alice")
    # reply links to the created post
    assert "https://www.mafiauniverse.com/forums/threads/9?p=555#post555" in message


def test_ita_link_falls_back_to_constructed_url_when_no_final_url(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.fetch_quote_bbcode.return_value = "[QUOTE=Label;11042484]original[/QUOTE]"
    mu.kill.return_value = {"response": "Kill was successful"}
    reply = MagicMock(post_id="777", final_url=None)
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    _result, message = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None,
        post_link="https://www.mafiauniverse.com/forums/threads/9#post11042484"))
    assert "?p=777#post777" in message


def test_ita_dry_run_marks_dead_without_mu(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    result, _msg = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=False,
        host_channel_id=10, target_name="Alice", source=None,
        post_link="https://www.mafiauniverse.com/forums/showthread.php?p=11042484"))
    assert result.success
    mu.kill.assert_not_called()
    mu.post_reply_with_threadmark.assert_not_called()
    assert db.is_dead(10, "g", "Alice")


def test_ita_bad_link_returns_error_no_mu(db, basic_state):
    _game(db)
    bot = MagicMock()
    mu = MagicMock()
    result, message = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None,
        post_link="https://www.mafiauniverse.com/forums/threads/9/"))
    assert result is None
    assert "post id" in message.lower()
    mu.kill.assert_not_called()
    mu.fetch_quote_bbcode.assert_not_called()

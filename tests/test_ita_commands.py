from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from host_ops.commands import actions
from host_ops.commands.actions import ita_action, ita_roll_action, parse_pipe_args, silent_ita_action
from host_ops.models import GameConfig


def test_ita_and_resolve_ita_commands_registered():
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)
    actions.register(bot, db=MagicMock(), sheet_reader=MagicMock(), mu_client=MagicMock(), live_mode=False)
    names = {c.name for c in bot.commands}
    assert "ita" in names          # unchanged: quote-a-post, posts to thread
    assert "resolve_ita" in names  # new: roll-only accuracy command


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
    assert threadmark == "A Silent Shot Rings Out! Alice was hit"
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


# ---- shield / BPV guard --------------------------------------------------

def _shielded_state():
    from host_ops.models import GameState, ITASettings, Player
    return GameState(
        players=[Player("Alice", "alice_mu", "PM", "Redacted Alice", True, "town")],
        protections=[],
        ita_settings=[ITASettings(phase="any", player="Alice", default_hit_pct=100.0, shield_status=1)],
    )


def test_silent_ita_warns_and_skips_when_target_shielded(db):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    result, message = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=100.0, rng=lambda: 0.0))
    assert result is None
    assert "shield" in message.lower()
    mu.kill.assert_not_called()
    mu.post_reply_with_threadmark.assert_not_called()
    assert not db.is_dead(10, "g", "Alice")


def test_silent_ita_confirm_overrides_shield(db):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.kill.return_value = {"response": "Kill was successful"}
    reply = MagicMock(post_id="555", final_url="https://mu/threads/1?p=555#post555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=100.0, mode="confirm", rng=lambda: 0.0))
    assert result.success
    mu.kill.assert_called_once()
    assert db.is_dead(10, "g", "Alice")


def test_silent_ita_vest_pops_hit_no_kill_no_reveal(db):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    reply = MagicMock(post_id="555", final_url="https://mu/threads/1?p=555#post555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=100.0, mode="vest", rng=lambda: 0.0))
    assert result.success
    # posts, but no kill and player stays alive
    mu.kill.assert_not_called()
    announcement, threadmark = mu.post_reply_with_threadmark.call_args.args[1], mu.post_reply_with_threadmark.call_args.args[2]
    assert "[B]Hit![/B]" in announcement
    assert "[SPOILER]" not in announcement
    assert threadmark == "A Silent Shot Rings Out!"
    assert not db.is_dead(10, "g", "Alice")


def test_silent_ita_vest_miss_still_posts_miss(db):
    # vest passed but the roll misses -> normal Miss, no vest pop
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    reply = MagicMock(post_id="555", final_url=None)
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=1.0, mode="vest", rng=lambda: 0.99))
    assert result.miss
    announcement = mu.post_reply_with_threadmark.call_args.args[1]
    assert "[B]Miss![/B]" in announcement


def test_silent_ita_miss_not_blocked_by_shield(db):
    # a miss posts "Miss!" but doesn't kill, so a shield is irrelevant and shouldn't block
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    reply = MagicMock(post_id="555", final_url=None)
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(silent_ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, hitrate=1.0, rng=lambda: 0.99))
    assert result.miss
    mu.post_reply_with_threadmark.assert_called_once()


def test_ita_warns_and_skips_when_target_shielded(db):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    result, message = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None,
        post_link="https://www.mafiauniverse.com/forums/threads/9#post11042484"))
    assert result is None
    assert "shield" in message.lower()
    mu.kill.assert_not_called()
    mu.fetch_quote_bbcode.assert_not_called()
    assert not db.is_dead(10, "g", "Alice")


def test_ita_confirm_overrides_shield(db):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.fetch_quote_bbcode.return_value = "[QUOTE=Mashy;11042484]shot[/QUOTE]"
    mu.kill.return_value = {"response": "Kill was successful"}
    reply = MagicMock(post_id="555", final_url="https://mu/threads/1?p=555#post555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, mode="confirm",
        post_link="https://www.mafiauniverse.com/forums/threads/9#post11042484"))
    assert result.success
    mu.kill.assert_called_once()
    assert db.is_dead(10, "g", "Alice")


def test_ita_vest_pops_hit_no_kill_no_reveal(db):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.fetch_quote_bbcode.return_value = "[QUOTE=Mashy;11042484]shot[/QUOTE]"
    reply = MagicMock(post_id="555", final_url="https://mu/threads/1?p=555#post555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _msg = asyncio.run(ita_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(_shielded_state()), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", source=None, mode="vest",
        post_link="https://www.mafiauniverse.com/forums/threads/9#post11042484"))
    assert result.success
    mu.kill.assert_not_called()
    announcement, threadmark = mu.post_reply_with_threadmark.call_args.args[1], mu.post_reply_with_threadmark.call_args.args[2]
    assert "[B]Hit![/B]" in announcement
    assert "[SPOILER]" not in announcement
    assert threadmark == "A shot rings out!"
    assert not db.is_dead(10, "g", "Alice")


# ---- !ita (roll-only, report to Discord/log, nothing posted) --------------

def test_ita_roll_hit_reports_but_touches_nothing(db, basic_state):
    _game(db)
    bot = MagicMock()
    log_channel = AsyncMock()
    bot.get_channel.return_value = log_channel
    mu = MagicMock()
    result, message = asyncio.run(ita_roll_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", shooter="Bob", accuracy=90.0, rng=lambda: 0.10))
    assert result.success
    # nothing posted, no kill, no death recorded
    mu.kill.assert_not_called()
    mu.post_reply_with_threadmark.assert_not_called()
    mu.fetch_quote_bbcode.assert_not_called()
    assert not db.is_dead(10, "g", "Alice")
    # reports to discord and the log channel
    assert "hit" in message.lower()
    log_channel.send.assert_called_once()
    # and logs an event
    events = db.get_events(10, "g", "Alice")
    assert events and events[-1]["event_type"] == "ita_roll"


def test_ita_roll_miss(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    result, message = asyncio.run(ita_roll_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", shooter="Bob", accuracy=10.0, rng=lambda: 0.90))
    assert result.miss
    assert "miss" in message.lower()
    assert not db.is_dead(10, "g", "Alice")


def test_ita_roll_same_in_live_and_dry_run(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    live, _ = asyncio.run(ita_roll_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", shooter="Bob", accuracy=50.0, rng=lambda: 0.10))
    dry, _ = asyncio.run(ita_roll_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=False,
        host_channel_id=10, target_name="Alice", shooter="Bob", accuracy=50.0, rng=lambda: 0.10))
    assert live.success and dry.success
    mu.kill.assert_not_called()


def test_ita_roll_unknown_player(db, basic_state):
    _game(db)
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    result, message = asyncio.run(ita_roll_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Nobody", shooter="Bob", accuracy=50.0))
    assert not result.success
    assert "unknown player" in message.lower()


def test_ita_roll_no_active_game(db, basic_state):
    bot = MagicMock()
    mu = MagicMock()
    result, message = asyncio.run(ita_roll_action(
        bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu, live_mode=True,
        host_channel_id=10, target_name="Alice", shooter="Bob", accuracy=50.0))
    assert result is None
    assert "No active game" in message

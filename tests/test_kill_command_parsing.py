from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from host_ops.commands import actions


def _make_bot(monkeypatch):
    """Register the action commands on a real bot with the action layer stubbed out."""
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    captured = {}

    async def fake_resolve_action(**kwargs):
        captured.update(kwargs)
        captured["_which"] = "resolve_action"
        return (MagicMock(), "ok")

    async def fake_resolve_bomb_action(**kwargs):
        captured.update(kwargs)
        captured["_which"] = "resolve_bomb_action"
        return (MagicMock(), "ok")

    async def fake_ita_action(**kwargs):
        captured.update(kwargs)
        captured["_which"] = "ita_action"
        return (MagicMock(), "ok")

    monkeypatch.setattr(actions, "resolve_action", fake_resolve_action)
    monkeypatch.setattr(actions, "resolve_bomb_action", fake_resolve_bomb_action)
    monkeypatch.setattr(actions, "ita_action", fake_ita_action)

    actions.register(bot, db=MagicMock(), sheet_reader=MagicMock(), mu_client=MagicMock(), live_mode=False)
    return bot, captured


def _run(bot, name, args):
    ctx = MagicMock()
    ctx.channel.id = 10
    ctx.reply = AsyncMock()
    cmd = bot.get_command(name)
    asyncio.run(cmd.callback(ctx, args=args))
    return ctx


def test_kill_splits_player_label_and_reason_on_pipe(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Alice | A gunshot rings out | night kill")
    assert captured["_which"] == "resolve_action"
    assert captured["event_type"] == "kill"
    assert captured["target_name"] == "Alice"
    assert captured["kill_label"] == "A gunshot rings out"
    assert captured["reason"] == "night kill"


def test_kill_second_field_is_the_label_not_the_reason(monkeypatch):
    """Field order is player | label | reason; a two-field kill fills the label."""
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Alice | night kill")
    assert captured["target_name"] == "Alice"
    assert captured["kill_label"] == "night kill"
    assert captured["reason"] == ""


def test_kill_without_label_or_reason(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Alice")
    assert captured["target_name"] == "Alice"
    assert captured["kill_label"] is None
    assert captured["reason"] == ""


def test_kill_preserves_spaces_in_player_label_and_reason(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Big Mommy Meowers | A gunshot rings out | shot by the vig at night")
    assert captured["target_name"] == "Big Mommy Meowers"
    assert captured["kill_label"] == "A gunshot rings out"
    assert captured["reason"] == "shot by the vig at night"


def test_kill_missing_target_shows_usage(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    ctx = _run(bot, "kill", "")
    assert "_which" not in captured  # action layer not called
    ctx.reply.assert_awaited_once()
    assert "Usage" in ctx.reply.await_args.args[0]


def test_dayvig_uses_pipe(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "dayvig", "Bob | claimed wolf")
    assert captured["event_type"] == "dayvig"
    assert captured["target_name"] == "Bob"
    assert captured["reason"] == "claimed wolf"


def test_desperado_uses_pipe(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "desperado", "Carol | desperado shot")
    assert captured["event_type"] == "desperado"
    assert captured["target_name"] == "Carol"
    assert captured["reason"] == "desperado shot"


def test_bomb_splits_bomber_bombee_reason(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "bomb", "Alice | Bob | boom")
    assert captured["_which"] == "resolve_bomb_action"
    assert captured["bomber_name"] == "Alice"
    assert captured["bombee_name"] == "Bob"
    assert captured["reason"] == "boom"


def test_bomb_without_reason(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "bomb", "Alice | Bob")
    assert captured["bomber_name"] == "Alice"
    assert captured["bombee_name"] == "Bob"


def test_ita_parses_target_source_accuracy_and_link(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "ita", "Alice | Bob | 35 | https://mu/threads/9#post123")
    assert captured["_which"] == "ita_action"
    assert captured["target_name"] == "Alice"
    assert captured["source"] == "Bob"
    assert captured["accuracy"] == 35
    assert captured["post_link"] == "https://mu/threads/9#post123"


def test_ita_source_may_be_blank(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "ita", "Alice |  | 100 | https://mu/threads/9#post123")
    assert captured["source"] is None
    assert captured["accuracy"] == 100


def test_ita_accepts_trailing_percent_on_accuracy(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "ita", "Alice | Bob | 50% | https://mu/threads/9#post123")
    assert captured["accuracy"] == 50


def test_ita_rejects_non_integer_accuracy(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    ctx = _run(bot, "ita", "Alice | Bob | high | https://mu/threads/9#post123")
    assert "_which" not in captured
    assert "accuracy" in ctx.reply.await_args.args[0].lower()


def test_ita_rejects_out_of_range_accuracy(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    ctx = _run(bot, "ita", "Alice | Bob | 150 | https://mu/threads/9#post123")
    assert "_which" not in captured
    assert "between 0 and 100" in ctx.reply.await_args.args[0]


def test_ita_missing_link_shows_usage(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    ctx = _run(bot, "ita", "Alice | Bob | 35")
    assert "_which" not in captured
    assert "Usage" in ctx.reply.await_args.args[0]


def test_bomb_missing_bombee_shows_usage(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    ctx = _run(bot, "bomb", "Alice")
    assert "_which" not in captured
    ctx.reply.assert_awaited_once()
    assert "Usage" in ctx.reply.await_args.args[0]

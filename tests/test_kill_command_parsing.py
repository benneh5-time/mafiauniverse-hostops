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

    monkeypatch.setattr(actions, "resolve_action", fake_resolve_action)
    monkeypatch.setattr(actions, "resolve_bomb_action", fake_resolve_bomb_action)

    actions.register(bot, db=MagicMock(), sheet_reader=MagicMock(), mu_client=MagicMock(), live_mode=False)
    return bot, captured


def _run(bot, name, args):
    ctx = MagicMock()
    ctx.channel.id = 10
    ctx.reply = AsyncMock()
    cmd = bot.get_command(name)
    asyncio.run(cmd.callback(ctx, args=args))
    return ctx


def test_kill_splits_player_and_reason_on_pipe(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Alice | night kill")
    assert captured["_which"] == "resolve_action"
    assert captured["event_type"] == "kill"
    assert captured["target_name"] == "Alice"
    assert captured["reason"] == "night kill"


def test_kill_without_reason(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Alice")
    assert captured["target_name"] == "Alice"
    assert captured["reason"] == ""


def test_kill_preserves_spaces_in_player_and_reason(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    _run(bot, "kill", "Big Mommy Meowers | shot by the vig at night")
    assert captured["target_name"] == "Big Mommy Meowers"
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
    assert captured["reason"] == ""


def test_bomb_missing_bombee_shows_usage(monkeypatch):
    bot, captured = _make_bot(monkeypatch)
    ctx = _run(bot, "bomb", "Alice")
    assert "_which" not in captured
    ctx.reply.assert_awaited_once()
    assert "Usage" in ctx.reply.await_args.args[0]

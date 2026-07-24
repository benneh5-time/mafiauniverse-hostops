from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from host_ops.commands import host
from host_ops.models import GameConfig, GameState, Player


class FakeSheetReader:
    def __init__(self, state):
        self.state = state
        self.written: dict[str, str] | None = None

    def load_game_state(self, sheet_id):
        return self.state

    def write_mu_role_names(self, sheet_id, names_by_player):
        self.written = names_by_player
        return len(names_by_player)


def _player(name, **kwargs):
    defaults = dict(
        mu_username=name, role_pm="pm", redacted_role_pm="redacted", alive=True,
        alignment="town", role_name="Host Role", notes="", flavor="",
        mu_role_name="MU Role", faction="", faction_color="#339933", rolepm_verified=True,
    )
    defaults.update(kwargs)
    return Player(name, **defaults)


def _setup(players, *, game_id=10222):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    db = MagicMock()
    db.get_active_game.return_value = GameConfig("g", 123, "sheet", 10, log_channel_id=99, game_id=game_id, active=True)
    sheets = FakeSheetReader(GameState(players, [], []))
    mu = MagicMock()
    host.register(bot, db=db, sheet_reader=sheets, mu_client=mu)
    ctx = MagicMock()
    ctx.channel.id = 10
    ctx.reply = AsyncMock()
    return bot, ctx, sheets, mu


def _run(bot, name, ctx):
    asyncio.run(bot.get_command(name).callback(ctx))


def _reply(ctx) -> str:
    return ctx.reply.call_args.args[0]


def test_commands_are_registered():
    bot, _ctx, _sheets, _mu = _setup([_player("gamer")])
    names = {c.name for c in bot.commands}
    assert "pull_players" in names
    assert "push_players" in names


def test_pull_writes_mu_role_names_keyed_by_player():
    bot, ctx, sheets, mu = _setup([_player("gamer"), _player("Sprigatito")])
    mu.fetch_deaths_page_state.return_value = ("tok", [
        {"username": "gamer", "role_name": "Vanilla Town"},
        {"username": "Sprigatito", "role_name": "Cop"},
    ])
    _run(bot, "pull_players", ctx)
    assert sheets.written == {"gamer": "Vanilla Town", "sprigatito": "Cop"}


def test_pull_reports_players_missing_from_the_sheet():
    bot, ctx, sheets, mu = _setup([_player("gamer")])
    mu.fetch_deaths_page_state.return_value = ("tok", [
        {"username": "gamer", "role_name": "Vanilla Town"},
        {"username": "Ghost", "role_name": "Cop"},
    ])
    _run(bot, "pull_players", ctx)
    assert "Ghost" in _reply(ctx)
    assert sheets.written == {"gamer": "Vanilla Town"}


def test_push_sends_only_sheet_owned_fields():
    bot, ctx, _sheets, mu = _setup([
        _player("gamer", mu_role_name="Vanilla Villager", faction="", faction_color="#339933", rolepm_verified=True),
    ])
    mu.push_player_settings.return_value = 1
    _run(bot, "push_players", ctx)
    payload = mu.push_player_settings.call_args.args[1]
    assert payload == {"gamer": {
        "role_name": "Vanilla Villager",
        "faction": "",
        "faction_color": "#339933",
        "alignment": "town",
        "rolepm_verified": "1",
    }}


def test_push_normalizes_alignment_and_color_before_sending():
    bot, ctx, _sheets, mu = _setup([
        _player("gamer", alignment="  MAFIA ", faction_color="ff2244", rolepm_verified=False),
    ])
    mu.push_player_settings.return_value = 1
    _run(bot, "push_players", ctx)
    sent = mu.push_player_settings.call_args.args[1]["gamer"]
    assert sent["alignment"] == "mafia"
    assert sent["faction_color"] == "#ff2244"
    assert sent["rolepm_verified"] == "0"


def test_push_aborts_on_bad_alignment_without_contacting_mu():
    bot, ctx, _sheets, mu = _setup([_player("gamer", alignment="independent")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()
    message = _reply(ctx)
    assert "aborted" in message.lower()
    assert "gamer" in message


def test_push_aborts_on_bad_faction_color_without_contacting_mu():
    bot, ctx, _sheets, mu = _setup([_player("gamer", faction_color="green")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()
    assert "faction_color" in _reply(ctx)


def test_push_abort_is_all_or_nothing():
    """One bad row must not let the other players through."""
    bot, ctx, _sheets, mu = _setup([_player("gamer"), _player("bad", alignment="???")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()


def test_commands_require_a_stored_game_id():
    for command in ("pull_players", "push_players"):
        bot, ctx, _sheets, mu = _setup([_player("gamer")], game_id=None)
        _run(bot, command, ctx)
        assert "game ID" in _reply(ctx)
        mu.push_player_settings.assert_not_called()
        mu.fetch_deaths_page_state.assert_not_called()

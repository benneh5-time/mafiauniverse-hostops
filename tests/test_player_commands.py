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

    def write_mu_columns(self, sheet_id, values_by_player, columns):
        self.written = values_by_player
        self.columns = columns
        return len(values_by_player)


def _player(name, **kwargs):
    defaults = dict(
        mu_username=name, role_pm="pm", redacted_role_pm="redacted", alive=True,
        # `alignment` is the host's own free-form column and must stay unread by
        # push; `mu_alignment` is the MU mirror.
        alignment="katz", role_name="Host Role", notes="", flavor="",
        mu_role_name="MU Role", mu_alignment="town", faction="", faction_color="#339933",
        rolepm_verified="TRUE",
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


def _page_row(username, **kwargs):
    row = {
        "username": username, "role_name": "Vanilla Town", "alignment": "town",
        "is_alive": "1", "faction": "", "faction_color": "#339933", "rolepm_verified": "1",
    }
    row.update(kwargs)
    return row


def test_pull_mirrors_mu_state_keyed_by_player():
    bot, ctx, sheets, mu = _setup([_player("gamer"), _player("Sprigatito")])
    mu.fetch_deaths_page_state.return_value = ("tok", [
        _page_row("gamer", is_alive="0", rolepm_verified="0"),
        _page_row("Sprigatito", role_name="Cop", alignment="mafia", faction="Mafia"),
    ])
    _run(bot, "pull_players", ctx)

    assert sheets.written["gamer"] == {
        "mu_role_name": "Vanilla Town", "mu_alignment": "town", "mu_is_alive": "FALSE",
        "faction": "", "faction_color": "#339933", "rolepm_verified": "FALSE",
    }
    assert sheets.written["sprigatito"]["mu_role_name"] == "Cop"
    assert sheets.written["sprigatito"]["mu_alignment"] == "mafia"
    assert sheets.written["sprigatito"]["mu_is_alive"] == "TRUE"


def test_pull_never_writes_host_owned_columns():
    """`alive`, `alignment` and `role_name` drive the resolver and flips."""
    bot, ctx, sheets, mu = _setup([_player("gamer")])
    mu.fetch_deaths_page_state.return_value = ("tok", [_page_row("gamer")])
    _run(bot, "pull_players", ctx)

    assert "alive" not in sheets.columns
    assert "alignment" not in sheets.columns
    assert "role_name" not in sheets.columns
    for fields in sheets.written.values():
        assert not {"alive", "alignment", "role_name"} & set(fields)


def test_pull_reports_players_missing_from_the_sheet():
    bot, ctx, sheets, mu = _setup([_player("gamer")])
    mu.fetch_deaths_page_state.return_value = ("tok", [
        _page_row("gamer"),
        _page_row("Ghost", role_name="Cop"),
    ])
    _run(bot, "pull_players", ctx)
    assert "Ghost" in _reply(ctx)
    assert set(sheets.written) == {"gamer"}


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
        _player("gamer", mu_alignment="  MAFIA ", faction_color="ff2244", rolepm_verified="FALSE"),
    ])
    mu.push_player_settings.return_value = 1
    _run(bot, "push_players", ctx)
    sent = mu.push_player_settings.call_args.args[1]["gamer"]
    assert sent["alignment"] == "mafia"
    assert sent["faction_color"] == "#ff2244"
    assert sent["rolepm_verified"] == "0"


def test_push_ignores_the_host_alignment_column():
    """The host's `alignment` column holds free-form values like 3p/katz."""
    bot, ctx, _sheets, mu = _setup([_player("gamer", alignment="3p", mu_alignment="mafia")])
    mu.push_player_settings.return_value = 1
    _run(bot, "push_players", ctx)
    assert mu.push_player_settings.call_args.args[1]["gamer"]["alignment"] == "mafia"


def test_push_with_no_mu_columns_sends_blanks_and_does_not_abort():
    """The realistic first run: sheet has none of the MU mirror columns."""
    bot, ctx, _sheets, mu = _setup([
        _player("gamer", mu_role_name="", mu_alignment="", faction="", faction_color="", rolepm_verified=""),
    ])
    mu.push_player_settings.return_value = 1
    _run(bot, "push_players", ctx)
    assert mu.push_player_settings.call_args.args[1]["gamer"] == {
        "role_name": "", "faction": "", "faction_color": "", "alignment": "", "rolepm_verified": "",
    }


def test_push_aborts_on_bad_alignment_without_contacting_mu():
    bot, ctx, _sheets, mu = _setup([_player("gamer", mu_alignment="independent")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()
    message = _reply(ctx)
    assert "aborted" in message.lower()
    assert "gamer" in message


def test_push_aborts_on_bad_verified_value():
    bot, ctx, _sheets, mu = _setup([_player("gamer", rolepm_verified="maybe")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()
    assert "rolepm_verified" in _reply(ctx)


def test_push_aborts_on_bad_faction_color_without_contacting_mu():
    bot, ctx, _sheets, mu = _setup([_player("gamer", faction_color="green")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()
    assert "faction_color" in _reply(ctx)


def test_push_abort_is_all_or_nothing():
    """One bad row must not let the other players through."""
    bot, ctx, _sheets, mu = _setup([_player("gamer"), _player("bad", mu_alignment="???")])
    _run(bot, "push_players", ctx)
    mu.push_player_settings.assert_not_called()


def test_commands_require_a_stored_game_id():
    for command in ("pull_players", "push_players"):
        bot, ctx, _sheets, mu = _setup([_player("gamer")], game_id=None)
        _run(bot, command, ctx)
        assert "game ID" in _reply(ctx)
        mu.push_player_settings.assert_not_called()
        mu.fetch_deaths_page_state.assert_not_called()

from __future__ import annotations

import asyncio

from ..db import HostOpsDB
from ..models import GameConfig
from ..mu_client import MUClient
from ..resolver import choose_ita_settings
from ..sheets import SheetReader, extract_sheet_id


def _channel_id_from_arg(ctx, channel_arg: str | None) -> int:
    if not channel_arg:
        return ctx.channel.id
    return int(channel_arg.strip().strip("<#!>"))


def register(bot, *, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient) -> None:
    @bot.command(name="setup_game")
    async def setup_game(ctx, name: str, thread_id: int, sheet_url_or_id: str):
        sheet_id = extract_sheet_id(sheet_url_or_id)
        state = sheet_reader.load_game_state(sheet_id)
        game_id = await asyncio.to_thread(mu_client.extract_game_id, thread_id)
        cfg = GameConfig(name=name, thread_id=thread_id, sheet_id=sheet_id, host_channel_id=ctx.channel.id, log_channel_id=ctx.channel.id, active=True, game_id=int(game_id) if game_id else None)
        db.upsert_game(cfg)
        db.set_active_game(ctx.channel.id, name)
        await ctx.reply(f"Game `{name}` configured and active: {len(state.players)} players loaded. Game ID: `{game_id or 'not found'}`. Log channel: <#{ctx.channel.id}>.")

    @bot.command(name="use_game")
    async def use_game(ctx, name: str):
        cfg = db.set_active_game(ctx.channel.id, name)
        if cfg is None:
            await ctx.reply(f"No configured game named `{name}` for this channel.")
            return
        await ctx.reply(f"Active game set to `{cfg.name}` for thread `{cfg.thread_id}`.")

    @bot.command(name="set_log_channel")
    async def set_log_channel(ctx, channel: str | None = None):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game. Use `!use_game <name>` first.")
            return
        log_channel_id = _channel_id_from_arg(ctx, channel)
        db.set_log_channel(ctx.channel.id, cfg.name, log_channel_id)
        await ctx.reply(f"Log channel for `{cfg.name}` set to <#{log_channel_id}>.")

    @bot.command(name="game_status")
    async def game_status(ctx):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game configured for this channel.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        await ctx.reply(f"Active game `{cfg.name}` | thread `{cfg.thread_id}` | players `{len(state.players)}` | log <#{cfg.log_channel_id or cfg.host_channel_id}>.")

    @bot.command(name="reload_sheet")
    async def reload_sheet(ctx):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game. Use `!use_game <name>` first.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        await ctx.reply(f"Reloaded `{cfg.name}` sheet: {len(state.players)} players, {len(state.protections)} protections, {len(state.ita_settings)} ITA rows.")

    @bot.command(name="pull_ita")
    async def pull_ita(ctx):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game. Use `!use_game <name>` first.")
            return
        if not cfg.game_id:
            await ctx.reply("No MU game ID stored — run `!setup_game` to detect it.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        players_by_mu = {p.mu_username.lower(): p for p in state.players}
        _token, page_rows = await asyncio.to_thread(mu_client.fetch_ita_page_state, cfg.game_id)
        sheet_rows = []
        unmatched = []
        for row in page_rows:
            player = players_by_mu.get(row["username"].lower())
            if player is None:
                unmatched.append(row["username"])
                continue
            immune_val = str(row["immunity"]) == "100"
            sheet_rows.append({
                "phase": "any",
                "player": player.player,
                "default_hit_pct": row["base_hit"],
                "hit_pct_override": "",
                "immune": "true" if immune_val else "false",
                "bonus": row["booster"],
                "penalty": row["nerfer"],
                "shots_allowed": row["count"],
                "vulnerability": row["vulnerability"],
                "shield_status": row["shield_status"],
                "bpv_status": row["bpv_status"],
            })
        await asyncio.to_thread(sheet_reader.write_ita_settings, cfg.sheet_id, sheet_rows)
        msg = f"ITA Settings tab updated from MU: {len(sheet_rows)} players written."
        if unmatched:
            msg += f" Could not match to sheet: {', '.join(unmatched)}."
        await ctx.reply(msg)

    @bot.command(name="push_ita")
    async def push_ita(ctx):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game. Use `!use_game <name>` first.")
            return
        if not cfg.game_id:
            await ctx.reply("No MU game ID stored — run `!setup_game` to detect it.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        settings_by_username: dict[str, dict] = {}
        for player in state.players:
            ita = choose_ita_settings(player, "any", state.ita_settings)
            base_hit = ita.hit_pct_override if ita.hit_pct_override is not None else ita.default_hit_pct
            settings_by_username[player.mu_username.lower()] = {
                "base_hit": base_hit,
                "immunity": 100 if ita.immune else 0,
                "booster": ita.bonus,
                "nerfer": ita.penalty,
                "count": ita.shots_allowed if ita.shots_allowed > 0 else 1,
                "vulnerability": ita.vulnerability,
                "shield_status": ita.shield_status,
                "bpv_status": ita.bpv_status,
            }
        matched = await asyncio.to_thread(mu_client.push_ita_settings, cfg.game_id, settings_by_username)
        total = len(state.players)
        await ctx.reply(f"ITA settings pushed: {matched}/{total} players matched on MU.")

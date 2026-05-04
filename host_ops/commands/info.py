from __future__ import annotations

from ..db import HostOpsDB
from ..models import normalize_name
from ..sheets import SheetReader


def _chunks(names: list[str]) -> str:
    return ", ".join(names) if names else "none"


def register(bot, *, db: HostOpsDB, sheet_reader: SheetReader) -> None:
    @bot.command(name="alive")
    async def alive(ctx):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        dead = db.dead_players(cfg.host_channel_id, cfg.name)
        names = [p.player for p in state.players if p.alive and normalize_name(p.player) not in dead]
        await ctx.reply(f"Alive ({len(names)}): {_chunks(names)}")

    @bot.command(name="dead")
    async def dead(ctx):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        dead = db.dead_players(cfg.host_channel_id, cfg.name)
        names = [p.player for p in state.players if not p.alive or normalize_name(p.player) in dead]
        await ctx.reply(f"Dead ({len(names)}): {_chunks(names)}")

    @bot.command(name="audit")
    async def audit(ctx, player: str):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game.")
            return
        events = db.get_events(cfg.host_channel_id, cfg.name, player)
        if not events:
            await ctx.reply(f"No events found for `{player}`.")
            return
        lines = [f"Audit for `{player}`:"]
        for event in events[-10:]:
            extra = f" blocked_by={event['blocked_by']}" if event.get("blocked_by") else ""
            lines.append(f"`{event['created_at']}` {event['event_type']} -> {event['outcome']}{extra}")
        await ctx.reply("\n".join(lines))

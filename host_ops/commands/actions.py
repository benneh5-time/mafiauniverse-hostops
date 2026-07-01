from __future__ import annotations

import asyncio

from ..db import HostOpsDB
from ..models import normalize_name
from ..mu_client import MUClient
from ..resolver import ResolutionError, build_death_announcement, resolve_bomb, resolve_death, resolve_player, threadmark_name
from ..sheets import SheetReader


def _outcome(result) -> str:
    if result.success:
        return "killed"
    if result.already_dead:
        return "already_dead"
    if result.blocked_by:
        return "blocked"
    if result.miss:
        return "missed"
    return "error"


async def _send_log(bot, cfg, text: str) -> None:
    channel_id = cfg.log_channel_id or cfg.host_channel_id
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(text)


async def resolve_action(*, bot, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool,
                         host_channel_id: int, target_name: str, event_type: str, phase: str = "any",
                         shooter: str | None = None, reason: str = ""):
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    state = sheet_reader.load_game_state(cfg.sheet_id)
    dead = db.dead_players(cfg.host_channel_id, cfg.name)
    for player in state.players:
        if normalize_name(player.player) in dead:
            player.alive = False
    result = resolve_death(
        target_name=target_name,
        event_type=event_type,
        phase=phase,
        state=state,
        is_dead=lambda name: db.is_dead(cfg.host_channel_id, cfg.name, name),
        dry_run=not live_mode,
    )
    outcome = _outcome(result)
    mu_post_id = None
    if result.success and live_mode:
        target = resolve_player(result.target_name, state.players)
        if cfg.game_id:
            mu_statuses = await asyncio.to_thread(mu_client.fetch_player_statuses, cfg.game_id)
            mu_alive = mu_statuses.get(target.mu_username.lower())
            if mu_alive is False:
                return result, f"{target.player} is already dead in MU modbot — kill aborted."
        kill_response = await asyncio.to_thread(mu_client.kill, cfg.thread_id, target.mu_username)
        kill_ok = isinstance(kill_response, dict) and "successful" in kill_response.get("response", "").lower()
        if not kill_ok:
            return result, f"MU kill did not confirm success for {target.player} — post/threadmark skipped. MU said: {kill_response}"
        announcement = build_death_announcement(target, event_type, reason)
        reply, _threadmark_response = await asyncio.to_thread(mu_client.post_reply_with_threadmark, cfg.thread_id, announcement, threadmark_name(target, event_type))
        mu_post_id = reply.post_id
        result.mu_response = kill_response
        result.announcement_post_id = reply.post_id
        result.threadmark_ok = True
        db.mark_dead(cfg.host_channel_id, cfg.name, result.target_name, event_type)
    elif result.success and not live_mode:
        db.mark_dead(cfg.host_channel_id, cfg.name, result.target_name, event_type)

    db.log_event(cfg.host_channel_id, cfg.name, event_type, result.target_name, outcome, shooter=shooter,
                 blocked_by=result.blocked_by, roll=result.roll, hit_pct=result.hit_pct, dry_run=not live_mode,
                 mu_post_id=mu_post_id, notes=reason or None)
    prefix = "[DRY RUN] " if not live_mode else ""
    await _send_log(bot, cfg, f"{prefix}**{event_type.upper()}** target={result.target_name} outcome={outcome}" + (f" shooter={shooter}" if shooter else ""))
    return result, result.message


async def resolve_bomb_action(*, bot, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool,
                              host_channel_id: int, bomber_name: str, bombee_name: str, reason: str = ""):
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    state = sheet_reader.load_game_state(cfg.sheet_id)
    dead = db.dead_players(cfg.host_channel_id, cfg.name)
    for player in state.players:
        if normalize_name(player.player) in dead:
            player.alive = False
    try:
        bomb = resolve_bomb(
            bomber_name=bomber_name,
            bombee_name=bombee_name,
            state=state,
            is_dead=lambda name: db.is_dead(cfg.host_channel_id, cfg.name, name),
        )
    except ResolutionError as exc:
        return None, str(exc)

    mu_post_id = None
    if live_mode:
        bomber_kill = await asyncio.to_thread(mu_client.kill, cfg.thread_id, bomb.bomber.mu_username)
        bomber_ok = isinstance(bomber_kill, dict) and "successful" in bomber_kill.get("response", "").lower()
        if not bomber_ok:
            return None, f"MU kill did not confirm success for {bomb.bomber.player} — post/threadmark skipped. MU said: {bomber_kill}"
        bombee_kill = await asyncio.to_thread(mu_client.kill, cfg.thread_id, bomb.bombee.mu_username)
        bombee_ok = isinstance(bombee_kill, dict) and "successful" in bombee_kill.get("response", "").lower()
        if not bombee_ok:
            return None, f"MU kill did not confirm success for {bomb.bombee.player} — post/threadmark skipped. MU said: {bombee_kill}"
        announcement = bomb.build_announcement(reason)
        reply, _threadmark_response = await asyncio.to_thread(mu_client.post_reply_with_threadmark, cfg.thread_id, announcement, bomb.threadmark_name())
        mu_post_id = reply.post_id
        bomb.mu_response_bomber = bomber_kill
        bomb.mu_response_bombee = bombee_kill
        bomb.announcement_post_id = reply.post_id
        bomb.threadmark_ok = True

    bomb.dry_run = not live_mode
    for player in (bomb.bomber, bomb.bombee):
        db.mark_dead(cfg.host_channel_id, cfg.name, player.player, "bomb")
        db.log_event(cfg.host_channel_id, cfg.name, "bomb", player.player, "killed", dry_run=not live_mode,
                     mu_post_id=mu_post_id, notes=reason or None)

    prefix = "[DRY RUN] " if not live_mode else ""
    message = f"{prefix}Bomb resolved: {bomb.bomber.player} and {bomb.bombee.player} are dead."
    await _send_log(bot, cfg, f"{prefix}**BOMB** bomber={bomb.bomber.player} bombee={bomb.bombee.player} outcome=killed")
    return bomb, message


def register(bot, *, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool) -> None:
    @bot.command(name="kill")
    async def kill(ctx, player: str, *, reason: str = ""):
        _result, message = await resolve_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, target_name=player, event_type="kill", reason=reason)
        await ctx.reply(message)

    @bot.command(name="dayvig")
    async def dayvig(ctx, player: str, *, reason: str = ""):
        _result, message = await resolve_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, target_name=player, event_type="dayvig", reason=reason)
        await ctx.reply(message)

    @bot.command(name="desperado")
    async def desperado(ctx, player: str, *, reason: str = ""):
        _result, message = await resolve_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, target_name=player, event_type="desperado", reason=reason)
        await ctx.reply(message)

    @bot.command(name="bomb")
    async def bomb(ctx, bomber: str, bombee: str, *, reason: str = ""):
        _result, message = await resolve_bomb_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, bomber_name=bomber, bombee_name=bombee, reason=reason)
        await ctx.reply(message)

    @bot.command(name="resolve_ita")
    async def resolve_ita(ctx, player: str, shooter: str = "", *, reason: str = ""):
        _result, message = await resolve_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, target_name=player, event_type="ita", shooter=shooter or None, reason=reason)
        await ctx.reply(message)

    @bot.command(name="revive")
    async def revive(ctx, *, player: str):
        cfg = db.get_active_game(ctx.channel.id)
        if cfg is None:
            await ctx.reply("No active game. Use `!use_game <name>` first.")
            return
        state = sheet_reader.load_game_state(cfg.sheet_id)
        try:
            target = resolve_player(player, state.players)
        except ResolutionError as exc:
            await ctx.reply(str(exc))
            return
        if live_mode:
            revive_response = await asyncio.to_thread(mu_client.revive, cfg.thread_id, target.mu_username)
            revive_ok = isinstance(revive_response, dict) and "successful" in revive_response.get("response", "").lower()
            if not revive_ok:
                await ctx.reply(f"MU revive did not confirm success for `{target.player}`. MU said: {revive_response}")
                return
        db.mark_alive(ctx.channel.id, cfg.name, target.player)
        prefix = "[DRY RUN] " if not live_mode else ""
        await ctx.reply(f"{prefix}`{target.player}` marked alive.")

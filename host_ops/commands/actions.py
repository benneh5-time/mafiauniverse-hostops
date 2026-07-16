from __future__ import annotations

import asyncio
import random

from ..db import HostOpsDB
from ..models import ResolveResult, normalize_name
from ..mu_client import MUClient
from ..resolver import (
    ResolutionError,
    build_death_announcement,
    build_ita_announcement,
    build_silent_ita_announcement,
    bpv_warning,
    extract_post_id_from_link,
    extract_quote_author,
    ita_protection_warning,
    ita_threadmark_name,
    resolve_bomb,
    resolve_death,
    resolve_player,
    resolve_silent_ita,
    silent_ita_threadmark_name,
    threadmark_name,
)
from ..sheets import SheetReader

DEFAULT_SILENT_ITA_HITRATE = 18.0


def _normalize_mode(mode: str | None) -> str:
    """Return one of '', 'confirm', 'vest' from the final pipe field."""
    m = (mode or "").strip().lower()
    return m if m in ("confirm", "vest") else ""


def parse_pipe_args(args: str, count: int) -> list[str]:
    """Split a ``|``-delimited arg string into exactly ``count`` trimmed fields.

    Missing trailing fields are padded with empty strings.
    """
    parts = [part.strip() for part in (args or "").split("|")]
    parts = parts[:count]
    while len(parts) < count:
        parts.append("")
    return parts


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
                         shooter: str | None = None, reason: str = "", mode: str | None = None):
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    mode = _normalize_mode(mode)
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

    vest = result.success and mode == "vest"
    # A real flip cannot be undone, so guard a successful kill against a BPV target.
    if result.success and not vest and mode != "confirm":
        target = resolve_player(result.target_name, state.players)
        warning = bpv_warning(target, state)
        if warning:
            return None, warning

    outcome = "vest_pop" if vest else _outcome(result)
    kills = result.success and not vest
    mu_post_id = None
    post_link = None
    if result.success and live_mode:
        target = resolve_player(result.target_name, state.players)
        if kills and cfg.game_id:
            mu_statuses = await asyncio.to_thread(mu_client.fetch_player_statuses, cfg.game_id)
            mu_alive = mu_statuses.get(target.mu_username.lower())
            if mu_alive is False:
                return result, f"{target.player} is already dead in MU modbot — kill aborted."
        if kills:
            kill_response = await asyncio.to_thread(mu_client.kill, cfg.thread_id, target.mu_username)
            kill_ok = isinstance(kill_response, dict) and "successful" in kill_response.get("response", "").lower()
            if not kill_ok:
                return result, f"MU kill did not confirm success for {target.player} — post/threadmark skipped. MU said: {kill_response}"
            result.mu_response = kill_response
        announcement = build_death_announcement(target, event_type, reason, vest=vest)
        reply, _threadmark_response = await asyncio.to_thread(mu_client.post_reply_with_threadmark, cfg.thread_id, announcement, threadmark_name(target, event_type, vest=vest))
        mu_post_id = reply.post_id
        post_link = _post_link(reply, cfg.thread_id)
        result.announcement_post_id = reply.post_id
        result.threadmark_ok = True
        if kills:
            db.mark_dead(cfg.host_channel_id, cfg.name, result.target_name, event_type)
    elif kills and not live_mode:
        db.mark_dead(cfg.host_channel_id, cfg.name, result.target_name, event_type)

    db.log_event(cfg.host_channel_id, cfg.name, event_type, result.target_name, outcome, shooter=shooter,
                 blocked_by=result.blocked_by, roll=result.roll, hit_pct=result.hit_pct, dry_run=not live_mode,
                 mu_post_id=mu_post_id, notes=reason or None)
    prefix = "[DRY RUN] " if not live_mode else ""
    await _send_log(bot, cfg, f"{prefix}**{event_type.upper()}** target={result.target_name} outcome={outcome}" + (f" shooter={shooter}" if shooter else ""))
    reply_text = f"{prefix}Vest popped on {result.target_name} (no kill)." if vest else result.message
    message = reply_text + (f"\n{post_link}" if post_link else "")
    return result, message


async def resolve_bomb_action(*, bot, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool,
                              host_channel_id: int, bomber_name: str, bombee_name: str, reason: str = "",
                              mode: str | None = None):
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    mode = _normalize_mode(mode)
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

    vest = mode == "vest"
    # Only the bombee can be protected (the bomber always dies). Guard against BPV.
    if not vest and mode != "confirm":
        warning = bpv_warning(bomb.bombee, state)
        if warning:
            return None, warning

    mu_post_id = None
    post_link = None
    if live_mode:
        bomber_kill = await asyncio.to_thread(mu_client.kill, cfg.thread_id, bomb.bomber.mu_username)
        bomber_ok = isinstance(bomber_kill, dict) and "successful" in bomber_kill.get("response", "").lower()
        if not bomber_ok:
            return None, f"MU kill did not confirm success for {bomb.bomber.player} — post/threadmark skipped. MU said: {bomber_kill}"
        bomb.mu_response_bomber = bomber_kill
        if not vest:
            bombee_kill = await asyncio.to_thread(mu_client.kill, cfg.thread_id, bomb.bombee.mu_username)
            bombee_ok = isinstance(bombee_kill, dict) and "successful" in bombee_kill.get("response", "").lower()
            if not bombee_ok:
                return None, f"MU kill did not confirm success for {bomb.bombee.player} — post/threadmark skipped. MU said: {bombee_kill}"
            bomb.mu_response_bombee = bombee_kill
        announcement = bomb.build_announcement(reason, vest=vest)
        reply, _threadmark_response = await asyncio.to_thread(mu_client.post_reply_with_threadmark, cfg.thread_id, announcement, bomb.threadmark_name(vest=vest))
        mu_post_id = reply.post_id
        post_link = _post_link(reply, cfg.thread_id)
        bomb.announcement_post_id = reply.post_id
        bomb.threadmark_ok = True

    bomb.dry_run = not live_mode
    victims = [bomb.bomber] if vest else [bomb.bomber, bomb.bombee]
    for player in victims:
        db.mark_dead(cfg.host_channel_id, cfg.name, player.player, "bomb")
        db.log_event(cfg.host_channel_id, cfg.name, "bomb", player.player, "killed", dry_run=not live_mode,
                     mu_post_id=mu_post_id, notes=reason or None)

    prefix = "[DRY RUN] " if not live_mode else ""
    if vest:
        message = f"{prefix}Bomb resolved: {bomb.bomber.player} is dead; {bomb.bombee.player} survived (vest)."
        log_outcome = f"bomber={bomb.bomber.player} bombee={bomb.bombee.player} outcome=vest_pop"
    else:
        message = f"{prefix}Bomb resolved: {bomb.bomber.player} and {bomb.bombee.player} are dead."
        log_outcome = f"bomber={bomb.bomber.player} bombee={bomb.bombee.player} outcome=killed"
    if post_link:
        message += f"\n{post_link}"
    await _send_log(bot, cfg, f"{prefix}**BOMB** {log_outcome}")
    return bomb, message


async def _modbot_precheck(mu_client, cfg, target) -> str | None:
    """Return an abort message if MU modbot already shows the target dead, else None."""
    if not cfg.game_id:
        return None
    mu_statuses = await asyncio.to_thread(mu_client.fetch_player_statuses, cfg.game_id)
    if mu_statuses.get(target.mu_username.lower()) is False:
        return f"{target.player} is already dead in MU modbot — kill aborted."
    return None


def _kill_confirmed(kill_response) -> bool:
    return isinstance(kill_response, dict) and "successful" in kill_response.get("response", "").lower()


def _post_link(reply, thread_id) -> str | None:
    """Direct MU link to a posted reply, matching the role-post links."""
    if reply is None:
        return None
    if getattr(reply, "final_url", None):
        return reply.final_url
    post_id = getattr(reply, "post_id", None)
    if not post_id:
        return None
    return f"https://www.mafiauniverse.com/forums/threads/{thread_id}?p={post_id}#post{post_id}"


async def silent_ita_action(*, bot, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool,
                            host_channel_id: int, target_name: str, source: str | None, hitrate: float | None,
                            mode: str | None = None, rng=random.random):
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    if hitrate is None:
        hitrate = DEFAULT_SILENT_ITA_HITRATE
    mode = _normalize_mode(mode)
    state = sheet_reader.load_game_state(cfg.sheet_id)
    dead = db.dead_players(cfg.host_channel_id, cfg.name)
    for player in state.players:
        if normalize_name(player.player) in dead:
            player.alive = False

    result = resolve_silent_ita(target_name=target_name, hitrate=hitrate, state=state,
                                is_dead=lambda name: db.is_dead(cfg.host_channel_id, cfg.name, name),
                                dry_run=not live_mode, rng=rng)
    if result.already_dead or (not result.success and not result.miss):
        return result, result.message

    hit = result.success
    vest = hit and mode == "vest"
    target = resolve_player(result.target_name, state.players)

    # A hit that would post a death (not a vest pop, not already confirmed) is guarded
    # against shielded/BPV targets, since a real flip cannot be undone.
    if hit and not vest and mode != "confirm":
        warning = ita_protection_warning(target, state)
        if warning:
            return None, warning

    announcement = build_silent_ita_announcement(target, hit, vest=vest)
    threadmark = silent_ita_threadmark_name(target, hit, vest=vest)
    kills = hit and not vest  # vest pop connects but does not kill
    mu_post_id = None
    post_link = None

    if live_mode:
        if kills:
            abort = await _modbot_precheck(mu_client, cfg, target)
            if abort:
                return result, abort
            kill_response = await asyncio.to_thread(mu_client.kill, cfg.thread_id, target.mu_username)
            if not _kill_confirmed(kill_response):
                return result, f"MU kill did not confirm success for {target.player} — post/threadmark skipped. MU said: {kill_response}"
            result.mu_response = kill_response
        reply, _tm = await asyncio.to_thread(mu_client.post_reply_with_threadmark, cfg.thread_id, announcement, threadmark)
        mu_post_id = reply.post_id
        post_link = _post_link(reply, cfg.thread_id)
        result.announcement_post_id = reply.post_id
        result.threadmark_ok = True

    if kills:
        db.mark_dead(cfg.host_channel_id, cfg.name, result.target_name, "silent_ita")

    outcome = "vest_pop" if vest else ("killed" if hit else "missed")
    db.log_event(cfg.host_channel_id, cfg.name, "silent_ita", result.target_name, outcome, shooter=source,
                 roll=result.roll, hit_pct=result.hit_pct, dry_run=not live_mode, mu_post_id=mu_post_id)
    prefix = "[DRY RUN] " if not live_mode else ""
    await _send_log(bot, cfg, f"{prefix}**SILENT_ITA** target={result.target_name} outcome={outcome}" + (f" source={source}" if source else ""))
    reply_text = f"{prefix}Vest popped on {result.target_name} (no kill)." if vest else result.message
    message = reply_text + (f"\n{post_link}" if post_link else "")
    return result, message


async def ita_action(*, bot, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool,
                     host_channel_id: int, target_name: str, source: str | None, post_link: str,
                     mode: str | None = None):
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    try:
        post_id = extract_post_id_from_link(post_link)
    except ResolutionError as exc:
        return None, str(exc)

    mode = _normalize_mode(mode)
    vest = mode == "vest"
    state = sheet_reader.load_game_state(cfg.sheet_id)
    dead = db.dead_players(cfg.host_channel_id, cfg.name)
    for player in state.players:
        if normalize_name(player.player) in dead:
            player.alive = False
    try:
        target = resolve_player(target_name, state.players)
    except ResolutionError as exc:
        return None, str(exc)
    if db.is_dead(cfg.host_channel_id, cfg.name, target.player) or not target.alive:
        return None, f"{target.player} is already dead."

    # A real flip cannot be undone, so guard a killing ITA against shielded/BPV targets.
    if not vest and mode != "confirm":
        warning = ita_protection_warning(target, state)
        if warning:
            return None, warning

    mu_post_id = None
    post_link = None
    if live_mode:
        quote_bbcode = await asyncio.to_thread(mu_client.fetch_quote_bbcode, cfg.thread_id, post_id)
        announcement = build_ita_announcement(quote_bbcode, target, vest=vest)
        shooter = extract_quote_author(quote_bbcode) or source or "Unknown"
        if not vest:
            abort = await _modbot_precheck(mu_client, cfg, target)
            if abort:
                return None, abort
            kill_response = await asyncio.to_thread(mu_client.kill, cfg.thread_id, target.mu_username)
            if not _kill_confirmed(kill_response):
                return None, f"MU kill did not confirm success for {target.player} — post/threadmark skipped. MU said: {kill_response}"
        reply, _tm = await asyncio.to_thread(
            mu_client.post_reply_with_threadmark, cfg.thread_id, announcement, ita_threadmark_name(shooter, target, vest=vest))
        mu_post_id = reply.post_id
        post_link = _post_link(reply, cfg.thread_id)

    if not vest:
        db.mark_dead(cfg.host_channel_id, cfg.name, target.player, "ita")
    outcome = "vest_pop" if vest else "killed"
    db.log_event(cfg.host_channel_id, cfg.name, "ita", target.player, outcome, shooter=source,
                 dry_run=not live_mode, mu_post_id=mu_post_id, notes=f"quote post {post_id}")
    prefix = "[DRY RUN] " if not live_mode else ""
    await _send_log(bot, cfg, f"{prefix}**ITA** target={target.player} outcome={outcome}" + (f" source={source}" if source else ""))
    reply_text = f"{prefix}Vest popped on {target.player} (no kill)." if vest else f"{prefix}ITA hit: {target.player} is dead."
    message = reply_text + (f"\n{post_link}" if post_link else "")
    result = ResolveResult(True, target.player, "ita", message, dry_run=not live_mode, announcement_post_id=mu_post_id)
    return result, message


async def ita_roll_action(*, bot, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool,
                          host_channel_id: int, target_name: str, shooter: str | None, accuracy: float,
                          rng=random.random):
    """Roll an ITA against a given accuracy and report the result only.

    Never posts to the MU thread, never kills, never marks the player dead — it is a
    pure dice roll plus Discord/log reporting. Behaves the same in live and dry-run.
    """
    cfg = db.get_active_game(host_channel_id)
    if cfg is None:
        return None, "No active game. Use `!use_game <name>` first."
    state = sheet_reader.load_game_state(cfg.sheet_id)
    dead = db.dead_players(cfg.host_channel_id, cfg.name)
    for player in state.players:
        if normalize_name(player.player) in dead:
            player.alive = False

    result = resolve_silent_ita(target_name=target_name, hitrate=accuracy, state=state,
                                is_dead=lambda name: db.is_dead(cfg.host_channel_id, cfg.name, name),
                                dry_run=True, rng=rng)
    if result.already_dead or (not result.success and not result.miss):
        return result, result.message

    outcome = "hit" if result.success else "miss"
    db.log_event(cfg.host_channel_id, cfg.name, "ita_roll", result.target_name, outcome, shooter=shooter,
                 roll=result.roll, hit_pct=result.hit_pct, dry_run=not live_mode)
    await _send_log(bot, cfg, f"**ITA ROLL** target={result.target_name} outcome={outcome} "
                              f"roll={result.roll:.1f} acc={accuracy:.1f}" + (f" shooter={shooter}" if shooter else ""))
    verb = "HIT" if result.success else "MISS"
    message = f"ITA {verb}: {result.target_name} (rolled {result.roll:.1f} vs {accuracy:.1f}%)"
    return result, message


def register(bot, *, db: HostOpsDB, sheet_reader: SheetReader, mu_client: MUClient, live_mode: bool) -> None:
    async def _single_target_kill(ctx, args: str, event_type: str) -> None:
        player, reason, mode = parse_pipe_args(args, 3)
        if not player:
            await ctx.reply(f"Usage: `!{event_type} <player> | <reason> | [confirm|vest]`")
            return
        _result, message = await resolve_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, target_name=player, event_type=event_type, reason=reason, mode=mode)
        await ctx.reply(message)

    @bot.command(name="kill")
    async def kill(ctx, *, args: str = ""):
        await _single_target_kill(ctx, args, "kill")

    @bot.command(name="dayvig")
    async def dayvig(ctx, *, args: str = ""):
        await _single_target_kill(ctx, args, "dayvig")

    @bot.command(name="desperado")
    async def desperado(ctx, *, args: str = ""):
        await _single_target_kill(ctx, args, "desperado")

    @bot.command(name="bomb")
    async def bomb(ctx, *, args: str = ""):
        bomber, bombee, reason, mode = parse_pipe_args(args, 4)
        if not bomber or not bombee:
            await ctx.reply("Usage: `!bomb <bomber> | <bombee> | <reason> | [confirm|vest]`")
            return
        _result, message = await resolve_bomb_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=live_mode, host_channel_id=ctx.channel.id, bomber_name=bomber, bombee_name=bombee, reason=reason, mode=mode)
        await ctx.reply(message)

    @bot.command(name="silent_ita")
    async def silent_ita(ctx, *, args: str = ""):
        target, source, hitrate_raw, mode = parse_pipe_args(args, 4)
        if not target:
            await ctx.reply("Usage: `!silent_ita <target> | <source> | <hitrate> | [confirm|vest]` (hitrate default 18)")
            return
        try:
            hitrate = float(hitrate_raw.rstrip("%").strip()) if hitrate_raw else None
        except ValueError:
            await ctx.reply(f"Invalid hitrate: `{hitrate_raw}`")
            return
        _result, message = await silent_ita_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client,
                                                    live_mode=live_mode, host_channel_id=ctx.channel.id,
                                                    target_name=target, source=source or None, hitrate=hitrate, mode=mode)
        await ctx.reply(message)

    @bot.command(name="ita")
    async def ita(ctx, *, args: str = ""):
        target, source, post_link, mode = parse_pipe_args(args, 4)
        if not target or not post_link:
            await ctx.reply("Usage: `!ita <target> | <source> | <post link> | [confirm|vest]`")
            return
        _result, message = await ita_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client,
                                            live_mode=live_mode, host_channel_id=ctx.channel.id,
                                            target_name=target, source=source or None, post_link=post_link, mode=mode)
        await ctx.reply(message)

    @bot.command(name="resolve_ita")
    async def resolve_ita(ctx, *, args: str = ""):
        target, shooter, accuracy_raw = parse_pipe_args(args, 3)
        if not target or not accuracy_raw:
            await ctx.reply("Usage: `!resolve_ita <target> | <shooter> | <accuracy%>`")
            return
        try:
            accuracy = float(accuracy_raw.rstrip("%").strip())
        except ValueError:
            await ctx.reply(f"Invalid accuracy: `{accuracy_raw}`")
            return
        _result, message = await ita_roll_action(bot=bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client,
                                                 live_mode=live_mode, host_channel_id=ctx.channel.id,
                                                 target_name=target, shooter=shooter or None, accuracy=accuracy)
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

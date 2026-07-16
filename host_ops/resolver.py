from __future__ import annotations

import random
import re
from collections.abc import Callable

from .models import BombResolveResult, GameState, ITASettings, Player, Protection, ResolveResult, normalize_name

_POST_ID_LINK_RE = re.compile(r"(?:#post|[?&]p=)(\d+)")


class ResolutionError(ValueError):
    pass


def resolve_player(name: str, players: list[Player]) -> Player:
    wanted = normalize_name(name)
    exact = [player for player in players if normalize_name(player.player) == wanted or normalize_name(player.mu_username) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [player for player in players if wanted and wanted in normalize_name(player.player)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise ResolutionError("Ambiguous player name: " + ", ".join(p.player for p in partial))
    raise ResolutionError(f"Unknown player: {name}")


def find_blocking_protection(target: Player, event_type: str, phase: str, protections: list[Protection]) -> Protection | None:
    target_keys = {normalize_name(target.player), normalize_name(target.mu_username)}
    for protection in protections:
        if normalize_name(protection.target) in target_keys and protection.blocks(event_type, phase):
            return protection
    return None


def choose_ita_settings(target: Player, phase: str, settings: list[ITASettings]) -> ITASettings:
    phase_key = normalize_name(phase or "any")
    target_key = normalize_name(target.player)
    candidates = [s for s in settings if normalize_name(s.phase or "any") in {"any", phase_key}]
    specific = [s for s in candidates if normalize_name(s.player) == target_key]
    if specific:
        return specific[-1]
    global_rows = [s for s in candidates if not normalize_name(s.player)]
    return global_rows[-1] if global_rows else ITASettings(default_hit_pct=0.0)


def ita_hit_pct(target: Player, phase: str, settings: list[ITASettings]) -> tuple[float, bool]:
    chosen = choose_ita_settings(target, phase, settings)
    if chosen.immune:
        return 0.0, True
    base = chosen.hit_pct_override if chosen.hit_pct_override is not None else chosen.default_hit_pct
    return max(0.0, min(100.0, base + chosen.bonus - chosen.penalty)), False


def build_death_block(target: Player) -> str:
    return f"[B]{target.player}[/B] has died. [B]{target.player}[/B] was:\n\n[SPOILER]{target.redacted_role_pm}[/SPOILER]"


def build_death_announcement(target: Player, event_type: str, reason: str = "") -> str:
    if event_type == "ita":
        header = "[CENTER][TITLE][B]An ITA hits![/B][/TITLE][/CENTER]"
    elif event_type == "desperado":
        header = "[CENTER][TITLE][B]A desperado shot rings out![/B][/TITLE][/CENTER]"
    else:
        header = "[CENTER][TITLE][B]A shot rings out![/B][/TITLE][/CENTER]"
    reason_text = f"\n\n{reason.strip()}" if reason and reason.strip() else ""
    return f"{header}\n\n{build_death_block(target)}{reason_text}"


def threadmark_name(target: Player, event_type: str) -> str:
    if event_type == "ita":
        label = "An ITA hits!"
    elif event_type == "desperado":
        label = "A desperado shot rings out!"
    else:
        label = "A shot rings out!"
    suffix = f", {target.role_name}" if target.role_name else ""
    return f"{label} {target.player} is dead{suffix}"


def resolve_bomb(*, bomber_name: str, bombee_name: str, state: GameState,
                 is_dead: Callable[[str], bool] = lambda _name: False) -> BombResolveResult:
    bomber = resolve_player(bomber_name, state.players)
    bombee = resolve_player(bombee_name, state.players)
    if bomber.key == bombee.key:
        raise ResolutionError("Bomber and bombee cannot be the same player.")
    for player in (bomber, bombee):
        if is_dead(player.player) or not player.alive:
            raise ResolutionError(f"{player.player} is already dead.")
    return BombResolveResult(bomber=bomber, bombee=bombee)


def resolve_death(*, target_name: str, event_type: str, phase: str, state: GameState,
                  is_dead: Callable[[str], bool] = lambda _name: False,
                  dry_run: bool = True, rng: Callable[[], float] = random.random) -> ResolveResult:
    try:
        target = resolve_player(target_name, state.players)
    except ResolutionError as exc:
        return ResolveResult(False, target_name, event_type, str(exc), dry_run=dry_run)
    if is_dead(target.player) or not target.alive:
        return ResolveResult(False, target.player, event_type, f"{target.player} is already dead.", dry_run=dry_run, already_dead=True)
    blocker = find_blocking_protection(target, event_type, phase, state.protections)
    if blocker:
        source = blocker.source or blocker.protection_type or "protection"
        return ResolveResult(False, target.player, event_type, f"{target.player} was protected by {source}.", blocked_by=source, dry_run=dry_run)
    if event_type == "ita":
        hit_pct, immune = ita_hit_pct(target, phase, state.ita_settings)
        if immune:
            return ResolveResult(False, target.player, event_type, f"{target.player} is ITA immune.", blocked_by="ITA immune", hit_pct=0.0, dry_run=dry_run)
        roll = rng() * 100
        if roll > hit_pct:
            return ResolveResult(False, target.player, event_type, f"ITA on {target.player} missed ({roll:.1f} > {hit_pct:.1f}).", miss=True, roll=roll, hit_pct=hit_pct, dry_run=dry_run)
        return ResolveResult(True, target.player, event_type, f"ITA on {target.player} hit ({roll:.1f} <= {hit_pct:.1f}).", roll=roll, hit_pct=hit_pct, dry_run=dry_run)
    return ResolveResult(True, target.player, event_type, f"{target.player} would be killed." if dry_run else f"{target.player} was killed.", dry_run=dry_run)


def resolve_silent_ita(*, target_name: str, hitrate: float, state: GameState,
                       is_dead: Callable[[str], bool] = lambda _name: False,
                       dry_run: bool = True, rng: Callable[[], float] = random.random) -> ResolveResult:
    """Silent ITA: roll against a caller-supplied hit rate. Sheet ITA settings are ignored."""
    try:
        target = resolve_player(target_name, state.players)
    except ResolutionError as exc:
        return ResolveResult(False, target_name, "silent_ita", str(exc), dry_run=dry_run)
    if is_dead(target.player) or not target.alive:
        return ResolveResult(False, target.player, "silent_ita", f"{target.player} is already dead.", dry_run=dry_run, already_dead=True)
    roll = rng() * 100
    if roll > hitrate:
        return ResolveResult(False, target.player, "silent_ita", f"Silent ITA on {target.player} missed ({roll:.1f} > {hitrate:.1f}).", miss=True, roll=roll, hit_pct=hitrate, dry_run=dry_run)
    return ResolveResult(True, target.player, "silent_ita", f"Silent ITA on {target.player} hit ({roll:.1f} <= {hitrate:.1f}).", roll=roll, hit_pct=hitrate, dry_run=dry_run)


def build_silent_ita_announcement(target: Player, hit: bool) -> str:
    header = "[BANNER]A Silent Shot Rings Out![/BANNER]"
    if not hit:
        return f"{header}\n\n[B]Miss![/B]"
    return f"{header}\n\n[B]Hit![/B]\n\n{build_death_block(target)}"


def silent_ita_threadmark_name(target: Player, hit: bool) -> str:
    if not hit:
        return "A Silent Shot Rings Out! Miss"
    return f"A Silent Shot Rings Out! {target.player} is dead"


def build_ita_announcement(quote_bbcode: str, target: Player) -> str:
    """Quote (already wrapped by MU) + Hit! + standard death reveal."""
    return f"{quote_bbcode.strip()}\n\n[B]Hit![/B]\n\n{build_death_block(target)}"


def extract_post_id_from_link(link: str) -> str:
    match = _POST_ID_LINK_RE.search(link or "")
    if not match:
        raise ResolutionError(f"Could not find a post id in link: {link}")
    return match.group(1)

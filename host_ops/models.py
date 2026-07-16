from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def normalize_name(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


@dataclass(slots=True)
class Player:
    player: str
    mu_username: str
    role_pm: str = ""
    redacted_role_pm: str = ""
    alive: bool = True
    alignment: str = ""
    role_name: str = ""
    notes: str = ""

    @property
    def key(self) -> str:
        return normalize_name(self.player)


@dataclass(slots=True)
class Protection:
    phase: str
    target: str
    protection_type: str = ""
    source: str = ""
    uses: int = -1
    active: bool = True
    blocks_events: str = "any"
    notes: str = ""

    def blocks(self, event_type: str, phase: str) -> bool:
        if not self.active or self.uses == 0:
            return False
        own_phase = normalize_name(self.phase or "any")
        event_phase = normalize_name(phase or "any")
        if own_phase not in {"", "any", event_phase} and event_phase != "any":
            return False
        blocked = {normalize_name(piece) for piece in str(self.blocks_events or "").replace(";", ",").split(",") if piece.strip()}
        if not blocked:
            blocked = {normalize_name(self.protection_type or "any")}
        return "any" in blocked or normalize_name(event_type) in blocked


@dataclass(slots=True)
class ITASettings:
    phase: str = "any"
    default_hit_pct: float = 0.0
    player: str = ""
    hit_pct_override: float | None = None
    immune: bool = False
    bonus: float = 0.0
    penalty: float = 0.0
    shots_allowed: int = -1
    vulnerability: int = 0
    shield_status: int = 0
    bpv_status: int = 0


@dataclass(slots=True)
class GameConfig:
    name: str
    thread_id: int
    sheet_id: str
    host_channel_id: int
    log_channel_id: int | None = None
    game_id: int | None = None
    active: bool = True


@dataclass(slots=True)
class GameState:
    players: list[Player] = field(default_factory=list)
    protections: list[Protection] = field(default_factory=list)
    ita_settings: list[ITASettings] = field(default_factory=list)


@dataclass(slots=True)
class PostedReply:
    text: str
    status_code: int
    final_url: str
    post_id: str | None


@dataclass(slots=True)
class BombResolveResult:
    bomber: Player
    bombee: Player
    mu_response_bomber: Any = None
    mu_response_bombee: Any = None
    announcement_post_id: str | None = None
    threadmark_ok: bool = False
    dry_run: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def build_announcement(self, reason: str = "", vest: bool = False) -> str:
        from .resolver import build_death_block

        reason_text = f"\n\n{reason.strip()}" if reason and reason.strip() else ""
        header = "[CENTER][TITLE][B]A bomb goes off![/B][/TITLE][/CENTER]"
        if vest:
            # bombee is vested: only the bomber dies (with reveal); the bombee survives
            # and is not named.
            return f"{header}\n\n{build_death_block(self.bomber)}\n\n[B]BOOM! No one else has died.[/B]{reason_text}"
        blocks = "\n\n".join(build_death_block(p) for p in (self.bomber, self.bombee))
        return f"{header}\n\n{blocks}{reason_text}"

    def threadmark_name(self, vest: bool = False) -> str:
        if vest:
            return f"A bomb goes off! {self.bomber.player} is dead"
        return f"A bomb goes off! {self.bomber.player} and {self.bombee.player} are dead"


@dataclass(slots=True)
class ResolveResult:
    success: bool
    target_name: str
    event_type: str
    message: str
    blocked_by: str | None = None
    miss: bool = False
    roll: float | None = None
    hit_pct: float | None = None
    dry_run: bool = True
    already_dead: bool = False
    mu_response: Any = None
    announcement_post_id: str | None = None
    threadmark_ok: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

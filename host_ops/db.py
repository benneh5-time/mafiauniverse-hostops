from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import GameConfig, normalize_name

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    host_channel_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    thread_id INTEGER NOT NULL,
    game_id INTEGER,
    sheet_id TEXT NOT NULL,
    log_channel_id INTEGER,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (host_channel_id, name)
);
CREATE TABLE IF NOT EXISTS deaths (
    host_channel_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    player_key TEXT NOT NULL,
    player_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (host_channel_id, game_name, player_key)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_channel_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    target_player TEXT NOT NULL,
    shooter TEXT,
    outcome TEXT NOT NULL,
    blocked_by TEXT,
    roll REAL,
    hit_pct REAL,
    dry_run INTEGER NOT NULL DEFAULT 1,
    mu_post_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ita_seen_posts (
    host_channel_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    mu_post_id TEXT NOT NULL,
    PRIMARY KEY (host_channel_id, game_name, mu_post_id)
);
CREATE TABLE IF NOT EXISTS ita_poll_state (
    host_channel_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    last_post_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (host_channel_id, game_name)
);
"""


class HostOpsDB:
    def __init__(self, path: str | Path = Path("data/host_ops.db")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_game(self, cfg: GameConfig) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO games
                   (host_channel_id, name, thread_id, game_id, sheet_id, log_channel_id, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(host_channel_id, name) DO UPDATE SET
                     thread_id=excluded.thread_id,
                     game_id=excluded.game_id,
                     sheet_id=excluded.sheet_id,
                     log_channel_id=excluded.log_channel_id,
                     active=excluded.active,
                     updated_at=datetime('now')""",
                (cfg.host_channel_id, cfg.name, cfg.thread_id, cfg.game_id, cfg.sheet_id, cfg.log_channel_id, int(cfg.active)),
            )

    def get_game(self, host_channel_id: int, name: str) -> GameConfig | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE host_channel_id = ? AND name = ?",
                (host_channel_id, name),
            ).fetchone()
        return _row_to_game(row) if row else None

    def set_active_game(self, host_channel_id: int, name: str) -> GameConfig | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE host_channel_id = ? AND name = ?",
                (host_channel_id, name),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE games SET active = 0 WHERE host_channel_id = ?", (host_channel_id,))
            conn.execute(
                "UPDATE games SET active = 1, updated_at = datetime('now') WHERE host_channel_id = ? AND name = ?",
                (host_channel_id, name),
            )
        return self.get_game(host_channel_id, name)

    def get_active_game(self, host_channel_id: int) -> GameConfig | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM games WHERE host_channel_id = ? AND active = 1 ORDER BY updated_at DESC LIMIT 1",
                (host_channel_id,),
            ).fetchone()
        return _row_to_game(row) if row else None


    def list_active_games(self) -> list[GameConfig]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM games WHERE active = 1 ORDER BY host_channel_id, updated_at DESC").fetchall()
        return [_row_to_game(row) for row in rows]

    def set_log_channel(self, host_channel_id: int, game_name: str, log_channel_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE games SET log_channel_id = ?, updated_at = datetime('now') WHERE host_channel_id = ? AND name = ?",
                (log_channel_id, host_channel_id, game_name),
            )

    def mark_dead(self, host_channel_id: int, game_name: str, player_name: str, event_type: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO deaths
                   (host_channel_id, game_name, player_key, player_name, event_type)
                   VALUES (?, ?, ?, ?, ?)""",
                (host_channel_id, game_name, normalize_name(player_name), player_name, event_type),
            )

    def mark_alive(self, host_channel_id: int, game_name: str, player_name: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM deaths WHERE host_channel_id = ? AND game_name = ? AND player_key = ?",
                (host_channel_id, game_name, normalize_name(player_name)),
            )
        return cursor.rowcount > 0

    def is_dead(self, host_channel_id: int, game_name: str, player_name: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM deaths WHERE host_channel_id = ? AND game_name = ? AND player_key = ?",
                (host_channel_id, game_name, normalize_name(player_name)),
            ).fetchone()
        return row is not None

    def dead_players(self, host_channel_id: int, game_name: str) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT player_key FROM deaths WHERE host_channel_id = ? AND game_name = ?",
                (host_channel_id, game_name),
            ).fetchall()
        return {row["player_key"] for row in rows}

    def log_event(self, host_channel_id: int, game_name: str, event_type: str, target_player: str, outcome: str,
                  *, shooter: str | None = None, blocked_by: str | None = None, roll: float | None = None,
                  hit_pct: float | None = None, dry_run: bool = True, mu_post_id: str | None = None,
                  notes: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO events
                   (host_channel_id, game_name, event_type, target_player, shooter, outcome,
                    blocked_by, roll, hit_pct, dry_run, mu_post_id, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (host_channel_id, game_name, event_type, target_player, shooter, outcome, blocked_by,
                 roll, hit_pct, int(dry_run), mu_post_id, notes),
            )

    def get_events(self, host_channel_id: int, game_name: str, target_player: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if target_player:
                rows = conn.execute(
                    """SELECT * FROM events WHERE host_channel_id = ? AND game_name = ?
                       AND lower(target_player) = lower(?) ORDER BY id""",
                    (host_channel_id, game_name, target_player),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE host_channel_id = ? AND game_name = ? ORDER BY id",
                    (host_channel_id, game_name),
                ).fetchall()
        return [dict(row) for row in rows]

    def mark_ita_seen(self, host_channel_id: int, game_name: str, post_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO ita_seen_posts (host_channel_id, game_name, mu_post_id) VALUES (?, ?, ?)",
                (host_channel_id, game_name, post_id),
            )

    def is_ita_seen(self, host_channel_id: int, game_name: str, post_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM ita_seen_posts WHERE host_channel_id = ? AND game_name = ? AND mu_post_id = ?",
                (host_channel_id, game_name, post_id),
            ).fetchone()
        return row is not None

    def get_ita_poll_checkpoint(self, host_channel_id: int, game_name: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_post_id FROM ita_poll_state WHERE host_channel_id = ? AND game_name = ?",
                (host_channel_id, game_name),
            ).fetchone()
        return int(row["last_post_id"]) if row else 0

    def set_ita_poll_checkpoint(self, host_channel_id: int, game_name: str, post_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO ita_poll_state (host_channel_id, game_name, last_post_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(host_channel_id, game_name) DO UPDATE SET last_post_id = excluded.last_post_id""",
                (host_channel_id, game_name, post_id),
            )


def _row_to_game(row: sqlite3.Row) -> GameConfig:
    return GameConfig(
        name=row["name"],
        thread_id=int(row["thread_id"]),
        sheet_id=row["sheet_id"],
        host_channel_id=int(row["host_channel_id"]),
        log_channel_id=int(row["log_channel_id"]) if row["log_channel_id"] is not None else None,
        game_id=int(row["game_id"]) if row["game_id"] is not None else None,
        active=bool(row["active"]),
    )

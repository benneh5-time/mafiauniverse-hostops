from __future__ import annotations

from host_ops.models import GameConfig


def test_game_config_is_channel_scoped(db):
    db.upsert_game(GameConfig("g", 1, "s1", 10, active=True))
    db.upsert_game(GameConfig("g", 2, "s2", 20, active=True))
    assert db.get_active_game(10).thread_id == 1
    assert db.get_active_game(20).thread_id == 2


def test_death_overlay_and_events(db):
    db.upsert_game(GameConfig("g", 1, "s", 10, active=True))
    db.mark_dead(10, "g", "Alice", "kill")
    assert db.is_dead(10, "g", "alice")
    db.log_event(10, "g", "kill", "Alice", "killed", dry_run=True)
    assert db.get_events(10, "g", "Alice")[0]["outcome"] == "killed"


def test_ita_dedupe(db):
    assert not db.is_ita_seen(10, "g", "123")
    db.mark_ita_seen(10, "g", "123")
    db.mark_ita_seen(10, "g", "123")
    assert db.is_ita_seen(10, "g", "123")

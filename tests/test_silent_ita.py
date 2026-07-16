from __future__ import annotations

import pytest

from host_ops.models import GameState, ITASettings, Player
from host_ops.resolver import (
    ResolutionError,
    build_ita_announcement,
    build_silent_ita_announcement,
    extract_post_id_from_link,
    resolve_silent_ita,
    silent_ita_threadmark_name,
)


@pytest.fixture
def state():
    return GameState(
        players=[
            Player("Alice", "alice_mu", "PM", "Redacted Alice", True, "town", role_name="Cop"),
            Player("Bob", "bob_mu", "PM", "Redacted Bob", True, "mafia"),
        ],
        protections=[],
        # Sheet ITA settings should be IGNORED by silent ITA; make them wildly different.
        ita_settings=[ITASettings(phase="any", default_hit_pct=100.0, player="", immune=True)],
    )


def test_silent_ita_hit_when_roll_under_hitrate(state):
    result = resolve_silent_ita(target_name="Alice", hitrate=18.0, state=state, rng=lambda: 0.1)
    assert result.success
    assert not result.miss
    assert result.hit_pct == 18.0


def test_silent_ita_miss_when_roll_over_hitrate(state):
    result = resolve_silent_ita(target_name="Alice", hitrate=18.0, state=state, rng=lambda: 0.5)
    assert not result.success
    assert result.miss


def test_silent_ita_ignores_sheet_immunity_and_default(state):
    # Sheet says Alice is immune @ 100%; silent ITA must ignore it and use the passed rate.
    hit = resolve_silent_ita(target_name="Alice", hitrate=90.0, state=state, rng=lambda: 0.5)
    assert hit.success  # 50 <= 90 -> hit, despite sheet immunity
    miss = resolve_silent_ita(target_name="Alice", hitrate=10.0, state=state, rng=lambda: 0.5)
    assert miss.miss  # 50 > 10 -> miss


def test_silent_ita_already_dead_short_circuits(state):
    result = resolve_silent_ita(target_name="Alice", hitrate=99.0, state=state,
                                is_dead=lambda name: name == "Alice", rng=lambda: 0.0)
    assert not result.success
    assert result.already_dead


def test_silent_ita_unknown_player(state):
    result = resolve_silent_ita(target_name="Nobody", hitrate=18.0, state=state)
    assert not result.success
    assert "Unknown player" in result.message


def test_silent_ita_announcement_miss_has_banner_and_miss():
    target = Player("Alice", "alice_mu", "PM", "Redacted Alice")
    text = build_silent_ita_announcement(target, hit=False)
    assert "[BANNER]A Silent Shot Rings Out![/BANNER]" in text
    assert "[B]Miss![/B]" in text
    assert "Redacted Alice" not in text  # no role reveal on a miss


def test_silent_ita_announcement_hit_has_banner_hit_and_reveal():
    target = Player("Alice", "alice_mu", "PM", "Redacted Alice")
    text = build_silent_ita_announcement(target, hit=True)
    assert "[BANNER]A Silent Shot Rings Out![/BANNER]" in text
    assert "[B]Hit![/B]" in text
    assert "Alice" in text
    assert "[SPOILER]Redacted Alice[/SPOILER]" in text


def test_silent_ita_threadmark_hit_names_target_no_role():
    target = Player("Alice", "alice_mu", "PM", "Redacted Alice", role_name="Cop")
    name = silent_ita_threadmark_name(target, hit=True)
    assert name == "A Silent Shot Rings Out! Alice is dead"
    assert "Cop" not in name


def test_silent_ita_threadmark_miss_reveals_nothing():
    target = Player("Alice", "alice_mu", "PM", "Redacted Alice")
    name = silent_ita_threadmark_name(target, hit=False)
    assert name == "A Silent Shot Rings Out! Miss"
    assert "Alice" not in name


def test_ita_announcement_uses_quote_verbatim_then_hit_and_reveal():
    target = Player("Bob", "bob_mu", "PM", "Redacted Bob")
    quote = "[QUOTE=Label;123]original [B]bbcode[/B][/QUOTE]"
    text = build_ita_announcement(quote, target)
    assert text.startswith(quote)
    assert "[B]Hit![/B]" in text
    assert "[SPOILER]Redacted Bob[/SPOILER]" in text
    # must not double-wrap
    assert text.count("[QUOTE=") == 1


def test_extract_post_id_from_anchor_link():
    assert extract_post_id_from_link("https://www.mafiauniverse.com/forums/threads/9/page5#post11042484") == "11042484"


def test_extract_post_id_from_query_link():
    assert extract_post_id_from_link("https://www.mafiauniverse.com/forums/showthread.php?p=11042484") == "11042484"


def test_extract_post_id_unparseable_raises():
    with pytest.raises(ResolutionError):
        extract_post_id_from_link("https://www.mafiauniverse.com/forums/threads/9/")

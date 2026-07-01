from __future__ import annotations

import pytest

from host_ops.models import GameState, ITASettings, Player, Protection
from host_ops.resolver import ResolutionError, resolve_bomb, resolve_death


def test_successful_kill(basic_state):
    assert resolve_death(target_name="Alice", event_type="kill", phase="any", state=basic_state).success


def test_already_dead_overlay_blocks(basic_state):
    result = resolve_death(target_name="Alice", event_type="kill", phase="any", state=basic_state, is_dead=lambda name: name == "Alice")
    assert not result.success
    assert result.already_dead


def test_protection_blocks_matching_event():
    state = GameState(players=[Player("Alice", "alice_mu", redacted_role_pm="r")], protections=[Protection("any", "Alice", "doc", "Doc", 1, True, "kill")], ita_settings=[])
    result = resolve_death(target_name="Alice", event_type="kill", phase="any", state=state)
    assert not result.success
    assert result.blocked_by == "Doc"


def test_ita_hit_and_miss(basic_state):
    hit = resolve_death(target_name="Bob", event_type="ita", phase="any", state=basic_state, rng=lambda: 0.1)
    miss = resolve_death(target_name="Bob", event_type="ita", phase="any", state=basic_state, rng=lambda: 0.9)
    assert hit.success
    assert not miss.success and miss.miss


def test_ita_immune_target():
    state = GameState(players=[Player("Bob", "bob_mu", redacted_role_pm="r")], protections=[], ita_settings=[ITASettings("any", 50.0, "Bob", None, True)])
    result = resolve_death(target_name="Bob", event_type="ita", phase="any", state=state)
    assert not result.success
    assert result.blocked_by == "ITA immune"


def test_player_specific_override():
    state = GameState(players=[Player("Bob", "bob_mu", redacted_role_pm="r")], protections=[], ita_settings=[ITASettings("any", 10.0, "", None, False), ITASettings("any", 10.0, "Bob", 90.0, False)])
    result = resolve_death(target_name="Bob", event_type="ita", phase="any", state=state, rng=lambda: 0.8)
    assert result.success
    assert result.hit_pct == 90.0


def test_bomb_resolves_both_targets(basic_state):
    result = resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state)
    assert result.bomber.player == "Alice"
    assert result.bombee.player == "Bob"


def test_bomb_unknown_bomber_raises(basic_state):
    with pytest.raises(ResolutionError, match="Unknown player: Carol"):
        resolve_bomb(bomber_name="Carol", bombee_name="Bob", state=basic_state)


def test_bomb_unknown_bombee_raises(basic_state):
    with pytest.raises(ResolutionError, match="Unknown player: Carol"):
        resolve_bomb(bomber_name="Alice", bombee_name="Carol", state=basic_state)


def test_bomb_already_dead_bomber_raises(basic_state):
    with pytest.raises(ResolutionError, match="Alice is already dead"):
        resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state, is_dead=lambda name: name == "Alice")


def test_bomb_already_dead_bombee_raises(basic_state):
    with pytest.raises(ResolutionError, match="Bob is already dead"):
        resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state, is_dead=lambda name: name == "Bob")


def test_bomb_same_target_twice_raises(basic_state):
    with pytest.raises(ResolutionError, match="cannot be the same player"):
        resolve_bomb(bomber_name="Alice", bombee_name="Alice", state=basic_state)


def test_bomb_announcement_has_bomb_header_and_both_deaths(basic_state):
    result = resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state)
    announcement = result.build_announcement(reason="Boom.")
    assert "A bomb goes off!" in announcement
    assert "Alice" in announcement
    assert "Bob" in announcement
    assert "Redacted Alice" in announcement
    assert "Redacted Bob" in announcement
    assert "Boom." in announcement


def test_bomb_threadmark_name_mentions_both(basic_state):
    result = resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state)
    name = result.threadmark_name()
    assert "A bomb goes off!" in name
    assert "Alice" in name
    assert "Bob" in name

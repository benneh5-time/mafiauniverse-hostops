from __future__ import annotations

from host_ops.models import GameState, ITASettings, Player, Protection
from host_ops.resolver import resolve_death


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

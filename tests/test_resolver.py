from __future__ import annotations

import pytest

from host_ops.models import GameState, ITASettings, Player, Protection
from host_ops.resolver import (
    ResolutionError,
    build_death_announcement,
    elim_threadmark_name,
    ita_hit_pct,
    resolve_bomb,
    resolve_death,
    threadmark_name,
)


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
    state = GameState(players=[Player("Bob", "bob_mu", redacted_role_pm="r")], protections=[], ita_settings=[ITASettings("any", 50.0, "Bob", None, 100)])
    result = resolve_death(target_name="Bob", event_type="ita", phase="any", state=state)
    assert not result.success
    assert result.blocked_by == "ITA immune"


def test_ita_partial_immunity_scales_hit_pct():
    # 50% base hit with 40% immunity -> 30% effective, not a hard block.
    state = GameState(players=[Player("Bob", "bob_mu", redacted_role_pm="r")], protections=[], ita_settings=[ITASettings("any", 50.0, "Bob", None, 40)])
    hit_pct, immune = ita_hit_pct(state.players[0], "any", state.ita_settings)
    assert not immune
    assert hit_pct == pytest.approx(30.0)


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


def test_bomb_announcement_puts_reason_above_death_blocks(basic_state):
    result = resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state)
    announcement = result.build_announcement(reason="Boom.")
    assert announcement.index("A bomb goes off!") < announcement.index("Boom.") < announcement.index("Alice")


def test_bomb_vest_announcement_puts_reason_above_death_block(basic_state):
    result = resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state)
    announcement = result.build_announcement(reason="Boom.", vest=True)
    assert announcement.index("Boom.") < announcement.index("Redacted Alice")
    assert announcement.index("Boom.") < announcement.index("No one else has died.")


def test_death_announcement_puts_reason_above_death_block(basic_state):
    target = basic_state.players[0]
    announcement = build_death_announcement(target, "dayvig", "He's dead to the gun!")
    assert announcement.index("A shot rings out!") < announcement.index("He's dead to the gun!")
    assert announcement.index("He's dead to the gun!") < announcement.index("has died")


def test_kill_uses_caller_label_as_header(basic_state):
    target = basic_state.players[0]
    kill = build_death_announcement(target, "kill", "flavor", kill_label="A gunshot rings out")
    dayvig = build_death_announcement(target, "dayvig", "flavor")
    assert "A gunshot rings out" in kill
    assert "A shot rings out!" not in kill
    assert "A shot rings out!" in dayvig
    assert threadmark_name(target, "kill", kill_label="A gunshot rings out").startswith("A gunshot rings out")


def test_kill_without_label_is_headerless(basic_state):
    """No label -> the threadmark is just the reveal, and the post has no death header."""
    target = Player("Alice", "alice_mu", "PM", "Redacted", role_name="Cop", flavor="Nosy Neighbor")
    assert threadmark_name(target, "kill") == "Alice was Nosy Neighbor, Cop"
    announcement = build_death_announcement(target, "kill", "")
    assert not announcement.startswith("[CENTER]")


def test_death_threadmark_includes_flavor_before_role_name():
    target = Player("Alice", "alice_mu", "PM", "Redacted", role_name="Cop", flavor="Nosy Neighbor")
    assert threadmark_name(target, "kill", kill_label="A Player has died!") == "A Player has died! Alice was Nosy Neighbor, Cop"


def test_elim_threadmark_includes_flavor_before_role_name():
    target = Player("Alice", "alice_mu", "PM", "Redacted", role_name="Cop", flavor="Nosy Neighbor")
    assert elim_threadmark_name(target, "2") == "Day 2 Elimination: Alice was eliminated, Nosy Neighbor, Cop"


def test_vest_pop_announcement_omits_reason(basic_state):
    target = basic_state.players[0]
    announcement = build_death_announcement(target, "kill", "He's dead to the gun!", vest=True)
    assert "He's dead to the gun!" not in announcement
    assert "No one has died." in announcement


def test_kill_vest_pop_uses_caller_label(basic_state):
    """A kill vest pop keeps the supplied flavor header, swapping the reveal for the vest line."""
    target = basic_state.players[0]
    announcement = build_death_announcement(target, "kill", "flavor", vest=True, kill_label="A gunshot rings out")
    assert "A gunshot rings out" in announcement
    assert "No one has died." in announcement
    tm = threadmark_name(target, "kill", vest=True, kill_label="A gunshot rings out")
    assert tm == "A gunshot rings out No one has died."


def test_kill_vest_pop_without_label_is_headerless(basic_state):
    target = basic_state.players[0]
    assert threadmark_name(target, "kill", vest=True) == "No one has died."


def test_dayvig_and_desperado_vest_keep_their_fixed_headers(basic_state):
    target = basic_state.players[0]
    for event_type, header in (("dayvig", "A shot rings out!"), ("desperado", "A desperado shot rings out!")):
        announcement = build_death_announcement(target, event_type, "flavor", vest=True)
        assert header in announcement


def test_bomb_threadmark_name_mentions_both(basic_state):
    result = resolve_bomb(bomber_name="Alice", bombee_name="Bob", state=basic_state)
    name = result.threadmark_name()
    assert "A bomb goes off!" in name
    assert "Alice" in name
    assert "Bob" in name

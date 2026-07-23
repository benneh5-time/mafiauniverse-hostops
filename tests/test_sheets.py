from __future__ import annotations

import pytest

from host_ops.sheets import SheetValidationError, extract_sheet_id, parse_game_state


def rows():
    return {
        "Mashy Players": [{"player": "Alice", "mu_username": "alice_mu", "role_pm": "full", "redacted_role_pm": "red", "role_name": "Town Cop", "alive": "TRUE", "alignment": "town"}],
        "Mashy Protections": [{"phase": "any", "target": "Alice", "protection_type": "doc", "source": "Doc", "uses": "1", "active": "yes", "blocks_events": "kill"}],
        "Mashy ITA Settings": [{"phase": "any", "default_hit_pct": "50", "player": "", "hit_pct_override": "", "immune": "", "bonus": "0", "penalty": "0", "shots_allowed": "-1", "vulnerability": "0", "shield_status": "0", "bpv_status": "0"}],
    }


def test_extract_sheet_id_from_url():
    assert extract_sheet_id("https://docs.google.com/spreadsheets/d/abc_123/edit") == "abc_123"


def test_parse_game_state_success():
    state = parse_game_state(rows())
    assert state.players[0].player == "Alice"
    assert state.protections[0].blocks_events == "kill"
    assert state.ita_settings[0].default_hit_pct == 50


def test_flavor_column_is_optional_and_parsed():
    assert parse_game_state(rows()).players[0].flavor == ""
    data = rows()
    data["Mashy Players"][0]["flavor"] = "Nosy Neighbor"
    player = parse_game_state(data).players[0]
    assert player.flavor == "Nosy Neighbor"
    assert player.flip_name == "Nosy Neighbor, Town Cop"


def test_missing_required_tab_fails():
    data = rows()
    del data["Mashy Players"]
    with pytest.raises(SheetValidationError):
        parse_game_state(data)


def test_duplicate_player_fails():
    data = rows()
    data["Mashy Players"].append(dict(data["Mashy Players"][0]))
    with pytest.raises(SheetValidationError, match="Duplicate"):
        parse_game_state(data)


def test_missing_redacted_pm_fails():
    data = rows()
    data["Mashy Players"][0]["redacted_role_pm"] = ""
    with pytest.raises(SheetValidationError, match="redacted"):
        parse_game_state(data)

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from host_ops.mu_client import MUClient
from host_ops.sheets import normalize_alignment, normalize_hex_color

from test_mu_client import FakeResponse, _logged_in_session


def _player_row(
    *,
    name: str,
    slot: str,
    role_name: str = "Vanilla Town",
    faction: str = "",
    faction_color: str = "#339933",
    alignment: str = "town",
    verified: str = "1",
    is_alive: str = "1",
    vote_weight: str = "1",
    hide_vote_weight: str = "0",
    flipless: str = "0",
    shield: str = "0",
    bpv: str = "0",
    card: str = "[CENTER][TITLE]Role PM[/TITLE][/CENTER]\n\nYou are Town.",
) -> str:
    def _sel(value: str, options: list[tuple[str, str]]) -> str:
        return "".join(
            f'<option value="{v}"{" selected=\"selected\"" if v == value else ""}>{label}</option>'
            for v, label in options
        )

    yes_no = [("1", "Yes"), ("0", "No")]
    no_yes = [("0", "No"), ("1", "Yes")]
    show_hide = [("0", "Show"), ("1", "Hide")]
    alignments = [("town", "Town"), ("mafia", "Mafia"), ("evil independent", "Evil Independent"), ("neutral independent", "Neutral Independent")]
    return f"""<div class="blockrow edit_player_row">
        <label>{name}:</label>
        <input type="hidden" name="name[]" value="{name}" />
        <input type="hidden" name="slot[]" value="{slot}" />
        <div class="edit_player_fields">
            <input class="textbox" type="number" step="any" name="vote_weight[]" value="{vote_weight}">
            <select name="hide_vote_weight[]">{_sel(hide_vote_weight, show_hide)}</select>
            <input class="textbox" type="number" name="ita_shield_status[]" value="{shield}">
            <input class="textbox" type="number" name="bpv_status[]" value="{bpv}">
            <select name="is_alive[]">{_sel(is_alive, yes_no)}</select>
            <select name="flipless[]">{_sel(flipless, no_yes)}</select>
            <select name="alignment[]">{_sel(alignment, alignments)}</select>
            <input class="textbox" type="text" name="faction[]" value="{faction}">
            <input class="textbox spectrum no-alpha" type="text" name="faction_color[]" value="{faction_color}">
            <input class="textbox" type="text" name="role_name[]" value="{role_name}">
            <input type="hidden" name="rolepm_verified[]" value="{verified}" />
        </div>
        <textarea name="rolepm_card[]" class="rolePM_content" data-user="{name}" style="display: none;">{card}</textarea>
    </div>"""


def _deaths_page(rows: list[str]) -> str:
    return (
        '<html><head><script>var SECURITYTOKEN = "tok123";</script></head><body>'
        '<form id="ita_settings" method="post">'
        '<input type="hidden" name="securitytoken" value="tok123" />'
        + "".join(rows)
        + "</form></body></html>"
    )


SAMPLE = _deaths_page([
    _player_row(name="gamer", slot="1", is_alive="0", shield="0", bpv="1", verified="1"),
    _player_row(name="Sprigatito", slot="2", shield="1", bpv="0", verified="1"),
    _player_row(
        name="TheJoker", slot="6", role_name="Mafia Goon", faction="Mafia",
        faction_color="#ff2244", alignment="mafia", verified="0", vote_weight="1.5",
        flipless="1", hide_vote_weight="1",
        card="[CENTER][TITLE]Role PM[/TITLE][/CENTER]\n\nYou are [B]Mafia Goon[/B].\n\nFactional kill.",
    ),
])


def _client_for(page: str) -> tuple[MUClient, MagicMock]:
    session = _logged_in_session()
    session.get = MagicMock(return_value=FakeResponse(text=page))
    session.post = MagicMock(return_value=FakeResponse(text="saved"))
    return MUClient("u", "p", session=session), session


def _posted_fields(session: MagicMock) -> dict[str, list[str]]:
    data = session.post.call_args.kwargs["data"]
    fields: dict[str, list[str]] = {}
    for key, value in data:
        fields.setdefault(key, []).append(value)
    return fields


def test_fetch_deaths_page_state_parses_every_field():
    client, _ = _client_for(SAMPLE)
    token, rows = client.fetch_deaths_page_state(10222)

    assert token == "tok123"
    assert [r["username"] for r in rows] == ["gamer", "Sprigatito", "TheJoker"]
    assert rows[0]["is_alive"] == "0"
    assert rows[0]["bpv_status"] == "1"
    assert rows[1]["ita_shield_status"] == "1"

    joker = rows[2]
    assert joker["slot"] == "6"
    assert joker["role_name"] == "Mafia Goon"
    assert joker["faction"] == "Mafia"
    assert joker["faction_color"] == "#ff2244"
    assert joker["alignment"] == "mafia"
    assert joker["rolepm_verified"] == "0"
    assert joker["vote_weight"] == "1.5"
    assert joker["flipless"] == "1"
    assert joker["hide_vote_weight"] == "1"
    assert "Factional kill." in joker["rolepm_card"]


def test_push_with_no_overrides_is_a_byte_identical_round_trip():
    """The echo path must not mutate a single field it does not own."""
    client, session = _client_for(SAMPLE)
    _token, before = client.fetch_deaths_page_state(10222)

    client.push_player_settings(10222, {})

    posted = _posted_fields(session)
    assert posted["name[]"] == [r["username"] for r in before]
    assert posted["slot[]"] == [r["slot"] for r in before]
    for field, key in [
        ("vote_weight[]", "vote_weight"),
        ("hide_vote_weight[]", "hide_vote_weight"),
        ("ita_shield_status[]", "ita_shield_status"),
        ("bpv_status[]", "bpv_status"),
        ("is_alive[]", "is_alive"),
        ("flipless[]", "flipless"),
        ("alignment[]", "alignment"),
        ("faction[]", "faction"),
        ("faction_color[]", "faction_color"),
        ("role_name[]", "role_name"),
        ("rolepm_card[]", "rolepm_card"),
        ("rolepm_verified[]", "rolepm_verified"),
    ]:
        assert posted[field] == [r[key] for r in before], f"{field} was mutated on round-trip"


def test_push_does_not_coerce_fractional_vote_weight():
    """vote_weight is step=any; an int() in the echo path would silently drop .5."""
    client, session = _client_for(SAMPLE)
    client.push_player_settings(10222, {})
    assert "1.5" in _posted_fields(session)["vote_weight[]"]


def test_push_preserves_multiline_role_pm_bodies():
    client, session = _client_for(SAMPLE)
    client.push_player_settings(10222, {"thejoker": {
        "role_name": "Godfather", "faction": "Mafia", "faction_color": "#ff2244",
        "alignment": "mafia", "rolepm_verified": "1",
    }})
    cards = _posted_fields(session)["rolepm_card[]"]
    assert cards[2] == "[CENTER][TITLE]Role PM[/TITLE][/CENTER]\n\nYou are [B]Mafia Goon[/B].\n\nFactional kill."


def test_push_can_never_change_life_state():
    """!push_players must be structurally incapable of killing or reviving."""
    client, session = _client_for(SAMPLE)
    client.push_player_settings(10222, {
        "gamer": {"role_name": "X", "faction": "", "faction_color": "#339933", "alignment": "town", "rolepm_verified": "1", "is_alive": "1"},
        "sprigatito": {"role_name": "Y", "faction": "", "faction_color": "#339933", "alignment": "town", "rolepm_verified": "0", "is_alive": "0"},
    })
    # Page said gamer dead, Sprigatito alive; sheet asked for the reverse.
    assert _posted_fields(session)["is_alive[]"] == ["0", "1", "1"]


def test_push_applies_only_sheet_owned_fields():
    client, session = _client_for(SAMPLE)
    matched = client.push_player_settings(10222, {"gamer": {
        "role_name": "Vanilla Villager", "faction": "Coven", "faction_color": "#123456",
        "alignment": "mafia", "rolepm_verified": "0",
    }})

    assert matched == 1
    posted = _posted_fields(session)
    assert posted["role_name[]"][0] == "Vanilla Villager"
    assert posted["faction[]"][0] == "Coven"
    assert posted["faction_color[]"][0] == "#123456"
    assert posted["alignment[]"][0] == "mafia"
    assert posted["rolepm_verified[]"][0] == "0"
    # Unmatched players keep their live values.
    assert posted["role_name[]"][1] == "Vanilla Town"
    assert posted["alignment[]"][2] == "mafia"


def test_blank_mu_role_name_inherits_live_value():
    """A hidden, unmaintained column must not blank MU's role name."""
    client, session = _client_for(SAMPLE)
    client.push_player_settings(10222, {"thejoker": {
        "role_name": "", "faction": "Mafia", "faction_color": "#ff2244",
        "alignment": "mafia", "rolepm_verified": "0",
    }})
    assert _posted_fields(session)["role_name[]"][2] == "Mafia Goon"


def test_blank_faction_clears_rather_than_inherits():
    """Town players legitimately have no faction, so empty must be sendable."""
    client, session = _client_for(SAMPLE)
    client.push_player_settings(10222, {"thejoker": {
        "role_name": "Mafia Goon", "faction": "", "faction_color": "#ff2244",
        "alignment": "mafia", "rolepm_verified": "0",
    }})
    assert _posted_fields(session)["faction[]"][2] == ""


def test_push_posts_to_deaths_endpoint_with_token():
    client, session = _client_for(SAMPLE)
    client.push_player_settings(10222, {})
    assert session.post.call_args.args[0].endswith("/modbot/manage-game/deaths/")
    assert session.post.call_args.kwargs["params"] == {"game_id": 10222}
    assert ("securitytoken", "tok123") in session.post.call_args.kwargs["data"]


def test_missing_token_raises():
    client, _ = _client_for("<html><body>no token here</body></html>")
    with pytest.raises(RuntimeError):
        client.fetch_deaths_page_state(10222)


def test_push_with_no_rows_raises():
    client, _ = _client_for(_deaths_page([]))
    with pytest.raises(RuntimeError):
        client.push_player_settings(10222, {})


@pytest.mark.parametrize("value,expected", [
    ("town", "town"),
    ("Town", "town"),
    ("  MAFIA  ", "mafia"),
    ("Evil Independent", "evil independent"),
    ("neutral independent", "neutral independent"),
])
def test_normalize_alignment_accepts_mu_values(value, expected):
    assert normalize_alignment(value) == expected


@pytest.mark.parametrize("value", ["", "indep", "independent", "villager", None])
def test_normalize_alignment_rejects_unknown(value):
    assert normalize_alignment(value) is None


@pytest.mark.parametrize("value,expected", [
    ("#339933", "#339933"),
    ("339933", "#339933"),
    ("#FFF", "#ffffff"),
    ("  #Ff2244 ", "#ff2244"),
])
def test_normalize_hex_color(value, expected):
    assert normalize_hex_color(value) == expected


@pytest.mark.parametrize("value", ["", "green", "#12345", None])
def test_normalize_hex_color_rejects_bad(value):
    assert normalize_hex_color(value) is None

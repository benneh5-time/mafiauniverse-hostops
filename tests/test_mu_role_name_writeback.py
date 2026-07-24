from __future__ import annotations

import pytest

from host_ops.sheets import SheetReader, SheetValidationError, _column_letter


class FakeWorksheet:
    def __init__(self, values):
        self.values = [list(row) for row in values]
        self.updates: list[tuple[list[list[str]], str]] = []
        self.cell_updates: list[tuple[int, int, str]] = []

    def get_all_values(self):
        return [list(row) for row in self.values]

    def update(self, data, rng):
        self.updates.append((data, rng))

    def update_cell(self, row, col, value):
        self.cell_updates.append((row, col, value))


class FakeSpreadsheet:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, name):
        if name != "Mashy Players":
            raise KeyError(name)
        return self.ws


class FakeClient:
    def __init__(self, ws):
        self.ws = ws

    def open_by_key(self, key):
        return FakeSpreadsheet(self.ws)


def _reader(values):
    ws = FakeWorksheet(values)
    return SheetReader(client=FakeClient(ws)), ws


@pytest.mark.parametrize("index,expected", [
    (1, "A"), (2, "B"), (26, "Z"), (27, "AA"), (28, "AB"), (52, "AZ"), (53, "BA"),
])
def test_column_letter(index, expected):
    assert _column_letter(index) == expected


def test_writes_existing_column_in_place():
    reader, ws = _reader([
        ["player", "mu_username", "mu_role_name", "role_pm"],
        ["gamer", "gamer", "stale", "pm1"],
        ["Sprigatito", "Sprigatito", "", "pm2"],
    ])
    written = reader.write_mu_role_names("sheet", {"gamer": "Vanilla Town", "sprigatito": "Cop"})

    assert written == 2
    data, rng = ws.updates[0]
    assert rng == "C2:C3"
    assert data == [["Vanilla Town"], ["Cop"]]
    assert ws.cell_updates == []  # column already existed


def test_appends_column_when_absent():
    reader, ws = _reader([
        ["player", "mu_username"],
        ["gamer", "gamer"],
    ])
    reader.write_mu_role_names("sheet", {"gamer": "Vanilla Town"})

    assert ws.cell_updates == [(1, 3, "mu_role_name")]
    data, rng = ws.updates[0]
    assert rng == "C2:C2"
    assert data == [["Vanilla Town"]]


def test_players_absent_from_mu_keep_their_existing_value():
    reader, ws = _reader([
        ["player", "mu_role_name"],
        ["gamer", "keep me"],
        ["Sprigatito", "also keep"],
    ])
    written = reader.write_mu_role_names("sheet", {"gamer": "Vanilla Town"})

    assert written == 1
    data, _rng = ws.updates[0]
    assert data == [["Vanilla Town"], ["also keep"]]


def test_blank_player_rows_are_preserved():
    reader, ws = _reader([
        ["player", "mu_role_name"],
        ["gamer", "Vanilla Town"],
        ["", "orphan value"],
    ])
    reader.write_mu_role_names("sheet", {"gamer": "Cop"})
    data, _rng = ws.updates[0]
    assert data == [["Cop"], ["orphan value"]]


def test_handles_short_rows_without_indexerror():
    """Sheets omits trailing empty cells, so rows can be shorter than headers."""
    reader, ws = _reader([
        ["player", "mu_username", "mu_role_name"],
        ["gamer"],
        ["Sprigatito", "Sprigatito"],
    ])
    reader.write_mu_role_names("sheet", {"gamer": "Cop"})
    data, _rng = ws.updates[0]
    assert data == [["Cop"], [""]]


def test_header_matching_is_normalized():
    reader, ws = _reader([
        ["Player", "MU Role Name"],
        ["gamer", "old"],
    ])
    reader.write_mu_role_names("sheet", {"gamer": "Cop"})
    assert ws.cell_updates == []  # matched "MU Role Name" -> mu_role_name
    data, rng = ws.updates[0]
    assert rng == "B2:B2"
    assert data == [["Cop"]]


def test_missing_player_column_raises():
    reader, _ws = _reader([["mu_username"], ["gamer"]])
    with pytest.raises(SheetValidationError):
        reader.write_mu_role_names("sheet", {"gamer": "Cop"})


def test_empty_tab_raises():
    reader, _ws = _reader([])
    with pytest.raises(SheetValidationError):
        reader.write_mu_role_names("sheet", {})

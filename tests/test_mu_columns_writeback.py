from __future__ import annotations

import pytest

from host_ops.sheets import SheetReader, SheetValidationError, _column_letter

ROLE = ("mu_role_name",)


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


def _range(ws, rng):
    for data, written_range in ws.updates:
        if written_range == rng:
            return data
    raise AssertionError(f"no write to {rng}; got {[r for _d, r in ws.updates]}")


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
    written = reader.write_mu_columns("sheet", {
        "gamer": {"mu_role_name": "Vanilla Town"},
        "sprigatito": {"mu_role_name": "Cop"},
    }, ROLE)

    assert written == 2
    assert _range(ws, "C2:C3") == [["Vanilla Town"], ["Cop"]]
    assert ws.cell_updates == []  # column already existed


def test_appends_column_when_absent():
    reader, ws = _reader([
        ["player", "mu_username"],
        ["gamer", "gamer"],
    ])
    reader.write_mu_columns("sheet", {"gamer": {"mu_role_name": "Vanilla Town"}}, ROLE)

    assert ws.cell_updates == [(1, 3, "mu_role_name")]
    assert _range(ws, "C2:C2") == [["Vanilla Town"]]


def test_appends_several_columns_at_distinct_indexes():
    reader, ws = _reader([
        ["player"],
        ["gamer"],
    ])
    reader.write_mu_columns("sheet", {
        "gamer": {"mu_role_name": "Cop", "mu_is_alive": "TRUE"},
    }, ("mu_role_name", "mu_is_alive"))

    assert ws.cell_updates == [(1, 2, "mu_role_name"), (1, 3, "mu_is_alive")]
    assert _range(ws, "B2:B2") == [["Cop"]]
    assert _range(ws, "C2:C2") == [["TRUE"]]


def test_writes_a_mix_of_existing_and_new_columns():
    reader, ws = _reader([
        ["player", "faction", "role_pm"],
        ["gamer", "old", "pm"],
    ])
    reader.write_mu_columns("sheet", {
        "gamer": {"faction": "Coven", "mu_is_alive": "FALSE"},
    }, ("faction", "mu_is_alive"))

    assert _range(ws, "B2:B2") == [["Coven"]]   # existing column, in place
    assert _range(ws, "D2:D2") == [["FALSE"]]   # appended after role_pm
    assert ws.cell_updates == [(1, 4, "mu_is_alive")]


def test_players_absent_from_mu_keep_their_existing_value():
    reader, ws = _reader([
        ["player", "mu_role_name"],
        ["gamer", "keep me"],
        ["Sprigatito", "also keep"],
    ])
    written = reader.write_mu_columns("sheet", {"gamer": {"mu_role_name": "Vanilla Town"}}, ROLE)

    assert written == 1
    assert _range(ws, "B2:B3") == [["Vanilla Town"], ["also keep"]]


def test_blank_player_rows_are_preserved():
    reader, ws = _reader([
        ["player", "mu_role_name"],
        ["gamer", "Vanilla Town"],
        ["", "orphan value"],
    ])
    reader.write_mu_columns("sheet", {"gamer": {"mu_role_name": "Cop"}}, ROLE)
    assert _range(ws, "B2:B3") == [["Cop"], ["orphan value"]]


def test_handles_short_rows_without_indexerror():
    """Sheets omits trailing empty cells, so rows can be shorter than headers."""
    reader, ws = _reader([
        ["player", "mu_username", "mu_role_name"],
        ["gamer"],
        ["Sprigatito", "Sprigatito"],
    ])
    reader.write_mu_columns("sheet", {"gamer": {"mu_role_name": "Cop"}}, ROLE)
    assert _range(ws, "C2:C3") == [["Cop"], [""]]


def test_header_matching_is_normalized():
    reader, ws = _reader([
        ["Player", "MU Role Name"],
        ["gamer", "old"],
    ])
    reader.write_mu_columns("sheet", {"gamer": {"mu_role_name": "Cop"}}, ROLE)
    assert ws.cell_updates == []  # matched "MU Role Name" -> mu_role_name
    assert _range(ws, "B2:B2") == [["Cop"]]


def test_missing_field_leaves_that_column_alone():
    reader, ws = _reader([
        ["player", "mu_role_name", "mu_is_alive"],
        ["gamer", "keep", "TRUE"],
    ])
    reader.write_mu_columns("sheet", {"gamer": {"mu_is_alive": "FALSE"}}, ("mu_role_name", "mu_is_alive"))
    assert _range(ws, "B2:B2") == [["keep"]]
    assert _range(ws, "C2:C2") == [["FALSE"]]


def test_missing_player_column_raises():
    reader, _ws = _reader([["mu_username"], ["gamer"]])
    with pytest.raises(SheetValidationError):
        reader.write_mu_columns("sheet", {"gamer": {"mu_role_name": "Cop"}}, ROLE)


def test_empty_tab_raises():
    reader, _ws = _reader([])
    with pytest.raises(SheetValidationError):
        reader.write_mu_columns("sheet", {}, ROLE)

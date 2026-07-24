from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import GameState, ITASettings, Player, Protection, normalize_name

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
PLAYER_COLUMNS = {"player", "mu_username", "role_pm", "redacted_role_pm", "role_name"}
PROTECTION_COLUMNS = {"phase", "target", "protection_type", "source", "uses", "active", "blocks_events"}
ITA_COLUMNS = {"phase", "default_hit_pct", "player", "hit_pct_override", "immune", "bonus", "penalty", "shots_allowed", "vulnerability", "shield_status", "bpv_status"}


MU_ALIGNMENTS = ("town", "mafia", "evil independent", "neutral independent")
HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class SheetValidationError(ValueError):
    pass


def normalize_alignment(value: Any) -> str | None:
    """Map a sheet alignment cell to one of MU's ``<select>`` values.

    Returns ``None`` for an unrecognised value. MU silently coerces anything
    off-list (most likely to ``town``), which would be an invisible mis-flip,
    so callers must reject rather than guess.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return None
    return text if text in MU_ALIGNMENTS else None


def normalize_hex_color(value: Any) -> str | None:
    """Coerce a sheet colour cell to ``#rrggbb``; ``None`` if unparseable."""
    text = str(value or "").strip()
    if not text:
        return None
    match = HEX_COLOR_RE.match(text)
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return f"#{digits.lower()}"


def extract_sheet_id(value: str) -> str:
    raw = (value or "").strip()
    match = SHEET_ID_RE.search(raw)
    return match.group(1) if match else raw


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on", "alive"}


def _immunity(value: Any, default: int = 0) -> int:
    """Parse ITA immunity as a 0-100 percentage.

    MU's ``ita_immunity[]`` is numeric, but this column used to be a boolean, so
    legacy ``true``/``yes`` cells still map to full (100%) immunity.
    """
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    if text.casefold() in {"true", "yes", "y", "on"}:
        return 100
    if text.casefold() in {"false", "no", "n", "off"}:
        return 0
    return max(0, min(100, int(float(text))))


def _int(value: Any, default: int = -1) -> int:
    if value is None or str(value).strip() == "":
        return default
    return int(float(str(value).strip()))


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value).strip())


def _float(value: Any, default: float = 0.0) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _column_letter(index_1based: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    letters = ""
    n = index_1based
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _norm_row(row: dict[str, Any]) -> dict[str, Any]:
    return {normalize_name(k).replace(" ", "_"): v for k, v in row.items()}


def validate_rows(tab_name: str, rows: list[dict[str, Any]], required: set[str]) -> None:
    if not rows:
        raise SheetValidationError(f"{tab_name} tab is empty")
    columns = set(_norm_row(rows[0]).keys())
    missing = sorted(required - columns)
    if missing:
        raise SheetValidationError(f"{tab_name} missing required columns: {', '.join(missing)}")


class SheetReader:
    def __init__(self, credentials_path: str | Path = "", client: Any = None):
        self.credentials_path = str(credentials_path or "")
        self.client = client

    def _client(self):
        if self.client is not None:
            return self.client
        import gspread
        self.client = gspread.service_account(filename=self.credentials_path)
        return self.client

    def write_ita_settings(self, sheet_url_or_id: str, rows: list[dict]) -> None:
        """Overwrite the Mashy ITA Settings tab with the given rows (list of dicts keyed by column name)."""
        spreadsheet = self._client().open_by_key(extract_sheet_id(sheet_url_or_id))
        try:
            ws = spreadsheet.worksheet("Mashy ITA Settings")
        except Exception:
            ws = spreadsheet.add_worksheet("Mashy ITA Settings", rows=max(len(rows) + 5, 20), cols=15)
        headers = ["phase", "player", "default_hit_pct", "hit_pct_override", "immune", "bonus", "penalty", "shots_allowed", "vulnerability", "shield_status", "bpv_status"]
        data = [headers] + [[str(row.get(h, "")) for h in headers] for row in rows]
        ws.clear()
        ws.update(data, "A1")

    def write_mu_role_names(self, sheet_url_or_id: str, names_by_player: dict[str, str]) -> int:
        """Update only the ``mu_role_name`` column on Mashy Players, in place.

        Every other column on the tab is host-authored, so this writes a single
        column range rather than rewriting the sheet. Adds the column if absent.
        Returns the number of cells written.
        """
        spreadsheet = self._client().open_by_key(extract_sheet_id(sheet_url_or_id))
        ws = spreadsheet.worksheet("Mashy Players")
        all_values = ws.get_all_values()
        if not all_values:
            raise SheetValidationError("Mashy Players tab is empty")
        headers = all_values[0]
        normalized = [normalize_name(h).replace(" ", "_") for h in headers]
        if "player" not in normalized:
            raise SheetValidationError("Mashy Players missing required columns: player")
        player_idx = normalized.index("player")
        if "mu_role_name" in normalized:
            col_idx = normalized.index("mu_role_name")
        else:
            col_idx = len(headers)
            ws.update_cell(1, col_idx + 1, "mu_role_name")

        column = [[""] for _ in range(len(all_values) - 1)]
        written = 0
        for offset, row in enumerate(all_values[1:]):
            name = row[player_idx].strip() if player_idx < len(row) else ""
            if not name:
                # Preserve whatever sits beside a blank player row.
                column[offset] = [row[col_idx] if col_idx < len(row) else ""]
                continue
            value = names_by_player.get(normalize_name(name))
            if value is None:
                column[offset] = [row[col_idx] if col_idx < len(row) else ""]
                continue
            column[offset] = [value]
            written += 1
        if column:
            letter = _column_letter(col_idx + 1)
            ws.update(column, f"{letter}2:{letter}{len(column) + 1}")
        return written

    def load_game_state(self, sheet_url_or_id: str) -> GameState:
        spreadsheet = self._client().open_by_key(extract_sheet_id(sheet_url_or_id))
        rows_by_tab = {name: spreadsheet.worksheet(name).get_all_records() for name in ("Mashy Players", "Mashy Protections", "Mashy ITA Settings")}
        return parse_game_state(rows_by_tab)


def parse_game_state(rows_by_tab: dict[str, list[dict[str, Any]]]) -> GameState:
    missing_tabs = [name for name in ("Mashy Players", "Mashy Protections", "Mashy ITA Settings") if name not in rows_by_tab]
    if missing_tabs:
        raise SheetValidationError(f"Missing required tab(s): {', '.join(missing_tabs)}")
    player_rows = rows_by_tab["Mashy Players"]
    protection_rows = rows_by_tab["Mashy Protections"]
    ita_rows = rows_by_tab["Mashy ITA Settings"]
    validate_rows("Mashy Players", player_rows, PLAYER_COLUMNS)
    if protection_rows:
        validate_rows("Mashy Protections", protection_rows, PROTECTION_COLUMNS)
    if ita_rows:
        validate_rows("Mashy ITA Settings", ita_rows, ITA_COLUMNS)

    players: list[Player] = []
    seen: set[str] = set()
    for raw in player_rows:
        row = _norm_row(raw)
        name = str(row.get("player", "")).strip()
        if not name:
            continue
        key = normalize_name(name)
        if key in seen:
            raise SheetValidationError(f"Duplicate player name: {name}")
        seen.add(key)
        redacted = str(row.get("redacted_role_pm", "")).strip()
        if not redacted:
            raise SheetValidationError(f"Missing redacted_role_pm for {name}")
        players.append(Player(name, str(row.get("mu_username", "")).strip() or name, str(row.get("role_pm", "")).strip(), redacted, _truthy(row.get("alive"), True), str(row.get("alignment", "")).strip(), str(row.get("role_name", "")).strip(), str(row.get("notes", "")).strip(), str(row.get("flavor", "")).strip(), str(row.get("mu_role_name", "")).strip(), str(row.get("faction", "")).strip(), str(row.get("faction_color", "")).strip(), _truthy(row.get("rolepm_verified"), False)))

    protections = [Protection(str(row.get("phase", "any")).strip() or "any", str(row.get("target", "")).strip(), str(row.get("protection_type", "")).strip(), str(row.get("source", "")).strip(), _int(row.get("uses"), -1), _truthy(row.get("active"), True), str(row.get("blocks_events", "any")).strip() or "any", str(row.get("notes", "")).strip()) for row in (_norm_row(r) for r in protection_rows) if str(row.get("target", "")).strip()]
    ita_settings = [ITASettings(str(row.get("phase", "any")).strip() or "any", _float(row.get("default_hit_pct"), 0.0), str(row.get("player", "")).strip(), _float_or_none(row.get("hit_pct_override")), _immunity(row.get("immune"), 0), _float(row.get("bonus"), 0.0), _float(row.get("penalty"), 0.0), _int(row.get("shots_allowed"), -1), _int(row.get("vulnerability"), 0), _int(row.get("shield_status"), 0), _int(row.get("bpv_status"), 0)) for row in (_norm_row(r) for r in ita_rows)]
    return GameState(players, protections, ita_settings)

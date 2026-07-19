from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import GameState, ITASettings, Player, Protection, normalize_name

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
PLAYER_COLUMNS = {"player", "mu_username", "role_pm", "redacted_role_pm", "role_name"}
PROTECTION_COLUMNS = {"phase", "target", "protection_type", "source", "uses", "active", "blocks_events"}
ITA_COLUMNS = {"phase", "default_hit_pct", "player", "hit_pct_override", "immune", "bonus", "penalty", "shots_allowed", "vulnerability", "shield_status", "bpv_status"}


class SheetValidationError(ValueError):
    pass


def extract_sheet_id(value: str) -> str:
    raw = (value or "").strip()
    match = SHEET_ID_RE.search(raw)
    return match.group(1) if match else raw


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on", "alive"}


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
        players.append(Player(name, str(row.get("mu_username", "")).strip() or name, str(row.get("role_pm", "")).strip(), redacted, _truthy(row.get("alive"), True), str(row.get("alignment", "")).strip(), str(row.get("role_name", "")).strip(), str(row.get("notes", "")).strip()))

    protections = [Protection(str(row.get("phase", "any")).strip() or "any", str(row.get("target", "")).strip(), str(row.get("protection_type", "")).strip(), str(row.get("source", "")).strip(), _int(row.get("uses"), -1), _truthy(row.get("active"), True), str(row.get("blocks_events", "any")).strip() or "any", str(row.get("notes", "")).strip()) for row in (_norm_row(r) for r in protection_rows) if str(row.get("target", "")).strip()]
    ita_settings = [ITASettings(str(row.get("phase", "any")).strip() or "any", _float(row.get("default_hit_pct"), 0.0), str(row.get("player", "")).strip(), _float_or_none(row.get("hit_pct_override")), _truthy(row.get("immune"), False), _float(row.get("bonus"), 0.0), _float(row.get("penalty"), 0.0), _int(row.get("shots_allowed"), -1), _int(row.get("vulnerability"), 0), _int(row.get("shield_status"), 0), _int(row.get("bpv_status"), 0)) for row in (_norm_row(r) for r in ita_rows)]
    return GameState(players, protections, ita_settings)

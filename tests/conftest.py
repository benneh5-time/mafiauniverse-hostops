from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from host_ops.db import HostOpsDB
from host_ops.models import GameState, ITASettings, Player


@pytest.fixture
def db():
    db_path = Path.cwd() / f".test_host_ops_{uuid4().hex}.db"
    try:
        yield HostOpsDB(db_path)
    finally:
        for path in db_path.parent.glob(f"{db_path.name}*"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


@pytest.fixture
def basic_state():
    return GameState(
        players=[Player("Alice", "alice_mu", "PM", "Redacted Alice", True, "town"), Player("Bob", "bob_mu", "PM", "Redacted Bob", True, "mafia")],
        protections=[],
        ita_settings=[ITASettings(phase="any", default_hit_pct=50.0, player="", hit_pct_override=None, immune=0)],
    )

from __future__ import annotations

import pytest

from host_ops.db import HostOpsDB
from host_ops.models import GameState, ITASettings, Player


@pytest.fixture
def db(tmp_path):
    return HostOpsDB(tmp_path / "host_ops.db")


@pytest.fixture
def basic_state():
    return GameState(
        players=[Player("Alice", "alice_mu", "PM", "Redacted Alice", True, "town"), Player("Bob", "bob_mu", "PM", "Redacted Bob", True, "mafia")],
        protections=[],
        ita_settings=[ITASettings(phase="any", default_hit_pct=50.0, player="", hit_pct_override=None, immune=False)],
    )

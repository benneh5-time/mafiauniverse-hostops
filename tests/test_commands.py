from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from host_ops.commands.actions import resolve_action
from host_ops.models import GameConfig


class FakeSheetReader:
    def __init__(self, state):
        self.state = state
    def load_game_state(self, sheet_id):
        return self.state


def test_dry_run_does_not_call_mu_and_logs(db, basic_state):
    db.upsert_game(GameConfig("g", 123, "sheet", 10, log_channel_id=99, active=True))
    bot = MagicMock()
    log_channel = AsyncMock()
    bot.get_channel.return_value = log_channel
    mu = MagicMock()
    result, _message = asyncio.run(resolve_action(bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu,
                                            live_mode=False, host_channel_id=10, target_name="Alice", event_type="kill"))
    assert result.success
    mu.kill.assert_not_called()
    log_channel.send.assert_called_once()
    assert db.get_events(10, "g", "Alice")[0]["outcome"] == "killed"


def test_live_kill_calls_mu_and_logs(db, basic_state):
    db.upsert_game(GameConfig("g", 123, "sheet", 10, log_channel_id=99, active=True))
    bot = MagicMock()
    bot.get_channel.return_value = AsyncMock()
    mu = MagicMock()
    mu.kill.return_value = {"response": "Kill was successful"}
    reply = MagicMock(post_id="555")
    mu.post_reply_with_threadmark.return_value = (reply, MagicMock())
    result, _message = asyncio.run(resolve_action(bot=bot, db=db, sheet_reader=FakeSheetReader(basic_state), mu_client=mu,
                                            live_mode=True, host_channel_id=10, target_name="Alice", event_type="kill"))
    assert result.success
    mu.kill.assert_called_once()
    mu.post_reply_with_threadmark.assert_called_once()
    assert db.is_dead(10, "g", "Alice")

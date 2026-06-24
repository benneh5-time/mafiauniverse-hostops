from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import csv
from pathlib import Path

from .commands import actions, host, info, rolepm
from .config import load_settings
from .db import HostOpsDB
from .mu_client import MUClient
from .poller import ManualITAPoller
from .sheets import SheetReader


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("host_ops").setLevel(logging.DEBUG)


def create_bot():
    settings = load_settings()
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix=settings.command_prefix, intents=intents)

    db = HostOpsDB(settings.db_path)
    sheet_reader = SheetReader(settings.google_credentials_path)
    mu_client = MUClient(settings.mu_username, settings.mu_password)

    _csv_path = Path(__file__).parent / "database" / "mu_user_ids.csv"
    # Maps lowercased username -> (original_username, pfp_id)
    _mu_user_ids: dict[str, tuple[str, int]] = {}
    with _csv_path.open(newline="", encoding="utf-8") as _f:
        for row in csv.DictReader(_f):
            pfp_id = row.get("pfp_id", "").strip()
            if pfp_id:
                _mu_user_ids[row["username"].casefold()] = (row["username"], int(pfp_id))

    host.register(bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client)
    actions.register(bot, db=db, sheet_reader=sheet_reader, mu_client=mu_client, live_mode=settings.live_mode)
    info.register(bot, db=db, sheet_reader=sheet_reader)
    rolepm.register(bot, mu_user_ids=_mu_user_ids)

    async def resolve_manual_ita(*, cfg, player_name: str, post_id: str) -> None:
        await actions.resolve_action(
            bot=bot,
            db=db,
            sheet_reader=sheet_reader,
            mu_client=mu_client,
            live_mode=settings.live_mode,
            host_channel_id=cfg.host_channel_id,
            target_name=player_name,
            event_type="ita",
            shooter=f"MU post {post_id}",
            reason=f"Manual ITA post {post_id}",
        )

    @bot.check
    def _guild_channel_check(ctx):
        from .commands.rolepm import ROLEPM_CHANNEL_ID
        if ctx.channel.id == ROLEPM_CHANNEL_ID:
            return True
        if settings.allowed_guild_ids and ctx.guild and ctx.guild.id not in settings.allowed_guild_ids:
            return False
        if settings.allowed_channel_ids and ctx.channel.id not in settings.allowed_channel_ids:
            return False
        return True

    poller = ManualITAPoller(
        db=db,
        mu_client=mu_client,
        resolve_callback=resolve_manual_ita,
        interval_seconds=settings.poll_interval_seconds,
    )
    bot._host_ops_poller = poller

    @bot.event
    async def on_ready():
        mode = "LIVE" if settings.live_mode else "DRY RUN"
        print(f"host ops bot connected as {bot.user} ({mode})", flush=True)
        if settings.mu_username and settings.mu_password:
            try:
                await asyncio.to_thread(mu_client.login)
                print("MU login completed", flush=True)
            except Exception as exc:
                print(f"MU login failed: {exc}", flush=True)
        poller.start()

    return bot


def main() -> None:
    setup_logging()
    settings = load_settings()
    bot = create_bot()
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


@dataclass(slots=True)
class Settings:
    discord_token: str
    mu_username: str
    mu_password: str
    google_credentials_path: str
    db_path: Path = Path("data/host_ops.db")
    live_mode: bool = False
    command_prefix: str = "!"
    poll_interval_seconds: int = 60
    allowed_guild_ids: frozenset[int] = frozenset()
    allowed_channel_ids: frozenset[int] = frozenset()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _id_set_env(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip().isdigit())


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    if load_dotenv:
        load_dotenv(env_file)
    return Settings(
        discord_token=os.environ.get("DISCORD_TOKEN", ""),
        mu_username=os.environ.get("MU_USERNAME", ""),
        mu_password=os.environ.get("MU_PASSWORD", ""),
        google_credentials_path=os.environ.get("GOOGLE_CREDENTIALS_PATH", ""),
        db_path=Path(os.environ.get("HOST_OPS_DB_PATH", "data/host_ops.db")),
        live_mode=_bool_env("HOST_OPS_LIVE_MODE", False),
        command_prefix=os.environ.get("HOST_OPS_COMMAND_PREFIX", "!"),
        poll_interval_seconds=int(os.environ.get("HOST_OPS_POLL_INTERVAL_SECONDS", "60")),
        allowed_guild_ids=_id_set_env("ALLOWED_GUILD_IDS"),
        allowed_channel_ids=_id_set_env("ALLOWED_CHANNEL_IDS"),
    )

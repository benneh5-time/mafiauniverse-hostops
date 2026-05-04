# MU Host Ops Bot

Standalone Discord bot for MafiaUniverse host operations.

Uses the shared `mafiauniverse-client` package for common MafiaUniverse forum operations, Google Sheets for game inputs, and SQLite for game configuration, deaths, event audit logs, and manual ITA dedupe. Google Sheets are input-only by default; `!pull_ita` and `!push_ita` can round-trip ITA settings between the sheet and MU.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Fill in `.env`, then run:

```powershell
python -m host_ops
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | Yes | — | Discord bot token |
| `MU_USERNAME` | Yes | — | MafiaUniverse forum username |
| `MU_PASSWORD` | Yes | — | MafiaUniverse forum password |
| `GOOGLE_CREDENTIALS_PATH` | Yes | — | Path to Google service account JSON |
| `HOST_OPS_DB_PATH` | No | `data/host_ops.db` | SQLite database path |
| `HOST_OPS_LIVE_MODE` | No | `false` | Set to `true` to enable real MU kills/posts |
| `HOST_OPS_COMMAND_PREFIX` | No | `!` | Discord command prefix |
| `HOST_OPS_POLL_INTERVAL_SECONDS` | No | `60` | How often the manual ITA poller checks the game thread |
| `ALLOWED_GUILD_IDS` | No | _(all)_ | Comma-separated guild IDs to restrict bot usage |
| `ALLOWED_CHANNEL_IDS` | No | _(all)_ | Comma-separated channel IDs to restrict bot usage |

`HOST_OPS_LIVE_MODE=false` is the default and prevents real MU kills/posts.

## Required Sheet Tabs

Each configured game spreadsheet must have these tabs: `Players`, `Protections`, and `ITA Settings`.

### Players tab

| Column | Required | Description |
|---|---|---|
| `player` | Yes | Display name used in announcements |
| `mu_username` | Yes | MafiaUniverse forum username |
| `role_pm` | Yes | Full role PM text |
| `redacted_role_pm` | Yes | Role PM shown in the death announcement spoiler |
| `role_name` | No | Role name appended to threadmarks |
| `alignment` | No | Faction/alignment (informational) |
| `alive` | No | `true`/`false` — treated as alive if omitted |
| `notes` | No | Free-form notes |

### Protections tab

| Column | Required | Description |
|---|---|---|
| `phase` | Yes | Phase this protection is active in (`any`, `day`, `night`, etc.) |
| `target` | Yes | Player name or MU username this protection covers |
| `protection_type` | No | Label for the protection (e.g. `doctor`) |
| `source` | No | Source of the protection (shown in block messages) |
| `uses` | No | Number of uses remaining; `-1` = unlimited |
| `active` | No | `true`/`false` |
| `blocks_events` | No | Comma-separated event types blocked (`any`, `kill`, `ita`, `dayvig`); defaults to `any` |
| `notes` | No | Free-form notes |

### ITA Settings tab

| Column | Required | Description |
|---|---|---|
| `phase` | Yes | Phase this row applies to (`any`, `day`, etc.) |
| `player` | Yes | Player name; leave blank for a global default row |
| `default_hit_pct` | Yes | Base ITA hit percentage (0–100) |
| `hit_pct_override` | No | Overrides `default_hit_pct` when set |
| `immune` | No | `true` = always miss |
| `bonus` | No | Added to effective hit % |
| `penalty` | No | Subtracted from effective hit % |
| `shots_allowed` | No | Max shots this player may fire; `-1` = unlimited |
| `vulnerability` | No | MU vulnerability field (integer) |
| `shield_status` | No | MU shield status field (integer) |
| `bpv_status` | No | MU BPV status field (integer) |

## Commands

### Game setup

| Command | Description |
|---|---|
| `!setup_game <name> <thread_id> <sheet_url_or_id>` | Configure a game, load the sheet, and set it active in this channel. Detects the MU game ID automatically. |
| `!use_game <name>` | Switch the active game for this channel. |
| `!set_log_channel [#channel\|channel_id]` | Set the channel where kill/event log messages are posted. Defaults to the current channel. |
| `!game_status` | Show the active game name, thread ID, player count, and log channel. |
| `!reload_sheet` | Re-read the Google Sheet and report player/protection/ITA row counts. |

### Kill actions

| Command | Description |
|---|---|
| `!kill <player> [reason...]` | Kill a player. Checks protections. In live mode: calls MU modbot, posts a death announcement, and sets a threadmark. |
| `!dayvig <player> [reason...]` | Day vigilante kill. Same flow as `!kill` but labelled as `dayvig` for protection matching. |
| `!resolve_ita <player> [shooter] [reason...]` | Manually resolve an ITA shot. Rolls against the player's hit % from the ITA Settings tab. |
| `!revive <player>` | Undo a recorded death. In live mode: calls MU modbot revive. |

### ITA sync

| Command | Description |
|---|---|
| `!pull_ita` | Fetch current ITA settings from MU and overwrite the `ITA Settings` tab in the Google Sheet. Matches players by MU username. |
| `!push_ita` | Read the `ITA Settings` tab and push the values to MU. Unmatched players keep their current MU values. |

### Information

| Command | Description |
|---|---|
| `!alive` | List currently alive players. |
| `!dead` | List currently dead players. |
| `!audit <player>` | Show the last 10 logged events for a player. |

## Manual ITA Poller

The bot polls the game thread every `HOST_OPS_POLL_INTERVAL_SECONDS` seconds looking for posts that contain bold red text matching:

```
Manual ITA: <player name>
```

When a new matching post is found it is resolved as an ITA shot (same logic as `!resolve_ita`) and the post ID is recorded so it is not processed again. The resolved outcome is logged to the configured log channel.

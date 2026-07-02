from __future__ import annotations

import asyncio

ROLEPM_CHANNEL_ID = 1519140610995392703

# Hardcoded MU draft thread that !vt posts roles into (will not change).
ROLE_DRAFT_THREAD_ID = 60309

_TOWN_TEMPLATE = """\
[QUOTE][TITLE][CENTER]MU Anniversary 2026 Role PM[/CENTER][/TITLE]

You are [B][COLOR="#008000"]{player}[/COLOR][/B], a [B][COLOR="#008000"]Town $Role[/COLOR][/B].

[CENTER][CHARIMG]{img_url}[/CHARIMG][/CENTER]

[I]$Flavor[/I]

[B][U]You have the following abilities:[/U][/B]
[LIST=1][*][B]Very Cool Ability!!![/B] — [I]tags[/I]
Ability that's very cool

[*][B]Very Mid Ability[/B] — [I]tags[/I]
Ability 2 that's mid[/LIST][/QUOTE]"""

_MAFIA_TEMPLATE = """\
[QUOTE][TITLE][CENTER]MU Anniversary 2026 Role PM[/CENTER][/TITLE]

You are [B][COLOR="#FF0000"]{player}[/COLOR][/B], a [B][COLOR="#FF0000"]Mafia $Role[/COLOR][/B].

[CENTER][CHARIMG]{img_url}[/CHARIMG][/CENTER]

[I]$Flavor[/I]

[B][U]You have the following abilities:[/U][/B]
[LIST=1][*][B]Very Cool Ability!!![/B] — [I]tags[/I]
Ability that's very cool

[*][B]Very Mid Ability[/B] — [I]tags[/I]
Ability 2 that's mid[/LIST][/QUOTE]"""

_PET_BLOCK = """

[BOX=Pet Name— Pet][CENTER][CHARIMG]picture here[/CHARIMG][/CENTER]

[B][U]While you have your pet, you also have the following abilities:[/U][/B]
[LIST=1][*][B]ability name[/B]
Ability here [/LIST]
[/BOX]"""

_TOWN_PET_TEMPLATE = _TOWN_TEMPLATE[: -len("[/QUOTE]")] + _PET_BLOCK + "[/QUOTE]"
_MAFIA_PET_TEMPLATE = _MAFIA_TEMPLATE[: -len("[/QUOTE]")] + _PET_BLOCK + "[/QUOTE]"

_VT_TEMPLATE = """\
[QUOTE][TITLE][CENTER]MU Anniversary 2026 Role PM[/CENTER][/TITLE]

You are [B][COLOR="#008000"]{player}[/COLOR][/B], a [B][COLOR="#008000"]Vanilla Town[/COLOR][/B].

[CENTER][CHARIMG]{img_url}[/CHARIMG][/CENTER]

[I]{flavor}[/I]

[B][U]You have no inherent abilities except your vote.[/U][/B][/QUOTE]"""


def register(bot, *, mu_user_ids: dict[str, tuple[str, int]], mu_client) -> None:
    def _lookup(name: str) -> tuple[str, str] | None:
        entry = mu_user_ids.get(name.strip().casefold())
        if entry is None:
            return None
        original_username, user_id = entry
        img_url = f"https://www.mafiauniverse.com/forums/image.php?u={user_id}"
        return original_username, img_url

    async def _rolepm(ctx, name: str, template: str) -> None:
        if ctx.channel.id != ROLEPM_CHANNEL_ID:
            return
        looked_up = _lookup(name)
        if looked_up is None:
            await ctx.reply(f"No MU user found for `{name}`.")
            return
        original_username, img_url = looked_up
        output = template.format(player=original_username, img_url=img_url)
        await ctx.reply(f"```\n{output}\n```")

    @bot.command(name="town")
    async def town(ctx, *, name: str):
        await _rolepm(ctx, name, _TOWN_TEMPLATE)

    @bot.command(name="villager")
    async def villager(ctx, *, name: str):
        await _rolepm(ctx, name, _TOWN_TEMPLATE)

    @bot.command(name="wolf")
    async def wolf(ctx, *, name: str):
        await _rolepm(ctx, name, _MAFIA_TEMPLATE)

    @bot.command(name="mafia")
    async def mafia(ctx, *, name: str):
        await _rolepm(ctx, name, _MAFIA_TEMPLATE)

    @bot.command(name="pettown")
    async def pettown(ctx, *, name: str):
        await _rolepm(ctx, name, _TOWN_PET_TEMPLATE)

    @bot.command(name="petmafia")
    async def petmafia(ctx, *, name: str):
        await _rolepm(ctx, name, _MAFIA_PET_TEMPLATE)

    @bot.command(name="petvillager")
    async def petvillager(ctx, *, name: str):
        await _rolepm(ctx, name, _TOWN_PET_TEMPLATE)

    @bot.command(name="petwolf")
    async def petwolf(ctx, *, name: str):
        await _rolepm(ctx, name, _MAFIA_PET_TEMPLATE)

    @bot.command(name="vt")
    async def vt(ctx, *, args: str):
        if ctx.channel.id != ROLEPM_CHANNEL_ID:
            return
        if "|" not in args:
            await ctx.reply("Usage: `!vt <name> | <flavor>`")
            return
        name, flavor = args.split("|", 1)
        name, flavor = name.strip(), flavor.strip()
        looked_up = _lookup(name)
        if looked_up is None:
            await ctx.reply(f"No MU user found for `{name}`.")
            return
        original_username, img_url = looked_up
        output = _VT_TEMPLATE.format(player=original_username, img_url=img_url, flavor=flavor)
        try:
            reply = await asyncio.to_thread(mu_client.post_reply, ROLE_DRAFT_THREAD_ID, output)
        except Exception as exc:
            await ctx.reply(f"Failed to post `{original_username}`'s role to MU: {exc}")
            return
        link = reply.final_url or (
            f"https://www.mafiauniverse.com/forums/threads/{ROLE_DRAFT_THREAD_ID}"
            + (f"?p={reply.post_id}#post{reply.post_id}" if reply.post_id else "")
        )
        await ctx.reply(f"Posted `{original_username}`'s VT role: {link}")

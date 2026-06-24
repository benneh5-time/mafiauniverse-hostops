from __future__ import annotations

ROLEPM_CHANNEL_ID = 1519140610995392703

_TOWN_TEMPLATE = """\
[QUOTE][TITLE][CENTER]MU Anniversary 2026 Role PM[/CENTER][/TITLE]

You are [B][COLOR="#008000"]{player}[/COLOR][/B], a [B][COLOR="#008000"]Town $Role[/COLOR][/B].

[CENTER][CHARIMG]{img_url}[/CHARIMG][/CENTER]

[I]$Flavor[/I]

[B][U]You have the following abilities starting Night 0:[/U][/B]
[LIST=1][*][B]Very Cool Ability!!![/B] — [I]tags[/I]
Ability that's very cool

[*][B]Very Mid Ability[/B] — [I]tags[/I]
Ability 2 that's mid[/LIST][/QUOTE]"""

_MAFIA_TEMPLATE = """\
[QUOTE][TITLE][CENTER]MU Anniversary 2026 Role PM[/CENTER][/TITLE]

You are [B][COLOR="#FF0000"]{player}[/COLOR][/B], a [B][COLOR="#FF0000"]Mafia $Role[/COLOR][/B].

[CENTER][CHARIMG]{img_url}[/CHARIMG][/CENTER]

[I]$Flavor[/I]

[B][U]You have the following abilities starting Night 0:[/U][/B]
[LIST=1][*][B]Very Cool Ability!!![/B] — [I]tags[/I]
Ability that's very cool

[*][B]Very Mid Ability[/B] — [I]tags[/I]
Ability 2 that's mid[/LIST][/QUOTE]"""


def register(bot, *, mu_user_ids: dict[str, tuple[str, int]]) -> None:
    async def _rolepm(ctx, name: str, template: str) -> None:
        if ctx.channel.id != ROLEPM_CHANNEL_ID:
            return
        entry = mu_user_ids.get(name.strip().casefold())
        if entry is None:
            await ctx.reply(f"No MU user found for `{name}`.")
            return
        original_username, user_id = entry
        img_url = f"https://www.mafiauniverse.com/forums/image.php?u={user_id}"
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

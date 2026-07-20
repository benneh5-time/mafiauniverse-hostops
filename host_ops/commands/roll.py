from __future__ import annotations

import random
import re

_DICE_RE = re.compile(r"^(?:(\d+)d)?(\d+)$", re.IGNORECASE)

MAX_COUNT = 50
MAX_SIDES = 1_000_000


def register(bot) -> None:
    @bot.command(name="roll")
    async def roll(ctx, spec: str = "100"):
        match = _DICE_RE.match(spec.strip())
        if match is None:
            await ctx.reply("Usage: `!roll 100` or `!roll 5d100`")
            return

        count = int(match.group(1)) if match.group(1) else 1
        sides = int(match.group(2))

        if count < 1 or count > MAX_COUNT:
            await ctx.reply(f"Number of rolls must be between 1 and {MAX_COUNT}.")
            return
        if sides < 1 or sides > MAX_SIDES:
            await ctx.reply(f"Maximum must be between 1 and {MAX_SIDES}.")
            return

        values = [random.randint(1, sides) for _ in range(count)]
        lines = [f"Roll #{i}: **{v}**" for i, v in enumerate(values, start=1)]
        await ctx.reply("\n".join(lines))

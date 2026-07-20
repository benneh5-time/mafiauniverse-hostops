from __future__ import annotations

import random


def register(bot) -> None:
    @bot.command(name="roll")
    async def roll(ctx, maximum: int = 100):
        if maximum < 1:
            await ctx.reply("Maximum must be at least 1.")
            return
        if maximum > 1_000_000:
            await ctx.reply("Maximum must be 1000000 or less.")
            return
        value = random.randint(1, maximum)
        await ctx.reply(f"🎲 {ctx.author.display_name} rolled **{value}** (1-{maximum})")

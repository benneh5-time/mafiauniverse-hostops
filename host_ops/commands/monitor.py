from __future__ import annotations

from ..pm_monitor import PMMonitor


def _channel_id_from_arg(ctx, channel_arg: str) -> int:
    return int(channel_arg.strip().strip("<#!>"))


def register(bot, *, pm_monitor: PMMonitor) -> None:
    @bot.command(name="monitor")
    async def monitor(ctx, arg: str | None = None):
        # No argument: report status.
        if arg is None:
            await ctx.reply(pm_monitor.status())
            return

        # Explicit off.
        if arg.strip().lower() == "off":
            if not pm_monitor.is_running:
                await ctx.reply("PM monitoring is already off.")
                return
            pm_monitor.stop()
            await ctx.reply("PM monitoring stopped.")
            return

        # Otherwise treat the argument as a channel mention / id.
        try:
            channel_id = _channel_id_from_arg(ctx, arg)
        except (ValueError, TypeError):
            await ctx.reply("Could not read a channel from that. Use `!monitor #channel`, `!monitor off`, or `!monitor`.")
            return

        if bot.get_channel(channel_id) is None:
            await ctx.reply(f"I can't see channel <#{channel_id}>. Check the ID and my access.")
            return

        await pm_monitor.start(channel_id)
        await ctx.reply(
            f"Now monitoring MU private messages → <#{channel_id}>. "
            f"New PMs from now on will be forwarded here. Use `!monitor off` to stop."
        )

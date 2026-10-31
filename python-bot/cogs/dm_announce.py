# Credits: gogeta_gg
import asyncio

import discord
from discord.ext import commands
from discord import app_commands

from ui import embeds
from ui.views import ConfirmView


class DMAnnounce(commands.Cog):
    """Send a confirmed announcement by DM to members of the current guild only."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="dmannounce",
        description="Send a confirmed announcement by DM to members of this server.",
    )
    @app_commands.describe(message="The announcement to send to this server's members.")
    @commands.guild_only()
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def dmannounce(self, ctx: commands.Context, *, message: str):
        """DM the supplied announcement to members of the server where it is invoked."""
        if not message.strip():
            await ctx.send(embed=embeds.error("Missing Message", "Please provide the announcement you want me to send."), ephemeral=True)
            return

        # A DM can only contain 2,000 characters.
        if len(message) > 2000:
            await ctx.send(
                embed=embeds.error(
                    "Message Too Long",
                    f"Discord DMs are limited to **2,000 characters**. Your message is **{len(message):,}** characters.",
                ),
                ephemeral=True,
            )
            return

        guild = ctx.guild
        members = list(guild.members)
        total = len(members)
        bots = sum(1 for m in members if m.bot)
        human_count = total - bots

        prompt = embeds.warning(
            "Confirm Server-Wide DM",
            (
                f"This will DM the announcement to **{human_count:,} human members** in **{guild.name}**.\n\n"
                f"**Bots:** {bots:,} (not targeted)\n"
                f"**Message:**\n> {message[:900]}{'…' if len(message) > 900 else ''}\n\n"
                "Only members of **this server** will be targeted. Members with closed DMs may not receive it."
            ),
        )
        view = ConfirmView(ctx.author.id, confirm_label="Send to Members", danger=True, timeout=30)
        prompt_message = await ctx.send(embed=prompt, view=view, ephemeral=True)
        view.message = prompt_message
        await view.wait()

        if not view.result:
            await ctx.send(embed=embeds.info("Cancelled", "No DMs were sent."), ephemeral=True)
            return

        # Acknowledge immediately so large servers do not hit the interaction timeout.
        await ctx.send(embed=embeds.info("Announcement Started", f"Starting the DM announcement for **{guild.name}**…"), ephemeral=True)

        sent = 0
        failed = 0
        attempted = 0
        failed_examples: list[str] = []

        # Keep concurrency deliberately low so a large guild does not turn the
        # announcement into a burst of DM requests. Discord's own HTTP limits
        # are still respected by discord.py's rate limiter.
        semaphore = asyncio.Semaphore(4)

        async def send_to_member(member: discord.Member):
            nonlocal sent, failed, attempted
            async with semaphore:
                attempted += 1
                try:
                    await member.send(message)
                    sent += 1
                except (discord.Forbidden, discord.NotFound):
                    failed += 1
                    if len(failed_examples) < 5:
                        failed_examples.append(f"{member} — DMs unavailable")
                except discord.HTTPException as exc:
                    failed += 1
                    if len(failed_examples) < 5:
                        failed_examples.append(f"{member} — Discord HTTP {exc.status}")
                except Exception as exc:
                    failed += 1
                    if len(failed_examples) < 5:
                        failed_examples.append(f"{member} — {type(exc).__name__}")

        # Do not block the event loop with thousands of coroutine objects at
        # once; process members in small batches.
        targets = [m for m in members if not m.bot]
        for start in range(0, len(targets), 100):
            batch = targets[start : start + 100]
            await asyncio.gather(*(send_to_member(member) for member in batch))

        details = [
            f"**Server:** {guild.name}",
            f"**Attempted:** {attempted:,}",
            f"**Delivered:** {sent:,}",
            f"**Failed:** {failed:,}",
        ]
        if failed_examples:
            details.append("\n**Some failures:**\n" + "\n".join(f"• {x}" for x in failed_examples))

        title = "Announcement Complete" if failed == 0 else "Announcement Finished With Some Failures"
        result_embed = embeds.success(title, "\n".join(details)) if failed == 0 else embeds.warning(title, "\n".join(details))
        await ctx.send(embed=result_embed, ephemeral=True)

    @dmannounce.error
    async def dmannounce_error(self, ctx: commands.Context, error: commands.CommandError):
        original = getattr(error, "original", error)
        if isinstance(original, commands.CommandOnCooldown):
            await ctx.send(
                embed=embeds.error(
                    "Please Wait",
                    f"This server can use `/dmannounce` again in **{original.retry_after:.0f}s**.",
                ),
                ephemeral=True,
            )
            return
        if isinstance(original, commands.NoPrivateMessage):
            await ctx.send(embed=embeds.error("Server Only", "This command can only be used inside a server."), ephemeral=True)
            return
        await ctx.send(embed=embeds.error("Announcement Failed", f"`{original}`"), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DMAnnounce(bot))

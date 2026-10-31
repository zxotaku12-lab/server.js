# Credits: gogeta_gg
import discord
from discord.ext import commands, tasks

from ui.emoji import E
from ui import embeds as ui_embeds

from . import giveaway_db
from . import giveaway_utils


class GiveawayTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        # This used to print "[Giveaway] Checking giveaways..." and
        # "[Giveaway] Expired found: 0" on every single pass, i.e. every 30
        # seconds forever, even when there was nothing to do. On a hosting
        # panel with a limited console/log buffer that noise pushes out
        # anything actually useful within a few minutes. Now we only print
        # when there's something worth knowing about.
        expired = giveaway_db.get_expired_giveaways()

        if not expired:
            return

        print(f"[Giveaway] {len(expired)} giveaway(s) expired, ending them now...")

        for giveaway in expired:
            await self._end_giveaway(giveaway)

    async def _end_giveaway(self, giveaway):
        message_id = giveaway["message_id"]

        # Mark it ended first, unconditionally. Previously this only
        # happened deep inside the try block after a successful
        # fetch_message() — so a giveaway whose message had been deleted
        # (or any other fetch failure) threw a 404, got caught, printed,
        # and then never got marked ended. That meant the SAME giveaway
        # came back out of get_expired_giveaways() on every single 30s
        # pass forever, which is exactly the endless "Failed to end
        # giveaway ... 404 Not Found" log spam. Ending it up front means
        # a failure below can no longer cause a retry loop.
        giveaway_db.mark_giveaway_ended(message_id)

        guild = self.bot.get_guild(giveaway["guild_id"])
        channel = self.bot.get_channel(giveaway["channel_id"])

        if guild is None or channel is None:
            print(f"[Giveaway] Guild/channel not found for giveaway {message_id}.")
            return

        # This is the actual missing piece: nothing here ever picked a
        # winner. The old code fetched the message purely to see if it
        # still existed, discarded the result, and stopped — no winner
        # was ever chosen or announced when a giveaway ended on its own.
        # Winner selection now goes through giveaway_utils, the same code
        # /greroll already used, so both paths behave identically.
        winners = giveaway_utils.pick_weighted_winners(guild, giveaway)

        if winners:
            winner_mentions = ", ".join(f"<@{user_id}>" for user_id in winners)
            announcement = (
                f"{E('q_celebrate')} **Giveaway Ended!**\n\n"
                f"Congratulations {winner_mentions}!\n"
                f"You won **{giveaway['prize']}**!"
            )
        else:
            announcement = (
                f"{E('q_error')} **Giveaway Ended!**\n\n"
                f"No valid entries — no winner could be picked for **{giveaway['prize']}**."
            )

        try:
            await channel.send(announcement)
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[Giveaway] Failed to announce winner(s) for giveaway {message_id}: {e}")

        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            # The original giveaway message is gone (deleted, or the bot
            # lost access) — the winner announcement above still went out,
            # there's just no embed left to update.
            print(f"[Giveaway] Couldn't fetch original message for giveaway {message_id} to close it out: {e}")
            return

        try:
            ended_embed = ui_embeds.giveaway(
                "GIVEAWAY ENDED",
                description=(
                    f"## {E('q_giveaway')} {giveaway['prize']}\n\n"
                    f"**{E('q_trophy')} Winner(s):** "
                    + (", ".join(f"<@{user_id}>" for user_id in winners) if winners else "No valid entries")
                    + "\n\n━━━━━━━━━━━━━━━━━━━━━━\nThis giveaway has ended."
                ),
            )
            view = discord.ui.View.from_message(message)
            for item in view.children:
                item.disabled = True
            await message.edit(embed=ended_embed, view=view)
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[Giveaway] Failed to update original message for giveaway {message_id}: {e}")

        print(f"[Giveaway] Giveaway {message_id} ended, {len(winners)} winner(s) picked.")

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        print("[Giveaway] Giveaway task started.")

    @check_giveaways.error
    async def check_giveaways_error(self, error):
        print(f"[Giveaway] Task crashed: {type(error).__name__}: {error}")


async def setup(bot):
    await bot.add_cog(GiveawayTasks(bot))

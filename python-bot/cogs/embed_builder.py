# Credits: gogeta_gg
import discord
from discord.ext import commands
from discord import app_commands

from .embed_builder_view import EmbedBuilderView


class EmbedBuilder(commands.Cog):
    """Interactive, step-by-step embed builder (/embed)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="embed",
        description="Build and send a custom embed with an interactive panel.",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def embed(self, ctx: commands.Context):
        panel = EmbedBuilderView(author_id=ctx.author.id)
        await ctx.send(embed=panel.preview_embed(), view=panel, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))

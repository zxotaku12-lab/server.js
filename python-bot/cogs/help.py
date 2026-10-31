# Credits: gogeta_gg
"""
Standalone /help cog for Gogeta's Pet.

Self-contained on purpose: everything the help command needs — its embed
styling, the banner attachment, category icons, and pagination — lives in
this one file. It does not import or modify bot.py or ui/embeds.py /
ui/pagination.py, so it can be dropped in or pulled out without touching
anything else.

Setup:
    1. Drop this file in cogs/.
    2. Put your banner image at assets/help_banner.png (path below).
    3. In bot.py, load it like any other cog, e.g.:
           await bot.load_extension("cogs.help")
    4. Make sure bot.py's help_command is still None (it already is) so
       this hybrid command doesn't collide with a built-in help.
"""

import discord
from discord import app_commands
from discord.ext import commands


BOT_NAME = "Gogeta's Pet"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━"
ACCENT_COLOR = discord.Color.from_rgb(151, 117, 255)  # bright violet

HELP_BANNER_PATH = "assets/help_banner.png"
HELP_BANNER_FILENAME = "help_banner.png"

# Emoji shown next to each category header. Falls back to a generic bullet
# for any category not listed here, so nothing ever renders blank.
CATEGORY_ICONS = {
    "General": "ℹ️",
    "Moderation": "🛡️",
    "Automod": "🤖",
    "Security": "🔐",
    "Antinuke": "💣",
    "Antibetray": "🔒",
    "Giveaway": "🎉",
    "Applications": "📋",
    "Invites": "📨",
    "Tickets": "🎫",
    "Config": "⚙️",
    "Logs": "🧾",
}
DEFAULT_ICON = "•"


def _cog_label(command) -> str:
    binding = getattr(command, "binding", None)
    if binding is not None:
        return type(binding).__cog_name__
    return "General"


def _build_categories(bot: commands.Bot) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}

    for top in bot.tree.get_commands():
        if isinstance(top, app_commands.Group):
            lines = categories.setdefault(top.name.replace("-", " ").title(), [])
            for child in top.walk_commands():
                if isinstance(child, app_commands.Command):
                    desc = child.description or ""
                    lines.append(f"`/{child.qualified_name}` — {desc}")
        elif isinstance(top, app_commands.Command):
            label = _cog_label(top)
            desc = top.description or ""
            categories.setdefault(label, []).append(f"`/{top.qualified_name}` — {desc}")

    return {k: v for k, v in sorted(categories.items()) if v}


def _base_embed(title: str, description: str, *, image_url: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description or None, color=ACCENT_COLOR)
    embed.set_author(name=f"{BOT_NAME}  •  Help")
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text=f"{BOT_NAME}  •  Help")
    if image_url:
        embed.set_image(url=image_url)
    return embed


class HelpPaginator(discord.ui.View):
    """Minimal Back/Next pager locked to whoever ran /help. Self-contained
    so this cog doesn't depend on ui/pagination.py."""

    def __init__(self, pages: list[discord.Embed], author_id: int, *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.index = 0
        self.message: discord.Message | None = None
        self._sync_labels()

    def _sync_labels(self):
        self.previous_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index == len(self.pages) - 1
        self.page_indicator.label = f"{self.index + 1} / {len(self.pages)}"
        page = self.pages[self.index]
        page.set_footer(text=f"{BOT_NAME}  •  Help  •  Page {self.index + 1} of {len(self.pages)}")

    @property
    def current(self) -> discord.Embed:
        return self.pages[self.index]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran `/help` can use these buttons.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def previous_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.current, view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.current, view=self)


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="help",
        description="List every command Gogeta offers, grouped by category.",
    )
    async def help_command(self, ctx: commands.Context):
        """Built by walking the live command tree rather than a hand-written
        list, so it can never drift out of sync with what's actually
        registered."""

        categories = _build_categories(self.bot)
        total_commands = sum(len(lines) for lines in categories.values())

        overview_desc = (
            f"{DIVIDER}\n"
            f"**{total_commands} commands** across **{len(categories)} categories** — "
            f"use the buttons below to flip through each one.\n"
            f"{DIVIDER}\n\n"
        )
        for name, lines in categories.items():
            icon = CATEGORY_ICONS.get(name, DEFAULT_ICON)
            overview_desc += f"{icon} **{name}** — `{len(lines)}` command(s)\n"

        overview = _base_embed(
            "GOGETA'S PET / COMMAND CENTER",
            overview_desc,
            image_url=f"attachment://{HELP_BANNER_FILENAME}",
        )
        pages = [overview]

        for name, lines in categories.items():
            icon = CATEGORY_ICONS.get(name, DEFAULT_ICON)
            body = f"{DIVIDER}\n" + "\n".join(lines)
            if len(body) > 4000:
                body = body[:4000] + "\n…"
            pages.append(_base_embed(f"{icon}  GOGETA'S PET / {name.upper()}", body))

        try:
            banner_file = discord.File(HELP_BANNER_PATH, filename=HELP_BANNER_FILENAME)
        except FileNotFoundError:
            banner_file = None
            overview.set_image(url=None)

        if len(pages) == 1:
            await ctx.send(embed=pages[0], file=banner_file)
            return

        paginator = HelpPaginator(pages, ctx.author.id)
        message = await ctx.send(embed=paginator.current, file=banner_file, view=paginator)
        paginator.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))

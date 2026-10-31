# Credits: gogeta_gg
"""Throwaway test cog — validates security_ui_v2.py + ui/componentsv2.py
actually render in Discord before antinuke/antibetray/automod get rebuilt
on top of them. Safe to delete once confirmed; excluded from nothing
special, just don't leave it in production long-term.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from ui import componentsv2 as cv2
from ui.theme import Color
from ui.emoji import E
from .security_ui_v2 import AdminView, security_panel, field


class CV2TestView(AdminView):
    def __init__(self, author_id: int):
        super().__init__(author_id, timeout=180)
        self.on = True
        self.render()

    def render(self):
        self.clear_items()
        p = security_panel(
            "CV2 TEST PANEL",
            "If you can see this with a colored border, bold text, a divider, "
            "and working buttons below, the Components V2 foundation is solid.",
            Color.SECURITY if self.on else Color.NEUTRAL,
            icon=E("q_shield"),
        )
        p.add_item(cv2.separator())
        p.add_item(cv2.text(field("STATUS", "🟢 ON" if self.on else "🔴 OFF")))
        p.add_item(cv2.separator())
        p.add_item(cv2.action_row(
            _mk_button("Toggle", discord.ButtonStyle.primary, self.toggle),
            _mk_button("Refresh", discord.ButtonStyle.secondary, self.refresh),
        ))
        self.add_item(p)

    async def toggle(self, interaction: discord.Interaction):
        self.on = not self.on
        self.render()
        await interaction.response.edit_message(view=self)

    async def refresh(self, interaction: discord.Interaction):
        self.render()
        await interaction.response.edit_message(view=self)


class CV2PremiumDemoView(AdminView):
    """Demonstrates the premium layout pieces — header w/ docked icon, a
    boxed stat group, link rows, banner — modeled on the reference panel
    the user provided. Two sibling Containers in one LayoutView (header+
    stats+links as one, banner as another), since Container can't nest
    inside Container."""

    def __init__(self, author_id: int, bot: commands.Bot):
        super().__init__(author_id, timeout=180)
        self.bot = bot
        self.render()

    def render(self):
        self.clear_items()
        avatar = self.bot.user.display_avatar.url if self.bot.user else None

        main = cv2.panel(
            cv2.header_section(
                "Gogeta's Pet",
                "My current prefix: `$`",
                thumbnail_url=avatar,
            ),
            cv2.separator(),
            cv2.text(
                cv2.feature_row("⚡", "Fast & reliable security suite", "with everything your server needs.")
                + "\n\n"
                + cv2.feature_row("🛡️", "Real-time protection,", "firewall, trust guard, automod & more — simple, powerful.")
            ),
            color=Color.SECURITY,
        )
        stats = cv2.stat_group([
            ("⚡", "Fast & Reliable"),
            ("🛡️", "Anti-Nuke Firewall"),
            ("🔒", "Trust Guard"),
            ("⭐", "Server Essential"),
        ], color=Color.NEUTRAL)
        links = cv2.panel(
            cv2.link_row("🌐  **Website**\nhttps://example.com", "https://example.com"),
            cv2.link_row("💜  **Support**\nhttps://discord.gg/example", "https://discord.gg/example"),
            color=Color.NEUTRAL,
        )
        self.add_item(main)
        self.add_item(stats)
        self.add_item(links)

        banner_url = avatar
        if banner_url:
            self.add_item(cv2.panel(cv2.banner(banner_url), color=Color.SECURITY))


def _mk_button(label, style, callback):
    b = discord.ui.Button(label=label, style=style)
    b.callback = callback
    return b


class CV2Test(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="cv2-test", description="Test the Components V2 security panel foundation.")
    async def cv2_test(self, ctx: commands.Context):
        view = CV2TestView(ctx.author.id)
        await ctx.send(view=view, ephemeral=True)

    @commands.hybrid_command(name="cv2-premium-test", description="Preview the premium Components V2 layout style.")
    async def cv2_premium_test(self, ctx: commands.Context):
        view = CV2PremiumDemoView(ctx.author.id, self.bot)
        await ctx.send(view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(CV2Test(bot))


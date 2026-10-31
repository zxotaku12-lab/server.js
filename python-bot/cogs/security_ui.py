# Credits: gogeta_gg
"""Shared heavy/premium Discord UI primitives for Gogeta's Pet security suite.

This module intentionally contains no Cog and is excluded from the extension
loader. It provides consistent panels, status cards, and admin-only views.
"""
from __future__ import annotations
from ui.emoji import E, bind_view_emojis

import discord
from ui.theme import Color, Icon
from ui import embeds as ui


def security_embed(title: str, description: str = "", color: discord.Color = Color.SECURITY, *, icon: str | None = None) -> discord.Embed:
    e = ui.premium(title, description, color, icon=icon or E('q_shield'), footer_label="Gogeta Security Suite")
    return e


def state(enabled: bool) -> str:
    return E('q_online') + ' **ONLINE**' if enabled else E('q_offline') + ' **OFFLINE**'


def check_line(label: str, ok: bool, detail: str = "") -> str:
    return f"{E('q_online') if ok else E('q_offline')} **{label}**" + (f" — {detail}" if detail else "")


def section(title: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "`Nothing configured`"
    return f"**{title.upper()}**\n{body}"


class AdminView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        bind_view_emojis(self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if interaction.user.id == self.author_id or (member and member.guild_permissions.administrator):
            return True
        await interaction.response.send_message(embed=ui.permission_denied("This security panel is locked to the administrator who opened it."), ephemeral=True)
        return False

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        # Safety net shared by every security panel (AutoMod, Anti-Nuke,
        # Anti-Betray, the dashboard). Without this, any unhandled exception
        # in a button/select callback dies silently in discord.py's default
        # logger and the user only ever sees Discord's generic "This
        # interaction failed" with zero information to act on.
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    embed=security_embed(
                        "SECURITY PANEL / ERROR",
                        f"That action failed unexpectedly.\n\n`{type(error).__name__}: {error}`",
                        Color.ERROR,
                        icon=E("q_error"),
                    ),
                    ephemeral=False,
                )
            except discord.HTTPException:
                pass
        print(f"[{type(self).__name__}] error in {item}: {type(error).__name__}: {error}")


class AdminModal(discord.ui.Modal):
    """Shared base for the security suite's config modals. Give any modal
    the same error safety net as AdminView without repeating it per-class."""

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    embed=security_embed(
                        "SECURITY PANEL / ERROR",
                        f"That submission failed unexpectedly.\n\n`{type(error).__name__}: {error}`",
                        Color.ERROR,
                        icon=E("q_error"),
                    ),
                    ephemeral=False,
                )
            except discord.HTTPException:
                pass
        print(f"[{type(self).__name__}] error: {type(error).__name__}: {error}")

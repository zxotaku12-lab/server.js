# Credits: gogeta_gg
"""Shared heavy/premium Discord UI primitives for Gogeta's Pet security suite
— Components V2 edition.

This module intentionally contains no Cog and is excluded from the extension
loader. It provides consistent CV2 panels, status lines, and admin-only
LayoutViews, replacing the old discord.Embed-based versions 1:1 so callers
in antinuke.py / antibetray.py / automod.py / security_dashboard.py only
need their call sites updated, not their control flow.
"""
from __future__ import annotations

import discord

from ui.emoji import E
from ui.theme import Color, Icon
from ui import componentsv2 as cv2


def security_panel(title: str, description: str = "", color: discord.Color = Color.SECURITY, *, icon: str | None = None) -> discord.ui.Container:
    """CV2 replacement for the old security_embed(). Same signature and
    call shape — swap `security_embed(...)` for `security_panel(...)` and
    attach fields with cv2.text()/cv2.section() instead of `.add_field()`."""
    return cv2.premium_panel(title, description, icon=icon or E("q_shield"), footer_label="Gogeta Security Suite", color=color)


def state(enabled: bool) -> str:
    return E("q_online") + " **ONLINE**" if enabled else E("q_offline") + " **OFFLINE**"


def check_line(label: str, ok: bool, detail: str = "") -> str:
    return f"{E('q_online') if ok else E('q_offline')} **{label}**" + (f" — {detail}" if detail else "")


def section(title: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "`Nothing configured`"
    return f"**{title.upper()}**\n{body}"


def field(name: str, value: str) -> str:
    """CV2 replacement for `embed.add_field(name=..., value=..., inline=...)`
    when rendered as a plain text block (no accessory). Sections don't have
    a true grid layout, so fields become stacked bold-label blocks —
    functionally identical to `inline=False` fields. For a 2-3 wide grid
    look, join a few field() calls with a single "\\n\\n".join(...) inside
    one cv2.text() call, matching how consecutive inline fields visually
    grouped anyway."""
    return f"**{name}**\n{value}"


def denied_panel(reason: str = "This security panel is locked to the administrator who opened it.") -> discord.ui.Container:
    return security_panel("ACCESS DENIED", reason, Color.ERROR, icon=E("q_error"))


def error_panel(scope: str, error: Exception) -> discord.ui.Container:
    return security_panel(
        f"{scope} / ERROR",
        f"That action failed unexpectedly.\n\n`{type(error).__name__}: {error}`",
        Color.ERROR,
        icon=E("q_error"),
    )


class _DeniedView(discord.ui.LayoutView):
    def __init__(self, reason: str):
        super().__init__(timeout=1)
        self.add_item(denied_panel(reason))


class AdminView(discord.ui.LayoutView):
    """CV2 base for every security panel (Anti-Nuke, Anti-Betray, AutoMod,
    the dashboard). Author/admin lock + a safety-net on_error, mirroring
    the old discord.ui.View version but built on LayoutView so buttons can
    live inside Containers.

    IMPORTANT: subclasses build their layout by calling self.add_item(...)
    with a Container built from ui/componentsv2.py helpers — LayoutView
    renders whatever is in self.children, same as before, just via
    add_item() instead of embed=... on send/edit.
    """

    def __init__(self, author_id: int, *, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if interaction.user.id == self.author_id or (member and member.guild_permissions.administrator):
            return True
        await interaction.response.send_message(
            view=_DeniedView("This security panel is locked to the administrator who opened it."),
            ephemeral=True,
        )
        return False

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        # Safety net shared by every security panel (AutoMod, Anti-Nuke,
        # Anti-Betray, the dashboard). Without this, any unhandled exception
        # in a button/select callback dies silently in discord.py's default
        # logger and the user only ever sees Discord's generic "This
        # interaction failed" with zero information to act on.
        if not interaction.response.is_done():
            try:
                view = discord.ui.LayoutView()
                view.add_item(error_panel("SECURITY PANEL", error))
                await interaction.response.send_message(view=view)
            except discord.HTTPException:
                pass
        print(f"[{type(self).__name__}] error in {item}: {type(error).__name__}: {error}")

    async def on_timeout(self) -> None:
        for item in self.walk_children():
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AdminModal(discord.ui.Modal):
    """Shared base for the security suite's config modals. Give any modal
    the same error safety net as AdminView without repeating it per-class.
    Modals themselves are unaffected by Components V2 — this class is
    unchanged from the embed-based version, kept here only so callers
    don't need two imports."""

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if not interaction.response.is_done():
            try:
                view = discord.ui.LayoutView()
                view.add_item(error_panel("SECURITY PANEL", error))
                await interaction.response.send_message(view=view)
            except discord.HTTPException:
                pass
        print(f"[{type(self).__name__}] error: {type(error).__name__}: {error}")

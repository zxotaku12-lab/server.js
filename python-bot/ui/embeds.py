# Credits: gogeta_gg
"""Premium Discord-native embed builders for Gogeta's Pet.

This module is presentation-only. Commands/cogs keep their existing data and
behavior while all user-facing embeds share one heavier visual identity.
"""

import discord
from .emoji import E

from .theme import Color, Icon

BOT_NAME = "Gogeta's Pet"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━"


def _base(
    title: str,
    description: str,
    color: discord.Color,
    icon: str = "",
    footer_label: str | None = None,
) -> discord.Embed:
    full_title = f"{icon}  {title}".strip() if icon else title
    embed = discord.Embed(
        title=full_title,
        description=description or None,
        color=color,
    )
    embed.set_author(name=f"{BOT_NAME}  •  {footer_label or 'Discord Interface'}")
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text=f"{BOT_NAME}  •  {footer_label or 'Discord Interface'}")
    return embed


def premium(title: str, description: str = "", color: discord.Color = Color.PRIMARY, *, icon: str = "", footer_label: str | None = None) -> discord.Embed:
    return _base(title, description, color, icon, footer_label)


def success(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.SUCCESS, Icon.SUCCESS, "Success")


def error(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.ERROR, Icon.ERROR, "Error")


def warning(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.WARNING, Icon.WARN, "Warning")


def info(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.INFO, "", "Information")


def security(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.SECURITY, Icon.SECURITY, "Security Suite")


def moderation(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.MODERATION, Icon.MODERATION, "Moderation")


def automod(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.AUTOMOD, Icon.AUTOMOD, "AutoMod")


def config(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.INFO, Icon.CONFIG, "Configuration")


def giveaway(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.GIVEAWAY, Icon.GIVEAWAYS, "Giveaways")


def application(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.APPLICATION, Icon.APPLICATIONS, "Staff Applications")


def invites(title: str, description: str = "") -> discord.Embed:
    return _base(title, description, Color.INVITES, Icon.INVITES, "Invite Tracker")


def permission_denied(reason: str = "You don't have permission to use this.") -> discord.Embed:
    return _base("Access Denied", reason, Color.ERROR, Icon.ERROR, "Permissions")


def empty_state(title: str, description: str) -> discord.Embed:
    return _base(title, description, Color.NEUTRAL, Icon.UNSET, "No Data")


def loading(title: str = "Working on it...") -> discord.Embed:
    return _base(title, "This should only take a moment.", Color.NEUTRAL, E("q_loading"), "Processing")

# Credits: gogeta_gg
"""Central visual identity for Gogeta's Pet Discord UI.

The bot uses a single dark/premium visual language for user-facing embeds and
interactive controls. Functional behavior is intentionally kept outside this
module.
"""

import discord
from .emoji import E


class Color:
    # Premium dark-violet / electric accent palette.
    PRIMARY = discord.Color.from_rgb(124, 92, 255)
    PRIMARY_BRIGHT = discord.Color.from_rgb(151, 117, 255)
    SUCCESS = discord.Color.from_rgb(63, 220, 125)
    ERROR = discord.Color.from_rgb(244, 78, 92)
    WARNING = discord.Color.from_rgb(255, 180, 70)
    INFO = PRIMARY
    SECURITY = discord.Color.from_rgb(62, 203, 205)
    MODERATION = discord.Color.from_rgb(235, 77, 158)
    AUTOMOD = discord.Color.from_rgb(103, 116, 255)
    NEUTRAL = discord.Color.from_rgb(57, 59, 72)
    GIVEAWAY = discord.Color.from_rgb(239, 93, 188)
    APPLICATION = discord.Color.from_rgb(112, 137, 255)
    INVITES = discord.Color.from_rgb(145, 103, 255)


class _IconMeta(type):
    def __getattr__(cls, name: str):
        mapping = {
            "SECURITY":"q_security", "ANTINUKE":"q_antinuke", "ANTIBETRAY":"q_lock",
            "AUTOMOD":"q_bot", "MODERATION":"q_mod", "APPLICATIONS":"q_quest",
            "GIVEAWAYS":"q_giveaway", "STATS":"q_audit", "MEMBERS":"q_member",
            "INVITES":"q_invite", "CONFIG":"q_admin", "LOGS":"q_logs",
            "ON":"q_online", "OFF":"q_offline", "UNSET":"q_info", "WARN":"q_error",
            "ALERT":"q_emergency", "SUCCESS":"q_success", "ERROR":"q_error",
            "BACK":"q_arrow_left", "NEXT":"q_arrow_right", "REFRESH":"q_sync",
            "EDIT":"q_paste", "SUBMIT":"q_rocket", "VIEW":"q_search",
        }
        emoji_name = mapping.get(name)
        if emoji_name is None:
            raise AttributeError(name)
        return E(emoji_name)


class Icon(metaclass=_IconMeta):
    pass


def status_text(enabled: bool) -> str:
    return f"{Icon.ON} Active" if enabled else f"{Icon.OFF} Disabled"


def status_word(enabled: bool) -> str:
    return "Active" if enabled else "Disabled"

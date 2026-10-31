# Credits: gogeta_gg
"""Components V2 toolkit — reusable building blocks for the bot's Components
V2 UI migration.

Components V2 messages cannot mix with `content`/`embeds` (Discord
restriction) — a message is either classic (content/embeds/files) or CV2
(view=LayoutView(...)), never both. Anywhere a cog currently does
`ctx.send(embed=..., view=...)` with a *classic* View, that stays exactly as
it is; only cogs being migrated switch their send call to
`ctx.send(view=SomeLayoutView())`.

Rough embed → CV2 mapping used throughout this toolkit:
    embed.title/description  -> TextDisplay (markdown heading + body)
    embed.color               -> Container(colour=...)
    embed.fields               -> TextDisplay lines inside the Container,
                                   or Section(...) when a field pairs with
                                   an accessory (button/thumbnail)
    embed.thumbnail             -> Section(..., accessory=Thumbnail(url))
    embed.image                  -> MediaGallery
    embed.footer/author/timestamp -> trailing TextDisplay line (CV2 has no
                                      dedicated footer/author slot)

This module only builds pieces. Cogs assemble them into a
`discord.ui.LayoutView` subclass (or `build_*_view()` factory function),
matching the existing `build_*_embed()` factory pattern in ui/embeds.py and
each cog's *_view.py.
"""

from __future__ import annotations

import discord

from .theme import Color, Icon
from .emoji import E

BOT_NAME = "Gogeta's Pet"


# ---------------------------------------------------------------------------
# Text helpers — markdown fragments, not components. Compose these into
# TextDisplay() calls so heading/body/meta styling stays consistent.
# ---------------------------------------------------------------------------


def heading(label: str, icon: str = "") -> str:
    prefix = f"{icon}  " if icon else ""
    return f"## {prefix}{label}"


def subheading(label: str, icon: str = "") -> str:
    prefix = f"{icon}  " if icon else ""
    return f"### {prefix}{label}"


def meta_line(footer_label: str | None = None, *, timestamp: bool = True) -> str:
    """Trailing small-print line — CV2 has no dedicated footer/timestamp
    slot, so this recreates the `BOT_NAME • label • time` look as markdown."""
    parts = [BOT_NAME]
    if footer_label:
        parts.append(footer_label)
    line = "  •  ".join(parts)
    if timestamp:
        line += f"  •  <t:{int(discord.utils.utcnow().timestamp())}:t>"
    return f"-# {line}"


def key_value_lines(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"**{k}**\n{v}" for k, v in pairs)


def bullet_list(items: list[str], empty_text: str = "None configured") -> str:
    if not items:
        return f"*{empty_text}*"
    return "\n".join(f"• {item}" for item in items)


def status_row(label: str, enabled: bool) -> str:
    dot = Icon.ON if enabled else Icon.OFF
    return f"{dot} **{label}**"


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------


def text(content: str) -> discord.ui.TextDisplay:
    return discord.ui.TextDisplay(content)


def separator(*, visible: bool = True, spacing: discord.SeparatorSpacing = discord.SeparatorSpacing.small) -> discord.ui.Separator:
    return discord.ui.Separator(visible=visible, spacing=spacing)


def panel(
    *items: discord.ui.Item,
    color: discord.Color = Color.PRIMARY,
    spoiler: bool = False,
) -> discord.ui.Container:
    """The CV2 analogue of `ui_embeds.premium(...)` — a bordered, colored
    box. Build the inside with text()/separator()/section()/gallery() and
    pass them in, e.g.:

        panel(
            text(heading("Title", Icon.SECURITY)),
            text("Body copy here."),
            separator(),
            text(meta_line("Security Suite")),
            color=Color.SECURITY,
        )
    """
    return discord.ui.Container(*items, accent_color=color, spoiler=spoiler)


def section(
    *lines: str,
    accessory: discord.ui.Item,
) -> discord.ui.Section:
    """Up to 3 TextDisplay lines + one required accessory (Button or
    Thumbnail). The CV2 equivalent of an inline embed field, or a title
    row with a thumbnail/button docked to the right. Discord rejects a
    Section with no accessory, so one must always be supplied — use
    section() only when you have a thumbnail or button to dock; otherwise
    use plain text()."""
    if not 1 <= len(lines) <= 3:
        raise ValueError("Section supports 1–3 text lines")
    return discord.ui.Section(*[discord.ui.TextDisplay(line) for line in lines], accessory=accessory)


def thumbnail(url: str, *, description: str | None = None, spoiler: bool = False) -> discord.ui.Thumbnail:
    return discord.ui.Thumbnail(url, description=description, spoiler=spoiler)


def gallery(*urls: str) -> discord.ui.MediaGallery:
    """Replaces embed.set_image() — pass one or more image URLs. Used as
    the branded banner strip at the bottom of a premium panel, matching
    the reference design's bold logo/wordmark banner."""
    return discord.ui.MediaGallery(*[discord.MediaGalleryItem(url) for url in urls])


def action_row(*items: discord.ui.Item) -> discord.ui.ActionRow:
    """Wraps buttons/selects for placement inside a Container. Top-level
    buttons on a LayoutView (declared directly as class attributes) don't
    need this — only ones nested inside a Container do."""
    return discord.ui.ActionRow(*items)


# ---------------------------------------------------------------------------
# Preset panel styles — CV2 equivalents of ui/embeds.py's premium/success/
# error/... helpers. Each returns a ready-to-add Container.
# ---------------------------------------------------------------------------


def premium_panel(title: str, description: str = "", *, icon: str = "", footer_label: str | None = None, color: discord.Color = Color.PRIMARY) -> discord.ui.Container:
    items = [text(heading(title, icon))]
    if description:
        items.append(text(description))
    items.append(separator())
    items.append(text(meta_line(footer_label)))
    return panel(*items, color=color)


# ---------------------------------------------------------------------------
# Premium layout pieces — matching a reference-style layout: a header row
# with a docked logo/icon, a boxed stat/feature group set apart from the
# header, link-style rows, and a bold banner strip. None of this fights CV2's
# real limits (no gradients, no glow, no custom fonts) — it gets the "designed,
# not default" feel through structure and hierarchy instead: a distinct nested
# Container for stats, a Section docking an icon beside the title instead of
# everything flush-left, and a banner graphic pinned to the bottom.
#
# Typical composition:
#
#     panel(
#         header_section("Snitch", "Fast & reliable music bot", thumbnail_url=logo_url),
#         separator(),
#         stat_group([
#             ("⚡", "Fast & Reliable"),
#             ("🎵", "High Quality"),
#             ("🛠️", "Utility Packed"),
#         ]),
#         separator(),
#         link_row("🌐 Website", "https://..."),
#         link_row("💜 Support", "https://..."),
#         separator(spacing=discord.SeparatorSpacing.large),
#         banner("https://cdn.example.com/wordmark.png"),
#         color=Color.PRIMARY,
#     )
# ---------------------------------------------------------------------------


def header_section(title: str, subtitle: str = "", *, thumbnail_url: str | None = None, icon: str = "") -> discord.ui.Item:
    """The top row of a premium panel — bold title (+ optional wave/emoji
    icon prefix) and a one-line subtitle, with a logo/avatar docked to the
    right via a Section+Thumbnail. Falls back to a single combined
    TextDisplay if no thumbnail is given (Section requires an accessory,
    so without one this can't use Section — and a Container can't nest
    inside the panel() Container this item gets passed into, so the
    fallback must stay a single Item, never another Container)."""
    lines = [heading(title, icon)]
    if subtitle:
        lines.append(subtitle)
    if thumbnail_url:
        return section(*lines, accessory=thumbnail(thumbnail_url))
    return text("\n".join(lines))


def stat_group(rows: list[tuple[str, str]], *, color: discord.Color = Color.NEUTRAL) -> discord.ui.Container:
    """A visually distinct boxed sub-panel for short stat/feature rows —
    `[("⚡", "Fast & Reliable"), ("🎵", "High Quality")]` — matching the
    reference's separated stat card. Nesting a Container inside a Container
    isn't supported, so this renders as its own Container meant to sit as a
    sibling item in the outer panel(...) call (see the composition example
    above), not literally nested inside it."""
    lines = [f"{emoji}  **{label}**" for emoji, label in rows]
    return panel(text("\n".join(lines)), color=color)


def link_row(label: str, url: str) -> discord.ui.Section:
    """A clickable-looking link row — label text on the left, an actual
    link-style button docked right, mirroring the reference's
    Website/Support rows. Discord renders link buttons with an outbound
    arrow automatically."""
    return section(label, accessory=discord.ui.Button(style=discord.ButtonStyle.link, url=url, label="Open"))


def banner(url: str, *, description: str | None = None) -> discord.ui.MediaGallery:
    """The bold branded strip near the bottom of a premium panel — a single
    wide graphic (wordmark, logo banner, etc). Thin wrapper over gallery()
    for a single image, named for what it's used for."""
    return gallery(url) if description is None else discord.ui.MediaGallery(discord.MediaGalleryItem(url, description=description))


def feature_row(emoji: str, title: str, detail: str = "") -> str:
    """One line of a feature list — bold emoji-led title with an optional
    dimmer detail line underneath, matching the reference's
    '⚡ Fast & reliable music bot / with essentials your server needs' rows.
    Returns markdown text — combine several with '\\n\\n'.join(...) inside a
    single text() call so they render as one grouped block."""
    line = f"{emoji}  **{title}**"
    if detail:
        line += f"\n{detail}"
    return line


def success_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.SUCCESS, footer_label="Success", color=Color.SUCCESS)


def error_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.ERROR, footer_label="Error", color=Color.ERROR)


def warning_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.WARN, footer_label="Warning", color=Color.WARNING)


def info_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, footer_label="Information", color=Color.INFO)


def security_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.SECURITY, footer_label="Security Suite", color=Color.SECURITY)


def moderation_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.MODERATION, footer_label="Moderation", color=Color.MODERATION)


def automod_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.AUTOMOD, footer_label="AutoMod", color=Color.AUTOMOD)


def config_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.CONFIG, footer_label="Configuration", color=Color.INFO)


def giveaway_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.GIVEAWAYS, footer_label="Giveaways", color=Color.GIVEAWAY)


def application_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.APPLICATIONS, footer_label="Staff Applications", color=Color.APPLICATION)


def invites_panel(title: str, description: str = "") -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.INVITES, footer_label="Invite Tracker", color=Color.INVITES)


def permission_denied_panel(reason: str = "You don't have permission to use this.") -> discord.ui.Container:
    return premium_panel("Access Denied", reason, icon=Icon.ERROR, footer_label="Permissions", color=Color.ERROR)


def empty_state_panel(title: str, description: str) -> discord.ui.Container:
    return premium_panel(title, description, icon=Icon.UNSET, footer_label="No Data", color=Color.NEUTRAL)


# ---------------------------------------------------------------------------
# Base LayoutView — the CV2 analogue of ui/views.py's BaseView. Subclass
# this the same way cogs subclass BaseView today.
# ---------------------------------------------------------------------------


class BaseLayoutView(discord.ui.LayoutView):
    """Locks all interactive children to the user who triggered the
    interaction that created this view, mirroring ui/views.py's BaseView.
    Interactive items may be nested inside Containers/Sections/ActionRows,
    so this checks via walk_children() rather than .children directly."""

    def __init__(self, author_id: int | None = None, *, timeout: float = 180, allow_any_user: bool = False):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.allow_any_user = allow_any_user
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.allow_any_user or self.author_id is None:
            return True
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            view=_denied_view(),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for item in self.walk_children():
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def bind_emojis(self, label_emoji_map: dict[str, str] | None = None) -> None:
        """CV2-aware version of emoji.bind_view_emojis — walks nested
        Containers/Sections/ActionRows, not just top-level children."""
        from .emoji import LABEL_EMOJIS
        mapping = label_emoji_map or LABEL_EMOJIS
        for item in self.walk_children():
            label = getattr(item, "label", None)
            if label in mapping:
                emoji = E(mapping[label])
                if emoji:
                    item.emoji = emoji


def _denied_view() -> discord.ui.LayoutView:
    class _DeniedView(discord.ui.LayoutView):
        panel_container = permission_denied_panel("Only the person who opened this panel can use it.")
    return _DeniedView()

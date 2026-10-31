# Credits: gogeta_gg
"""Interactive step-by-step embed builder UI.

Users assemble a discord.Embed piece by piece via buttons + modals, with a
live preview shown as the panel message itself. Follows the same patterns as
apply_view.py: a BaseView-style author lock, ui/embeds.py styling, and
bind_view_emojis for custom emoji support.
"""

from __future__ import annotations

import re

import discord

from ui.emoji import E, bind_view_emojis
from ui.views import BaseView
from ui import embeds as ui_embeds
from ui.theme import Color as ThemeColor

MAX_FIELDS = 25
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _parse_color(raw: str) -> discord.Color | None:
    raw = raw.strip()
    if not raw:
        return None
    if HEX_RE.match(raw):
        return discord.Color(int(raw.lstrip("#"), 16))
    named = getattr(discord.Color, raw.lower().replace(" ", "_"), None)
    if callable(named):
        try:
            return named()
        except TypeError:
            return None
    return None


class EmbedState:
    """Plain data holder for the embed under construction."""

    def __init__(self, author_id: int):
        self.author_id = author_id
        self.title: str | None = None
        self.description: str | None = None
        self.color: discord.Color = ThemeColor.PRIMARY
        self.url: str | None = None
        self.author_name: str | None = None
        self.author_icon_url: str | None = None
        self.footer_text: str | None = None
        self.footer_icon_url: str | None = None
        self.thumbnail_url: str | None = None
        self.image_url: str | None = None
        self.timestamp: bool = False
        self.fields: list[dict] = []  # [{name, value, inline}]

    def to_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title or None,
            description=self.description or None,
            color=self.color,
            url=self.url or None,
        )
        if self.author_name:
            embed.set_author(name=self.author_name, icon_url=self.author_icon_url or None)
        if self.footer_text:
            embed.set_footer(text=self.footer_text, icon_url=self.footer_icon_url or None)
        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if self.image_url:
            embed.set_image(url=self.image_url)
        if self.timestamp:
            embed.timestamp = discord.utils.utcnow()
        for f in self.fields:
            embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        return embed

    def is_empty(self) -> bool:
        return not (
            self.title or self.description or self.author_name or self.footer_text
            or self.thumbnail_url or self.image_url or self.fields
        )


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------


class ContentModal(discord.ui.Modal, title="Title & Description"):
    title_input = discord.ui.TextInput(
        label="Title",
        max_length=256,
        required=False,
        placeholder="Embed title...",
    )
    description_input = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=False,
        placeholder="Embed description...",
    )
    url_input = discord.ui.TextInput(
        label="Title URL (optional)",
        max_length=512,
        required=False,
        placeholder="https://...",
    )

    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__()
        self.panel = panel
        self.title_input.default = panel.state.title
        self.description_input.default = panel.state.description
        self.url_input.default = panel.state.url

    async def on_submit(self, interaction: discord.Interaction):
        self.panel.state.title = str(self.title_input).strip() or None
        self.panel.state.description = str(self.description_input).strip() or None
        url = str(self.url_input).strip()
        if url and not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                E("q_error") + " Title URL must start with http:// or https://.", ephemeral=True
            )
            return
        self.panel.state.url = url or None
        await self.panel.refresh(interaction)


class ColorModal(discord.ui.Modal, title="Embed Color"):
    color_input = discord.ui.TextInput(
        label="Hex color or name",
        max_length=32,
        required=True,
        placeholder="#7C5CFF, blurple, red, green...",
    )

    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        color = _parse_color(str(self.color_input))
        if color is None:
            await interaction.response.send_message(
                E("q_error") + " That's not a valid hex code (e.g. `#7C5CFF`) or color name (e.g. `red`).",
                ephemeral=True,
            )
            return
        self.panel.state.color = color
        await self.panel.refresh(interaction)


class AuthorModal(discord.ui.Modal, title="Author"):
    name_input = discord.ui.TextInput(
        label="Author name",
        max_length=256,
        required=False,
        placeholder="Leave blank to remove the author row",
    )
    icon_input = discord.ui.TextInput(
        label="Author icon URL (optional)",
        max_length=512,
        required=False,
        placeholder="https://...",
    )

    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__()
        self.panel = panel
        self.name_input.default = panel.state.author_name
        self.icon_input.default = panel.state.author_icon_url

    async def on_submit(self, interaction: discord.Interaction):
        icon = str(self.icon_input).strip()
        if icon and not icon.startswith(("http://", "https://")):
            await interaction.response.send_message(
                E("q_error") + " Author icon must be a URL starting with http:// or https://.", ephemeral=True
            )
            return
        self.panel.state.author_name = str(self.name_input).strip() or None
        self.panel.state.author_icon_url = icon or None
        await self.panel.refresh(interaction)


class FooterModal(discord.ui.Modal, title="Footer"):
    text_input = discord.ui.TextInput(
        label="Footer text",
        max_length=2048,
        required=False,
        placeholder="Leave blank to remove the footer",
    )
    icon_input = discord.ui.TextInput(
        label="Footer icon URL (optional)",
        max_length=512,
        required=False,
        placeholder="https://...",
    )

    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__()
        self.panel = panel
        self.text_input.default = panel.state.footer_text
        self.icon_input.default = panel.state.footer_icon_url

    async def on_submit(self, interaction: discord.Interaction):
        icon = str(self.icon_input).strip()
        if icon and not icon.startswith(("http://", "https://")):
            await interaction.response.send_message(
                E("q_error") + " Footer icon must be a URL starting with http:// or https://.", ephemeral=True
            )
            return
        self.panel.state.footer_text = str(self.text_input).strip() or None
        self.panel.state.footer_icon_url = icon or None
        await self.panel.refresh(interaction)


class ImagesModal(discord.ui.Modal, title="Thumbnail & Image"):
    thumbnail_input = discord.ui.TextInput(
        label="Thumbnail URL (small, top-right)",
        max_length=512,
        required=False,
        placeholder="https://...",
    )
    image_input = discord.ui.TextInput(
        label="Image URL (large, bottom)",
        max_length=512,
        required=False,
        placeholder="https://...",
    )

    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__()
        self.panel = panel
        self.thumbnail_input.default = panel.state.thumbnail_url
        self.image_input.default = panel.state.image_url

    async def on_submit(self, interaction: discord.Interaction):
        thumb = str(self.thumbnail_input).strip()
        img = str(self.image_input).strip()
        for val, label in ((thumb, "Thumbnail"), (img, "Image")):
            if val and not val.startswith(("http://", "https://")):
                await interaction.response.send_message(
                    E("q_error") + f" {label} must be a URL starting with http:// or https://.", ephemeral=True
                )
                return
        self.panel.state.thumbnail_url = thumb or None
        self.panel.state.image_url = img or None
        await self.panel.refresh(interaction)


class AddFieldModal(discord.ui.Modal, title="Add Field"):
    name_input = discord.ui.TextInput(label="Field name", max_length=256, required=True)
    value_input = discord.ui.TextInput(
        label="Field value", style=discord.TextStyle.paragraph, max_length=1024, required=True
    )
    inline_input = discord.ui.TextInput(
        label="Inline? (yes/no)", max_length=5, required=False, default="yes", placeholder="yes"
    )

    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.panel.state.fields) >= MAX_FIELDS:
            await interaction.response.send_message(
                E("q_error") + f" You can't have more than {MAX_FIELDS} fields.", ephemeral=True
            )
            return
        inline = str(self.inline_input).strip().lower() not in ("no", "false", "0")
        self.panel.state.fields.append({
            "name": str(self.name_input).strip(),
            "value": str(self.value_input).strip(),
            "inline": inline,
        })
        await self.panel.refresh(interaction)


class RemoveFieldSelect(discord.ui.Select):
    def __init__(self, panel: "EmbedBuilderView"):
        self.panel = panel
        options = [
            discord.SelectOption(label=f"{i + 1}. {f['name'][:90]}", value=str(i))
            for i, f in enumerate(panel.state.fields)
        ]
        super().__init__(placeholder="Choose a field to remove...", options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        if 0 <= idx < len(self.panel.state.fields):
            del self.panel.state.fields[idx]
        await self.panel.refresh(interaction)


class RemoveFieldView(BaseView):
    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__(author_id=panel.state.author_id, timeout=120)
        self.panel = panel
        self.add_item(RemoveFieldSelect(panel))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.panel.refresh(interaction)


class DestinationSelect(discord.ui.ChannelSelect):
    def __init__(self, panel: "EmbedBuilderView"):
        self.panel = panel
        super().__init__(
            placeholder="Choose a channel to send this embed to...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0].resolve() or await self.values[0].fetch()
        perms = channel.permissions_for(channel.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(
                E("q_error") + f" I don't have permission to send embeds in {channel.mention}.",
                ephemeral=True,
            )
            return
        try:
            await channel.send(embed=self.panel.state.to_embed())
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                E("q_error") + f" Discord rejected that embed: {exc}", ephemeral=True
            )
            return
        for child in self.panel.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=ui_embeds.success("Embed Sent", f"Your embed was posted in {channel.mention}."),
            view=self.panel,
        )
        self.panel.stop()


class SendView(BaseView):
    def __init__(self, panel: "EmbedBuilderView"):
        super().__init__(author_id=panel.state.author_id, timeout=120)
        self.add_item(DestinationSelect(panel))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.panel.refresh(interaction)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------


class EmbedBuilderView(BaseView):
    """Step-by-step embed builder. The panel message doubles as the live
    preview: every edit re-renders `state.to_embed()` in place."""

    def __init__(self, author_id: int):
        super().__init__(author_id=author_id, timeout=600)
        self.state = EmbedState(author_id)
        bind_view_emojis(self)
        self._sync_buttons()

    def _sync_buttons(self):
        self.remove_field_btn.disabled = not self.state.fields
        self.add_field_btn.disabled = len(self.state.fields) >= MAX_FIELDS

    def preview_embed(self) -> discord.Embed:
        if self.state.is_empty():
            return ui_embeds.premium(
                "Embed Builder",
                "This embed is empty. Use the buttons below to add a title, "
                "description, fields, and more — this message updates live "
                "as you go.",
                icon=E("q_paste"),
                footer_label="Embed Builder",
            )
        return self.state.to_embed()

    async def refresh(self, interaction: discord.Interaction):
        self._sync_buttons()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=self.preview_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=self.preview_embed(), view=self)

    # Row 0 — content
    @discord.ui.button(label="Title / Description", style=discord.ButtonStyle.primary, row=0)
    async def content_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ContentModal(self))

    @discord.ui.button(label="Color", style=discord.ButtonStyle.primary, row=0)
    async def color_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ColorModal(self))

    @discord.ui.button(label="Author", style=discord.ButtonStyle.secondary, row=0)
    async def author_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuthorModal(self))

    @discord.ui.button(label="Footer", style=discord.ButtonStyle.secondary, row=0)
    async def footer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FooterModal(self))

    # Row 1 — media & fields
    @discord.ui.button(label="Thumbnail / Image", style=discord.ButtonStyle.secondary, row=1)
    async def images_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ImagesModal(self))

    @discord.ui.button(label="Add Field", style=discord.ButtonStyle.success, row=1)
    async def add_field_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddFieldModal(self))

    @discord.ui.button(label="Remove Field", style=discord.ButtonStyle.danger, row=1)
    async def remove_field_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=RemoveFieldView(self))

    @discord.ui.button(label="Timestamp", style=discord.ButtonStyle.secondary, row=1)
    async def timestamp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state.timestamp = not self.state.timestamp
        button.style = discord.ButtonStyle.success if self.state.timestamp else discord.ButtonStyle.secondary
        await self.refresh(interaction)

    # Row 2 — lifecycle
    @discord.ui.button(label="Reset", style=discord.ButtonStyle.danger, row=2)
    async def reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.state = EmbedState(self.author_id)
        self.timestamp_btn.style = discord.ButtonStyle.secondary
        await self.refresh(interaction)

    @discord.ui.button(label="Send", style=discord.ButtonStyle.success, row=2)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state.is_empty():
            await interaction.response.send_message(
                E("q_error") + " Add at least a title, description, or field before sending.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(view=SendView(self))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=ui_embeds.empty_state("Embed Builder Cancelled", "No embed was sent."),
            view=self,
        )
        self.stop()

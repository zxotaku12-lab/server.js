# Credits: gogeta_gg
"""
Generic pagination — one implementation shared by invite leaderboards,
giveaway participant lists, security logs, application queues, purge
confirmations, anywhere a list is too long for a single embed.
"""

import discord
from .emoji import E, bind_view_emojis

from .views import BaseView


class Paginator(BaseView):
    """
    Pass a list of pre-built discord.Embed pages. Handles Previous/Next,
    disables at the edges, shows "Page x / y", locks to author, and
    disables itself on timeout instead of leaving a dead collector.
    """

    def __init__(self, pages: list[discord.Embed], author_id: int, *, timeout: float = 180):
        super().__init__(author_id=author_id, timeout=timeout)
        if not pages:
            raise ValueError("Paginator requires at least one page")
        self.pages = pages
        self.index = 0
        self._sync_labels()
        bind_view_emojis(self)

    def _sync_labels(self):
        self.previous_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index == len(self.pages) - 1
        self.page_indicator.label = f"{self.index + 1} / {len(self.pages)}"
        page = self.pages[self.index]
        page.set_footer(text=f"{page.footer.text or 'Gogeta Sentinel'} • Page {self.index + 1} of {len(self.pages)}")
        bind_view_emojis(self)

    @property
    def current(self) -> discord.Embed:
        return self.pages[self.index]

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def previous_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.current, view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # purely a label, not clickable in practice (disabled)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.current, view=self)


def chunk(items: list, size: int) -> list[list]:
    """Split a list into `size`-item chunks — first step for turning any
    long list into paginated embed pages."""
    return [items[i:i + size] for i in range(0, len(items), size)]

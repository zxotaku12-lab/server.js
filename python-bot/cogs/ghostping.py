# Credits: gogeta_gg
"""Ghost Ping on Join.

When a human joins, the bot mentions them in every configured channel and deletes the
mention a moment later. Discord still notifies them for each channel, so they get pulled
into the channels you want them to read, but nothing clutters the chat.

ONE command (needs Manage Server):
    /ghostping channels:#rules #info #roles #announcements   -> set the channels (as many as you like)
    /ghostping channels:off                                  -> stop ghost pinging
    /ghostping                                               -> show what is set

Prefix form works too: $ghostping #rules #info #roles
Channels can be #mentions, raw IDs or exact channel names, separated by spaces or commas.

Self-contained: its own table in ghostping.db, auto-loaded by the bot's cog loader.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from contextlib import closing
from typing import Callable, Iterable

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("gogeta.ghostping")

DB_NAME = "ghostping.db"
MAX_CHANNELS = 25        # per server; keeps a join from becoming a rate-limit storm
DELETE_DELAY = max(0.0, min(30.0, float(os.getenv("GHOSTPING_DELAY", "1"))))  # seconds the mention stays up
SEND_GAP = 0.35          # pause between channel sends
QUEUE_LIMIT = 60         # joins waiting per server; extra joins during a raid are skipped
_CHANNEL_ID_RE = re.compile(r"<#(\d{15,21})>|(\d{15,21})")


# --------------------------------------------------------------------------- storage
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ghostping_channels ("
            "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, position INTEGER NOT NULL, "
            "PRIMARY KEY (guild_id, channel_id))"
        )


def get_channels(guild_id: int) -> list[int]:
    """Channel ids in the order they were given."""
    with closing(_connect()) as conn:
        return [
            int(r["channel_id"])
            for r in conn.execute(
                "SELECT channel_id FROM ghostping_channels WHERE guild_id = ? ORDER BY position", (guild_id,)
            )
        ]


def save_channels(guild_id: int, channel_ids: Iterable[int]) -> list[int]:
    """Replace the whole list (order kept, duplicates dropped, capped)."""
    ordered: list[int] = []
    for cid in channel_ids:
        if int(cid) not in ordered:
            ordered.append(int(cid))
    ordered = ordered[:MAX_CHANNELS]
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM ghostping_channels WHERE guild_id = ?", (guild_id,))
        conn.executemany(
            "INSERT INTO ghostping_channels (guild_id, channel_id, position) VALUES (?, ?, ?)",
            [(guild_id, cid, pos) for pos, cid in enumerate(ordered)],
        )
    return ordered


# --------------------------------------------------------------------------- parsing
def parse_channels(
    text: str,
    get_channel: Callable[[int], object | None],
    find_by_name: Callable[[str], object | None],
    is_text: Callable[[object], bool],
) -> tuple[list[int], list[str]]:
    """Turn '#a <#123> 456 rules' into (valid channel ids, tokens that did not resolve).

    Takes lookups as callables so it can be tested without Discord.
    """
    found: list[int] = []
    unknown: list[str] = []
    for token in re.split(r"[\s,;]+", (text or "").strip()):
        if not token:
            continue
        channel = None
        match = _CHANNEL_ID_RE.fullmatch(token)
        if match:
            channel = get_channel(int(match.group(1) or match.group(2)))
        else:
            channel = find_by_name(token.lstrip("#").lower())
        if channel is not None and is_text(channel):
            cid = int(channel.id)
            if cid not in found:
                found.append(cid)
        else:
            unknown.append(token)
    return found, unknown


# --------------------------------------------------------------------------- cog
class GhostPing(commands.Cog):
    """Ghost-pings new members into the configured channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        setup_database()
        self.queues: dict[int, asyncio.Queue] = {}
        self.workers: dict[int, asyncio.Task] = {}
        self.cleanups: set[asyncio.Task] = set()
        self.screening: set[tuple[int, int]] = set()   # members waiting to pass Membership Screening

    async def cog_unload(self) -> None:
        for task in [*self.workers.values(), *self.cleanups]:
            task.cancel()

    # ---- helpers ---------------------------------------------------------
    def _resolve(self, guild: discord.Guild, text: str) -> tuple[list[int], list[str]]:
        names = {c.name.lower(): c for c in guild.text_channels}
        return parse_channels(
            text,
            get_channel=guild.get_channel,
            find_by_name=names.get,
            is_text=lambda c: isinstance(c, discord.TextChannel),
        )

    @staticmethod
    def _can_send(guild: discord.Guild, channel: discord.TextChannel) -> bool:
        me = guild.me
        if me is None:
            return False
        perms = channel.permissions_for(me)
        return bool(perms.view_channel and perms.send_messages)

    def _problem_channels(self, guild: discord.Guild, ids: Iterable[int]) -> list[str]:
        bad = []
        for cid in ids:
            channel = guild.get_channel(cid)
            if isinstance(channel, discord.TextChannel) and not self._can_send(guild, channel):
                bad.append(channel.mention)
        return bad

    @staticmethod
    def _fmt(ids: Iterable[int]) -> str:
        return " ".join(f"<#{i}>" for i in ids) or "`none`"

    # ---- the actual ghost ping -------------------------------------------
    async def _delete_later(self, message: discord.Message, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _ping_member(self, member: discord.Member) -> tuple[int, list[str]]:
        """Mention `member` in each configured channel, then delete. Returns (sent, failed channels)."""
        guild = member.guild
        ids = get_channels(guild.id)
        if not ids:
            return 0, []
        if guild.get_member(member.id) is None:     # already left
            return 0, []

        allowed = discord.AllowedMentions(users=[member], roles=False, everyone=False, replied_user=False)
        sent, failed = 0, []
        for cid in ids:
            channel = guild.get_channel(cid)
            if not isinstance(channel, discord.TextChannel) or not self._can_send(guild, channel):
                failed.append(f"<#{cid}>")
                continue
            try:
                message = await channel.send(member.mention, allowed_mentions=allowed)
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("Ghost ping failed in #%s (%s)", getattr(channel, "name", cid), type(exc).__name__)
                failed.append(channel.mention)
                continue
            sent += 1
            task = asyncio.create_task(self._delete_later(message, DELETE_DELAY))
            self.cleanups.add(task)
            task.add_done_callback(self.cleanups.discard)
            await asyncio.sleep(SEND_GAP)
        return sent, failed

    # ---- join queue (one worker per server, raid-safe) --------------------
    async def _worker(self, guild_id: int) -> None:
        queue = self.queues[guild_id]
        try:
            while True:
                try:
                    member = await asyncio.wait_for(queue.get(), timeout=60)
                except asyncio.TimeoutError:
                    break
                try:
                    await self._ping_member(member)
                except Exception:
                    log.exception("Ghost ping worker error in guild %s", guild_id)
        finally:
            self.workers.pop(guild_id, None)

    def _enqueue(self, member: discord.Member) -> None:
        guild_id = member.guild.id
        if not get_channels(guild_id):
            return
        queue = self.queues.setdefault(guild_id, asyncio.Queue())
        if queue.qsize() >= QUEUE_LIMIT:
            log.warning("Ghost ping queue full in guild %s (raid?); skipping %s", guild_id, member.id)
            return
        queue.put_nowait(member)
        worker = self.workers.get(guild_id)
        if worker is None or worker.done():
            self.workers[guild_id] = asyncio.create_task(self._worker(guild_id))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        if getattr(member, "pending", False):
            # Still on the rules screen: they can't see channels yet, so wait until they pass it.
            self.screening.add((member.guild.id, member.id))
            return
        self._enqueue(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        key = (after.guild.id, after.id)
        if key in self.screening and not getattr(after, "pending", False):
            self.screening.discard(key)
            if not after.bot:
                self._enqueue(after)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        self.screening.discard((member.guild.id, member.id))

    # ---- the one command --------------------------------------------------
    @commands.hybrid_command(
        name="ghostping",
        description="Ghost-ping new members into the channels you pick. Leave empty to see the current list.",
    )
    @app_commands.describe(channels="Several channels at once, e.g. #rules #info #roles  (or 'off' to stop)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def ghostping(self, ctx: commands.Context, *, channels: str = ""):
        guild = ctx.guild
        none = discord.AllowedMentions.none()
        text = channels.strip()

        if not text:
            ids = get_channels(guild.id)
            if not ids:
                await ctx.send("Ghost ping is **off**. Set it with `/ghostping channels:#rules #info #roles`.",
                               ephemeral=True)
                return
            lines = [f"Ghost ping is **on** for {len(ids)}/{MAX_CHANNELS} channel(s): {self._fmt(ids)}"]
            problems = self._problem_channels(guild, ids)
            if problems:
                lines.append(f"I can't send in {' '.join(problems)}. Give me View Channel + Send Messages.")
            await ctx.send("\n".join(lines), ephemeral=True, allowed_mentions=none)
            return

        if text.lower() in {"off", "none", "clear", "disable", "stop"}:
            save_channels(guild.id, [])
            await ctx.send("Ghost ping is now **off**.", ephemeral=True)
            return

        found, unknown = self._resolve(guild, text)
        if not found:
            note = f" Couldn't find: {' '.join(unknown)}" if unknown else ""
            await ctx.send("Give me at least one text channel (mention, ID or exact name)." + note, ephemeral=True)
            return
        saved = save_channels(guild.id, found)
        lines = [f"Ghost ping is **on** for {len(saved)}/{MAX_CHANNELS} channel(s): {self._fmt(saved)}"]
        if len(found) > MAX_CHANNELS:
            lines.append(f"Only the first {MAX_CHANNELS} were kept.")
        if unknown:
            lines.append(f"Skipped (not a text channel I can find): {' '.join(unknown)}")
        problems = self._problem_channels(guild, saved)
        if problems:
            lines.append(f"Heads up, I can't send in {' '.join(problems)}. Give me View Channel + Send Messages.")
        await ctx.send("\n".join(lines), ephemeral=True, allowed_mentions=none)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GhostPing(bot))

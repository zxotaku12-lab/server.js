# Credits: gogeta_gg
"""Emoji Vault — drop custom emoji from any server you're in straight into
one designated "vault" server just by sending them in a message.

No slash command needed to trigger it: pick a target server with
`/emojivault set`, then anywhere you (or anyone with Manage Expressions in
the vault server) send a message containing custom emoji — from any
server, since the image comes straight from Discord's CDN via the emoji's
own ID — this cog copies each one into the vault. Handles a full batch in
one message (Discord's own per-guild cap is 50 static + 50 animated).

Positional replace: the Nth new emoji in your message replaces the
*picture* on the vault's Nth existing emoji while keeping that emoji's
original name (Discord can't edit an emoji's image directly, only
delete+recreate, which is what happens under the hood). Anything past
however many emoji the vault already has is added fresh under its own
name. Sending the same picture twice (even under a different name/ID,
e.g. re-uploaded to two different servers) only counts once — dedupe is
by the image's actual bytes, not just by ID.
"""

import asyncio
import hashlib
import os
import re
import time

import discord
from discord.ext import commands

from . import emoji_vault_db
from ui import embeds
from ui.emoji import E

EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]{2,32}):(\d{15,20})>")
MAX_PER_MESSAGE = 50
UPLOAD_DELAY_SECONDS = 1.1
CDN_FETCH_DELAY_SECONDS = 0.4


class EmojiVault(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------------
    # Config commands
    # ---------------------------------------------------------------

    @commands.hybrid_group(
        name="emojivault",
        description="Configure the server that receives copied-in emoji.",
        fallback="status",
    )
    @commands.guild_only()
    async def emojivault(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            vault_id = emoji_vault_db.get_vault_guild_id()
            if vault_id is None:
                await ctx.send(embed=embeds.info(
                    "Emoji Vault — Not Configured",
                    "No vault server set yet. Run `/emojivault set` inside the "
                    "server you want emoji copied into (needs Manage Expressions).",
                ))
                return

            vault_guild = self.bot.get_guild(vault_id)
            if vault_guild is None:
                await ctx.send(embed=embeds.warning(
                    "Emoji Vault — Unreachable",
                    f"A vault is configured (`{vault_id}`) but I'm not in that server "
                    "anymore. Run `/emojivault set` somewhere I'm still in to fix this.",
                ))
                return

            if ctx.guild.id != vault_id:
                await ctx.send(embed=embeds.info(
                    "Emoji Vault",
                    f"**{vault_guild.name}** is the current vault — this isn't it. "
                    "Run `/emojivault set` in this server if you want to switch it here.",
                ))
                return

            static_count = sum(1 for e in vault_guild.emojis if not e.animated)
            animated_count = sum(1 for e in vault_guild.emojis if e.animated)
            limit = vault_guild.emoji_limit

            await ctx.send(embed=embeds.premium(
                E("q_chest") + " Emoji Vault — Status",
                f"**This server is the vault.**\n\n"
                f"**Static slots:** {static_count}/{limit}\n"
                f"**Animated slots:** {animated_count}/{limit}\n\n"
                "Anyone here with **Manage Expressions** can trigger a copy by just "
                "sending a message with custom emoji in it — from any server, in "
                "any channel I can read, up to 50 unique emoji per message. Each new "
                "emoji replaces the picture on an existing vault emoji (keeping its "
                "name) in the order you send them; anything extra is added as new.",
                embeds.Color.PRIMARY,
                icon=E("q_chest"),
                footer_label="Emoji Vault",
            ))

    @emojivault.command(name="set", description="Make this server the emoji vault target.")
    @commands.has_permissions(manage_emojis_and_stickers=True)
    async def emojivault_set(self, ctx: commands.Context):
        source_guild_id = os.getenv("EMOJI_SOURCE_GUILD_ID", "").strip()
        if source_guild_id and source_guild_id.isdigit() and int(source_guild_id) == ctx.guild.id:
            await ctx.send(embed=embeds.error(
                "Can't Use This Server",
                "This server hosts the bot's own UI icon set — the emoji everything from "
                "embeds to buttons pulls its icons from. Using it as the vault too risks "
                "the vault's replace/dedupe logic overwriting or deleting one of those "
                "icons, which breaks the bot's own interface. Pick a different server.",
            ), ephemeral=True)
            return
        emoji_vault_db.set_vault_guild(ctx.guild.id, ctx.author.id, int(time.time()))
        await ctx.send(embed=embeds.success(
            "Emoji Vault Set",
            f"**{ctx.guild.name}** is now the vault. Send a message containing custom "
            "emoji anywhere I can read it — from any server — and anyone here with "
            "**Manage Expressions** can copy them in just by sending them in chat.",
        ))

    @emojivault.command(name="clear", description="Unset the emoji vault (must be run in the current vault server).")
    @commands.has_permissions(manage_emojis_and_stickers=True)
    async def emojivault_clear(self, ctx: commands.Context):
        vault_id = emoji_vault_db.get_vault_guild_id()
        if vault_id is None:
            await ctx.send(embed=embeds.error("Nothing To Clear", "No vault is configured."), ephemeral=True)
            return
        if ctx.guild.id != vault_id:
            await ctx.send(embed=embeds.error(
                "Wrong Server",
                "You can only clear the vault from inside the server that's currently set as the vault.",
            ), ephemeral=True)
            return
        emoji_vault_db.clear_vault_guild()
        await ctx.send(embed=embeds.success("Emoji Vault Cleared", "This server is no longer the vault."))

    # ---------------------------------------------------------------
    # Passive trigger — just send emoji in a message
    # ---------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        vault_id = emoji_vault_db.get_vault_guild_id()
        if vault_id is None:
            return

        matches = EMOJI_RE.findall(message.content)
        if not matches:
            return

        vault_guild = self.bot.get_guild(vault_id)
        if vault_guild is None:
            return

        # Belt-and-suspenders: never touch the bot's own icon-registry guild
        # here either, even if it somehow got saved as the vault before the
        # /emojivault set guard existed.
        source_guild_id = os.getenv("EMOJI_SOURCE_GUILD_ID", "").strip()
        if source_guild_id and source_guild_id.isdigit() and int(source_guild_id) == vault_guild.id:
            return

        # Permission gate: the sender needs Manage Expressions *in the vault
        # server specifically* — regardless of which server the message was
        # actually sent in, since the whole point is grabbing emoji from
        # anywhere. Silent no-op for anyone who doesn't qualify, so this
        # doesn't spam random channels the bot happens to share with people.
        member = vault_guild.get_member(message.author.id)
        if member is None:
            try:
                member = await vault_guild.fetch_member(message.author.id)
            except (discord.NotFound, discord.HTTPException):
                return
        if not member.guild_permissions.manage_emojis_and_stickers:
            return

        # Dedupe by ID, preserve order, cap at 50 per message.
        seen_ids = set()
        candidates = []
        for animated_flag, name, emoji_id in matches:
            if emoji_id in seen_ids:
                continue
            seen_ids.add(emoji_id)
            candidates.append((bool(animated_flag), name, int(emoji_id)))
            if len(candidates) >= MAX_PER_MESSAGE:
                break

        # Fetch every candidate's image up front, since the next step needs
        # the actual bytes to dedupe by picture (not just by ID) — picking
        # the same emoji twice via Discord's picker can hand back two
        # different IDs/names if it was separately re-uploaded to more than
        # one server, so an ID-only dedupe would miss that.
        fetched = []  # (animated, name, image_bytes)
        fetch_failures = []
        for idx, (animated, name, emoji_id) in enumerate(candidates):
            ext = "gif" if animated else "png"
            cdn_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
            image_bytes = None
            for attempt in range(3):
                try:
                    image_bytes = await self.bot.http.get_from_cdn(cdn_url)
                    break
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(0.8 * (attempt + 1))
            if image_bytes is None:
                fetch_failures.append(f"`{name}` — couldn't fetch its image")
                continue
            fetched.append((animated, name, image_bytes))
            if idx < len(candidates) - 1:
                await asyncio.sleep(CDN_FETCH_DELAY_SECONDS)

        seen_hashes = set()
        deduped = []
        duplicate_images = 0
        for animated, name, image_bytes in fetched:
            digest = hashlib.sha256(image_bytes).hexdigest()
            if digest in seen_hashes:
                duplicate_images += 1
                continue
            seen_hashes.add(digest)
            deduped.append((animated, name, image_bytes))

        # Snapshot the vault's current emoji *before* any changes, so
        # positions stay stable for the rest of this run. Static and
        # animated are tracked as two SEPARATE positional queues — Discord
        # gives each kind its own slot pool, so a new animated emoji must
        # replace an existing *animated* one to actually free the right
        # kind of slot; matching purely by overall position could delete a
        # static emoji while trying to make room for an animated one,
        # which frees nothing useful and produces a false "slots full".
        existing_static = [e for e in vault_guild.emojis if not e.animated]
        existing_animated = [e for e in vault_guild.emojis if e.animated]
        static_idx, animated_idx = 0, 0

        replaced, added, failed = 0, 0, 0
        slots_full = set()
        fail_reasons = list(fetch_failures)

        for i, (animated, name, image_bytes) in enumerate(deduped):
            kind = "animated" if animated else "static"
            if animated:
                pool, idx = existing_animated, animated_idx
                animated_idx += 1
            else:
                pool, idx = existing_static, static_idx
                static_idx += 1

            is_replace = idx < len(pool)
            target = pool[idx] if is_replace else None
            target_name = target.name if is_replace else name

            if kind in slots_full:
                failed += 1
                fail_reasons.append(f"`{target_name}` — no {kind} slots left in the vault")
                continue

            # Create the replacement *before* touching the old emoji. If
            # this fails (slots full, bad image, whatever), the existing
            # emoji is never touched and nothing is lost — versus
            # deleting first, which risks leaving an approved name
            # missing entirely if the create step then fails for any
            # reason.
            try:
                await vault_guild.create_custom_emoji(
                    name=target_name,
                    image=image_bytes,
                    reason=f"Emoji vault — {'replaced by' if is_replace else 'added by'} {message.author} ({message.author.id})",
                )
            except discord.HTTPException as exc:
                failed += 1
                text = str(exc).lower()
                if "maximum number of emojis" in text or getattr(exc, "code", None) == 30008:
                    slots_full.add(kind)
                    fail_reasons.append(f"`{target_name}` — no {kind} slots left in the vault")
                else:
                    fail_reasons.append(f"`{target_name}` — {exc}")
                continue

            if is_replace:
                try:
                    await target.delete(reason=f"Emoji vault — old picture removed, requested by {message.author} ({message.author.id})")
                except (discord.NotFound, discord.HTTPException):
                    pass  # cosmetic only — the new one under the same name is already live
                replaced += 1
            else:
                added += 1

            if i < len(deduped) - 1:
                await asyncio.sleep(UPLOAD_DELAY_SECONDS)

        desc = (
            f"**Found:** {len(candidates)} unique emoji"
            + (f" ({duplicate_images} duplicate image(s) skipped)" if duplicate_images else "")
            + f"\n**Replaced (kept old name, new picture):** {replaced}"
            + f"\n**Added new:** {added}"
            + f"\n**Failed:** {failed}"
        )
        if fail_reasons:
            reasons_text = "\n".join(fail_reasons[:10])
            if len(fail_reasons) > 10:
                reasons_text += f"\n…and {len(fail_reasons) - 10} more"
            desc += f"\n\n**Details:**\n{reasons_text}"

        color = embeds.Color.SUCCESS if failed == 0 else (embeds.Color.WARNING if (replaced or added) else embeds.Color.ERROR)
        embed = embeds.premium(
            E("q_chest") + " Emoji Vault",
            desc,
            color,
            icon=E("q_chest"),
            footer_label="Emoji Vault",
        )
        try:
            await message.reply(embed=embed, mention_author=False)
        except (discord.Forbidden, discord.HTTPException):
            try:
                await message.channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass


async def setup(bot):
    emoji_vault_db.setup_database()
    await bot.add_cog(EmojiVault(bot))

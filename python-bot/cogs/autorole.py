# Credits: gogeta_gg
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands


DB_NAME = "autorole.db"


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autorole_settings (
            guild_id INTEGER PRIMARY KEY,
            role_id INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_role_id(guild_id: int):
    conn = connect()
    row = conn.execute(
        "SELECT role_id FROM autorole_settings WHERE guild_id = ?",
        (guild_id,),
    ).fetchone()
    conn.close()
    return int(row["role_id"]) if row else None


def set_role_id(guild_id: int, role_id: int):
    conn = connect()
    conn.execute(
        """
        INSERT INTO autorole_settings (guild_id, role_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET role_id = excluded.role_id
        """,
        (guild_id, role_id),
    )
    conn.commit()
    conn.close()


def clear_role_id(guild_id: int):
    conn = connect()
    conn.execute("DELETE FROM autorole_settings WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()


class AutoRole(commands.Cog):
    """Automatically gives configured members a role when they join."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        setup_database()

    @commands.hybrid_command(
        name="autorole",
        description="Set, view, or disable the role automatically given to new members.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        role="Role to automatically give new human members. Leave empty to view the current setting."
    )
    async def autorole(self, ctx: commands.Context, role: discord.Role = None):
        guild = ctx.guild
        if guild is None:
            return

        if role is None:
            role_id = get_role_id(guild.id)
            if role_id is None:
                await ctx.send(
                    "AutoRole is currently **disabled**. Set it with `/autorole @role`.",
                    ephemeral=True,
                )
                return

            current = guild.get_role(role_id)
            if current is None:
                await ctx.send(
                    "AutoRole is configured to a role that no longer exists. "
                    "Set a new role with `/autorole @role` or disable it with `$autorole_off`.",
                    ephemeral=True,
                )
                return

            await ctx.send(f"AutoRole is currently set to {current.mention}.", ephemeral=True)
            return

        if role.is_default():
            await ctx.send("You can't use `@everyone` as the AutoRole.", ephemeral=True)
            return

        if role.managed:
            await ctx.send("That role is managed by an integration and can't be assigned by the bot.", ephemeral=True)
            return

        me = guild.me
        if me is None:
            await ctx.send("I couldn't resolve my member record in this server. Please try again.", ephemeral=True)
            return

        if role >= me.top_role:
            await ctx.send(
                f"I can't assign {role.mention}. My highest role must be **above** that role.",
                ephemeral=True,
            )
            return

        if not me.guild_permissions.manage_roles:
            await ctx.send("I need the **Manage Roles** permission to use AutoRole.", ephemeral=True)
            return

        set_role_id(guild.id, role.id)
        await ctx.send(
            f"AutoRole enabled: new human members will automatically receive {role.mention}.",
            ephemeral=True,
        )

    @commands.hybrid_command(
        name="autorole_off",
        description="Disable automatic role assignment for new members.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def autorole_off(self, ctx: commands.Context):
        clear_role_id(ctx.guild.id)
        await ctx.send("AutoRole has been **disabled**.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # "People" means human members; don't automatically assign the role to bots.
        if member.bot:
            return

        role_id = get_role_id(member.guild.id)
        if role_id is None:
            return

        role = member.guild.get_role(role_id)
        if role is None:
            # Leave the setting intact so an admin can replace it with /autorole.
            return

        me = member.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return
        if role.is_default() or role.managed or role >= me.top_role:
            return

        try:
            if role not in member.roles:
                await member.add_roles(role, reason="AutoRole: automatic role assignment on member join")
        except (discord.Forbidden, discord.HTTPException):
            # A failed assignment should never break the rest of the bot's join handlers.
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))

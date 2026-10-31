# Credits: gogeta_gg
import discord
from discord.ext import commands
from discord import app_commands
import sqlite3, asyncio, os
from datetime import datetime, timezone

DB_PATH = os.getenv('SERVER_LOG_DB', 'cogs/server_logs.db')

class ServerLogs(commands.Cog):
    """Centralized, zero-category configuration server logging."""
    def __init__(self, bot):
        self.bot = bot
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute('CREATE TABLE IF NOT EXISTS server_logs (guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)')
        self.db.commit()
        self._locks = {}

    def cog_unload(self):
        self.db.close()

    def get_channel_id(self, guild_id):
        row = self.db.execute('SELECT channel_id FROM server_logs WHERE guild_id=?', (guild_id,)).fetchone()
        return row[0] if row else None

    def set_channel_id(self, guild_id, channel_id):
        self.db.execute('INSERT INTO server_logs(guild_id,channel_id) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id', (guild_id, channel_id))
        self.db.commit()

    def remove_config(self, guild_id):
        self.db.execute('DELETE FROM server_logs WHERE guild_id=?', (guild_id,))
        self.db.commit()

    def stamp(self):
        return discord.utils.format_dt(datetime.now(timezone.utc), 'F')

    def avatar(self, user):
        return user.display_avatar.url if user and getattr(user, 'display_avatar', None) else None

    def make_embed(self, title, description, *, thumbnail=None, guild=None, footer='Gogeta Logs • Centralized server activity'):
        e = discord.Embed(title=f'✦ {title}', description=description, timestamp=datetime.now(timezone.utc))
        if thumbnail:
            e.set_thumbnail(url=thumbnail)
        elif guild and guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        e.set_footer(text=footer)
        return e

    async def send_log(self, guild, embed):
        if not guild: return
        cid = self.get_channel_id(guild.id)
        if not cid: return
        channel = guild.get_channel(cid)
        if channel is None:
            try: channel = await self.bot.fetch_channel(cid)
            except Exception: return
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            print(f'[ServerLogs] send failed: {exc}')

    @app_commands.command(name='log', description='Set one channel for comprehensive premium server logging')
    @app_commands.describe(channel='Channel where all server logs will be sent')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.set_channel_id(interaction.guild_id, channel.id)
        embed = self.make_embed(
            'SERVER LOGGING ENABLED',
            f'**Centralized logging is now active.**\n\n📍 **Log Channel**\n{channel.mention}\n\nThe bot will automatically track member activity, messages, moderation-related changes, roles, channels, voice activity and server updates where Discord provides the event data.',
            guild=interaction.guild,
            footer='Gogeta Logs • One channel. Everything important.'
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.send_log(interaction.guild, self.make_embed('LOGGING ONLINE', f'Premium centralized logging is now active in {channel.mention}.', guild=interaction.guild))

    @app_commands.command(name='logoff', description='Disable centralized server logging')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logoff(self, interaction: discord.Interaction):
        self.remove_config(interaction.guild_id)
        await interaction.response.send_message('✦ Server logging has been disabled.', ephemeral=True)

    @app_commands.command(name='logstatus', description='View the current logging status')
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logstatus(self, interaction: discord.Interaction):
        cid = self.get_channel_id(interaction.guild_id)
        text = f'🟢 **Active**\nLogging to <#{cid}>' if cid else '🔴 **Disabled**\nUse `/log` and choose a channel to enable centralized logging.'
        await interaction.response.send_message(embed=self.make_embed('SERVER LOG STATUS', text, guild=interaction.guild), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        age = discord.utils.format_dt(member.created_at, 'R')
        await self.send_log(member.guild, self.make_embed('MEMBER JOINED', f'**{member.mention}** joined the server.\n`ID` • `{member.id}`\n`Account created` • {age}', thumbnail=self.avatar(member)))

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.send_log(member.guild, self.make_embed('MEMBER LEFT', f'**{member}** left the server.\n`ID` • `{member.id}`', thumbnail=self.avatar(member)))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.display_name != after.display_name:
            desc=f'**{after.mention}** changed their display name.\n`Before` • {before.display_name}\n`After` • {after.display_name}'
            await self.send_log(after.guild, self.make_embed('MEMBER UPDATED', desc, thumbnail=self.avatar(after)))
        added=set(after.roles)-set(before.roles); removed=set(before.roles)-set(after.roles)
        if added or removed:
            parts=[]
            if added: parts.append('**Added** • '+', '.join(r.mention for r in added))
            if removed: parts.append('**Removed** • '+', '.join(r.mention for r in removed))
            await self.send_log(after.guild, self.make_embed('MEMBER ROLES UPDATED', f'**{after.mention}**\n'+'\n'.join(parts), thumbnail=self.avatar(after)))

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot: return
        content=(message.content or '*No text content*')[:900]
        jump='Unavailable (message deleted)'
        desc=f'**Author** • {message.author.mention}\n**Channel** • {message.channel.mention}\n\n**Content**\n```{content}```'
        await self.send_log(message.guild, self.make_embed('MESSAGE DELETED', desc, thumbnail=self.avatar(message.author)))

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages: return
        m=next(iter(messages)); guild=m.guild
        await self.send_log(guild, self.make_embed('BULK MESSAGES DELETED', f'**{len(messages)} messages** were deleted in {m.channel.mention}.', guild=guild))

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not after.guild or after.author.bot or before.content == after.content: return
        b=(before.content or '*empty*')[:700]; a=(after.content or '*empty*')[:700]
        desc=f'**Author** • {after.author.mention}\n**Channel** • {after.channel.mention}\n[Jump to message]({after.jump_url})\n\n**Before**\n```{b}```\n**After**\n```{a}```'
        await self.send_log(after.guild, self.make_embed('MESSAGE EDITED', desc, thumbnail=self.avatar(after.author)))

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.send_log(channel.guild, self.make_embed('CHANNEL CREATED', f'**{channel.name}** was created.\nType • `{channel.type}`\nID • `{channel.id}`', guild=channel.guild))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.send_log(channel.guild, self.make_embed('CHANNEL DELETED', f'**{channel.name}** was deleted.\nType • `{channel.type}`\nID • `{channel.id}`', guild=channel.guild))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.name != after.name:
            await self.send_log(after.guild, self.make_embed('CHANNEL UPDATED', f'`{before.name}` → **{after.name}**\nChannel • {after.mention}', guild=after.guild))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.send_log(role.guild, self.make_embed('ROLE CREATED', f'**{role.name}**\nID • `{role.id}`', guild=role.guild))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.send_log(role.guild, self.make_embed('ROLE DELETED', f'**{role.name}**\nID • `{role.id}`', guild=role.guild))

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes=[]
        if before.name != after.name: changes.append(f'Name: `{before.name}` → `{after.name}`')
        if before.permissions != after.permissions: changes.append('Permissions were changed.')
        if changes: await self.send_log(after.guild, self.make_embed('ROLE UPDATED', f'**{after.name}**\n'+'\n'.join(changes), guild=after.guild))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel and before.self_mute == after.self_mute and before.self_deaf == after.self_deaf: return
        if before.channel != after.channel:
            if before.channel is None: action=f'joined {after.channel.mention}'
            elif after.channel is None: action=f'left {before.channel.mention}'
            else: action=f'moved from {before.channel.mention} to {after.channel.mention}'
            await self.send_log(member.guild, self.make_embed('VOICE ACTIVITY', f'**{member.mention}** {action}.', thumbnail=self.avatar(member)))

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes=[]
        if before.name != after.name: changes.append(f'Name: `{before.name}` → `{after.name}`')
        if before.description != after.description: changes.append('Server description changed.')
        if changes: await self.send_log(after, self.make_embed('SERVER UPDATED', '\n'.join(changes), guild=after))

async def setup(bot):
    await bot.add_cog(ServerLogs(bot))

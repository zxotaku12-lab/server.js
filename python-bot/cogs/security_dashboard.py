# Credits: gogeta_gg
"""Premium Discord-native Security Center hub.

This is intentionally not a web dashboard. It renders the same heavy security
language used by Anti-Nuke, Anti-Betray and AutoMod inside Discord.
"""
from __future__ import annotations
from ui.emoji import E
import time
import discord
from discord import app_commands
from discord.ext import commands
from . import antibetray_db
from .security_ui import AdminView, security_embed, state
from ui import embeds as ui
from ui.theme import Color


def admin(i):return bool(i.guild and isinstance(i.user,discord.Member) and i.user.guild_permissions.administrator)
def admin_ctx(ctx):return bool(ctx.guild and isinstance(ctx.author,discord.Member) and ctx.author.guild_permissions.administrator)

def recent(rows):return sum(1 for r in rows if r['timestamp']>=int(time.time())-86400)

class CenterView(AdminView):
 def __init__(self,bot,guild,author_id):super().__init__(author_id,timeout=300);self.bot=bot;self.guild=guild;self.build()
 def build(self):
  self.clear_items()
  for label,emoji,callback in (("Anti-Nuke",E('q_shield'),self.antinuke),("Anti-Betray",E('q_lock'),self.antibetray),("AutoMod",E('q_bot'),self.automod),("Refresh",E('q_sync'),self.refresh)):
   b=discord.ui.Button(label=label,emoji=emoji,style=discord.ButtonStyle.primary if label!='Refresh' else discord.ButtonStyle.secondary);b.callback=callback;self.add_item(b)
 async def refresh(self,i):await i.response.edit_message(embed=self.hub(),view=self)
 async def antinuke(self,i):
  cog=self.bot.get_cog('Antinuke')
  if cog:await i.response.edit_message(embed=__import__('cogs.antinuke',fromlist=['panel_embed']).panel_embed(self.guild,cog),view=CenterBackView(self))
  else:await i.response.edit_message(embed=security_embed('ANTI-NUKE','Anti-Nuke Cog is not loaded.',Color.ERROR,icon=E('q_shield')),view=CenterBackView(self))
 async def antibetray(self,i):
  cog=self.bot.get_cog('Antibetray')
  if cog:await i.response.edit_message(embed=__import__('cogs.antibetray',fromlist=['panel_embed']).panel_embed(self.guild,cog),view=CenterBackView(self))
  else:await i.response.edit_message(embed=security_embed('ANTI-BETRAY','Trust Guard Cog is not loaded.',Color.ERROR,icon=E('q_lock')),view=CenterBackView(self))
 async def automod(self,i):
  cog=self.bot.get_cog('Automod')
  if cog:await i.response.edit_message(embed=__import__('cogs.automod',fromlist=['panel_embed']).panel_embed(self.guild,cog),view=CenterBackView(self))
  else:await i.response.edit_message(embed=security_embed('AUTOMOD','AutoMod Cog is not loaded.',Color.ERROR,icon=E('q_bot')),view=CenterBackView(self))
 def hub(self):
  g = self.guild
  an_cog = self.bot.get_cog('Antinuke')
  ab_cog = self.bot.get_cog('Antibetray')
  am_cog = self.bot.get_cog('Automod')
  e = security_embed('GOGETA // SECURITY COMMAND CENTER', f"**Live protection overview** for **{g.name}**\n\nSelect a security core below to open its dedicated control surface.", Color.SECURITY, icon=E('q_shield'))

  # Read current runtime cogs, not the legacy compatibility tables. If a cog
  # failed to load, report that honestly rather than presenting stale state.
  if an_cog:
   try:
    an = an_cog.settings(g.id)
    an_rules = an_cog.rules(g.id)
    an_value = state(bool(an.get('enabled'))) + f"\n`{sum(bool(r.get('enabled')) for r in an_rules.values())}/{len(an_rules)} rules armed`"
    an_incidents = recent(an_cog.db.incidents(g.id, 100))
   except Exception as exc:
    print(f"[SecurityDashboard] Anti-Nuke status read failed: {type(exc).__name__}")
    an_value, an_incidents = '⚠️ STATUS ERROR', None
  else:
   an_value = '⚠️ NOT LOADED\n`Status unavailable`'
   an_incidents = None

  if ab_cog:
   try:
    ab = ab_cog.settings(g.id)
    ab_armed = sum(bool(antibetray_db.get_rule(g.id, category).get('enabled')) for category in antibetray_db.CATEGORIES)
    ab_value = state(bool(ab.get('enabled'))) + f"\n`{ab_armed}/{len(antibetray_db.CATEGORIES)} rules armed`"
    ab_incidents = recent(antibetray_db.get_incidents(g.id, 100))
   except Exception as exc:
    print(f"[SecurityDashboard] Anti-Betray status read failed: {type(exc).__name__}")
    ab_value, ab_incidents = '⚠️ STATUS ERROR', None
  else:
   ab_value = '⚠️ NOT LOADED\n`Status unavailable`'
   ab_incidents = None

  if am_cog:
   try:
    am = am_cog.settings(g.id)
    am_rules = am_cog.rules(g.id)
    am_value = state(bool(am.get('enabled'))) + f"\n`{sum(bool(r.get('enabled')) for r in am_rules.values())}/{len(am_rules)} rules armed`"
    am_incidents = recent(am_cog.db.incidents(g.id, 100))
   except Exception as exc:
    print(f"[SecurityDashboard] AutoMod status read failed: {type(exc).__name__}")
    am_value, am_incidents = '⚠️ STATUS ERROR', None
  else:
   am_value = '⚠️ NOT LOADED\n`Status unavailable`'
   am_incidents = None

  e.add_field(name='ANTI-NUKE', value=an_value, inline=True)
  e.add_field(name='ANTI-BETRAY', value=ab_value, inline=True)
  e.add_field(name='AUTOMOD', value=am_value, inline=True)
  def incident_line(emoji, count, label):
   return f"{emoji} `{count}` {label}" if count is not None else f"{emoji} `N/A` {label} (unavailable)"
  e.add_field(name='THREAT ACTIVITY • 24H', value='\n'.join((
   incident_line(E('q_shield'), an_incidents, 'firewall events'),
   incident_line(E('q_lock'), ab_incidents, 'trust incidents'),
   incident_line(E('q_bot'), am_incidents, 'AutoMod incidents'),
  )), inline=False)
  return e

class CenterBackView(AdminView):
 def __init__(self,parent):super().__init__(parent.author_id,timeout=300);self.parent=parent
 @discord.ui.button(label='Back to Security Center',style=discord.ButtonStyle.secondary)
 async def back(self,i,b):await i.response.edit_message(embed=self.parent.hub(),view=self.parent)

class SecurityDashboard(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @commands.hybrid_command(name='security-center',description="Open Gogeta's premium Discord security command center.")
 async def security_center(self,ctx:commands.Context):
  if not admin_ctx(ctx):await ctx.send(embed=ui.permission_denied(),ephemeral=True);return
  view=CenterView(self.bot,ctx.guild,ctx.author.id);await ctx.send(embed=view.hub(),view=view,ephemeral=True)
 @commands.hybrid_command(name='security-status',description='Show a compact live security status.')
 async def status(self,ctx:commands.Context):
  if not admin_ctx(ctx):await ctx.send(embed=ui.permission_denied(),ephemeral=True);return
  g = ctx.guild
  an_cog = self.bot.get_cog('Antinuke')
  ab_cog = self.bot.get_cog('Antibetray')
  am_cog = self.bot.get_cog('Automod')
  e = security_embed('SECURITY STATUS', f"Live state for **{g.name}**", Color.SECURITY, icon=E('q_shield'))
  def live_state(cog, guild_id):
   if cog is None:
    return '⚠️ NOT LOADED'
   try:
    return state(bool(cog.settings(guild_id).get('enabled')))
   except Exception:
    return '⚠️ STATUS ERROR'
  e.add_field(name='Anti-Nuke', value=live_state(an_cog, g.id), inline=True)
  e.add_field(name='Anti-Betray', value=live_state(ab_cog, g.id), inline=True)
  e.add_field(name='AutoMod', value=live_state(am_cog, g.id), inline=True)
  me=g.me;e.add_field(name='Audit Log',value=E('q_online') + ' Available' if me and me.guild_permissions.view_audit_log else E('q_offline') + ' Missing',inline=True);e.add_field(name='Bot Role',value=f"`{me.top_role.position}`" if me else '`Unknown`',inline=True)
  await ctx.send(embed=e,view=CenterView(self.bot,g,ctx.author.id),ephemeral=True)
 @commands.hybrid_command(name='security-check',description='Run a permissions and hierarchy diagnostic.')
 async def check(self,ctx:commands.Context):
  if not admin_ctx(ctx):await ctx.send(embed=ui.permission_denied(),ephemeral=True);return
  g=ctx.guild;me=g.me;names=('view_audit_log','manage_roles','manage_channels','manage_webhooks','ban_members','kick_members','moderate_members','manage_messages')
  lines=[f"{E('q_online') if getattr(me.guild_permissions,n,False) else E('q_offline')} **{n.replace('_',' ').title()}**" for n in names]
  above=[r for r in g.roles if r>me.top_role and not r.is_default()] if me else []
  e=security_embed('SECURITY // PREFLIGHT DIAGNOSTICS','The bot can only protect and contain actors below its highest role.',Color.WARNING if above else Color.SECURITY,icon=E('q_audit'))
  e.add_field(name='PERMISSIONS',value='\n'.join(lines),inline=False)
  e.add_field(name='ROLE HIERARCHY',value=(f"{E('q_offline')} `{len(above)}` roles are above the bot. Move the bot role higher." if above else E('q_online') + ' Bot role is above all server roles.'),inline=False)
  await ctx.send(embed=e,ephemeral=True)

async def setup(bot):await bot.add_cog(SecurityDashboard(bot))

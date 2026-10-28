// Audit log events are authoritative: never infer an executor from a channel/role event.
const { AuditLogEvent, PermissionFlagsBits } = require('discord.js');
const settings = require('./settings');
const monitored = new Set([
  AuditLogEvent.ChannelDelete, AuditLogEvent.RoleDelete, AuditLogEvent.MemberBanAdd,
  AuditLogEvent.MemberKick, AuditLogEvent.WebhookCreate, AuditLogEvent.BotAdd,
]);
const WINDOW_MS = 60_000;
const seen = new Map();
const buckets = new Map();

async function handle(entry, guild, now = Date.now()) {
  const cfg = settings.get(guild.id);
  if (!cfg.antiNuke || !monitored.has(entry.action) || !entry.id || !entry.executorId) return false;
  // Ignore stale, duplicate and owner/bot actions. Discord may deliver events late.
  if (seen.has(entry.id) || !entry.createdTimestamp || Math.abs(now - entry.createdTimestamp) > WINDOW_MS) return false;
  seen.set(entry.id, now);
  for (const [id, time] of seen) if (now - time > WINDOW_MS) seen.delete(id);
  if (entry.executorId === guild.ownerId || entry.executorId === guild.client.user.id) return false;
  const key = `${guild.id}:${entry.executorId}`;
  for (const [id, bucket] of buckets) if (now - bucket.last > WINDOW_MS) buckets.delete(id);
  const bucket = buckets.get(key) || { times: [], last: now, alerted: false };
  bucket.times = bucket.times.filter(t => now - t < WINDOW_MS);
  if (!bucket.times.length) bucket.alerted = false;
  bucket.times.push(now); bucket.last = now; buckets.set(key, bucket);
  const limit = cfg.antiNukeLimit || 3;
  if (bucket.times.length < limit || bucket.alerted) return false;
  bucket.alerted = true;
  const channel = cfg.logChannelId && guild.channels.cache.get(cfg.logChannelId);
  let response = 'Alert-only mode: koi automatic punishment nahi hui.';
  if (cfg.antiNukeAction === 'strip') {
    try {
      const member = await guild.members.fetch(entry.executorId);
      const me = guild.members.me;
      if (!me?.permissions.has(PermissionFlagsBits.ManageRoles) || member.roles.highest.comparePositionTo(me.roles.highest) >= 0) {
        response = 'Roles remove nahi hue: bot permission ya hierarchy check karein.';
      } else {
        const dangerous = [PermissionFlagsBits.Administrator, PermissionFlagsBits.ManageGuild, PermissionFlagsBits.ManageRoles, PermissionFlagsBits.ManageChannels, PermissionFlagsBits.ManageWebhooks, PermissionFlagsBits.BanMembers, PermissionFlagsBits.KickMembers];
        const roles = member.roles.cache.filter(role => role.id !== guild.id && !role.managed && role.position < me.roles.highest.position && dangerous.some(flag => role.permissions.has(flag, false)));
        if (roles.size) { await member.roles.remove(roles, 'Anti-nuke threshold exceeded'); response = `${roles.size} manageable dangerous roles remove kiye; baaki permissions manually check karein.`; }
        else response = 'Koi removable dangerous role nahi mila; permissions manually check karein.';
      }
    } catch (err) { response = 'Role removal fail hua; bot permissions aur hierarchy check karein.'; console.error('[antinuke] Role removal failed:', err.message); }
  }
  const content = `🚨 Anti-nuke alert: <@${entry.executorId}> ne 60 seconds me ${bucket.times.length} monitored actions kiye. Server owner please audit log check karein. ${response}`;
  if (!channel?.isTextBased?.() || !channel.send) {
    console.warn(`[antinuke] ${guild.id}: alert for ${entry.executorId} but no log channel`);
    return true;
  }
  try { await channel.send({ content, allowedMentions: { parse: [] } }); }
  catch (err) { console.error(`[antinuke] Alert delivery failed for ${guild.id}:`, err.message); }
  return true;
}

function botReady(guild) {
  return !!guild.members.me?.permissions?.has(PermissionFlagsBits.ViewAuditLog);
}
module.exports = { handle, botReady, monitored, WINDOW_MS, _reset: () => { seen.clear(); buckets.clear(); } };

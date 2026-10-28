const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { hasMemberPerm, hasBotPerm } = require('../lib/perms');
const { load, save } = require('../store');
const base = (name, desc, perm) => new SlashCommandBuilder().setName(name).setDescription(desc).setDMPermission(false).setDefaultMemberPermissions(perm);
const deny = (i, text) => i.reply({ content: text, ephemeral: true });
const gate = (i, perm) => i.guild && i.guild.members.me && hasMemberPerm(i, perm) && hasBotPerm(i, perm);
const userOption = o => o.setName('user').setDescription('Target member').setRequired(true);
const reasonOption = o => o.setName('reason').setDescription('Reason').setMaxLength(300);
const reason = i => `${i.user.id}: ${i.options.getString('reason') || 'No reason provided'}`;
async function target(i) {
  const user = i.options.getUser('user');
  const member = await i.guild.members.fetch(user.id).catch(() => null);
  if (!member || member.id === i.guild.ownerId || member.id === i.user.id || member.id === i.client.user.id) return null;
  if (i.user.id !== i.guild.ownerId && (!i.member?.roles?.highest || member.roles.highest.comparePositionTo(i.member.roles.highest) >= 0)) return null;
  if (member.roles.highest.comparePositionTo(i.guild.members.me.roles.highest) >= 0) return null;
  return member;
}
const warnings = () => load('warnings', {});
module.exports = [
  { guildOnly: true, data: base('unban', 'Ban hatao by user ID', PermissionFlagsBits.BanMembers)
    .addStringOption(o => o.setName('user-id').setDescription('Banned user ID').setRequired(true).setMinLength(17).setMaxLength(20)).addStringOption(reasonOption),
    async execute(i) {
      if (!gate(i, PermissionFlagsBits.BanMembers)) return deny(i, 'Gateway bot aur Ban Members permission chahiye.');
      const id = i.options.getString('user-id'); if (!/^\d{17,20}$/.test(id)) return deny(i, 'Valid Discord user ID do.');
      await i.guild.members.unban(id, reason(i)); return deny(i, `✅ Ban hata diya: ${id}`);
    } },
  { guildOnly: true, data: base('slowmode', 'Current channel ka slowmode set karo', PermissionFlagsBits.ManageChannels)
    .addIntegerOption(o => o.setName('seconds').setDescription('0 se 21600 seconds').setRequired(true).setMinValue(0).setMaxValue(21600)),
    async execute(i) {
      if (!gate(i, PermissionFlagsBits.ManageChannels)) return deny(i, 'Gateway bot aur Manage Channels permission chahiye.');
      if (!i.channel?.setRateLimitPerUser) return deny(i, 'Is channel me slowmode available nahi hai.');
      const seconds = i.options.getInteger('seconds'); await i.channel.setRateLimitPerUser(seconds, `Requested by ${i.user.id}`);
      return deny(i, `✅ Slowmode ${seconds} seconds set hua.`);
    } },
  { guildOnly: true, data: base('nickname', 'Member ka nickname set ya reset karo', PermissionFlagsBits.ManageNicknames)
    .addUserOption(userOption).addStringOption(o => o.setName('name').setDescription('Khaali rakho to reset').setMaxLength(32)),
    async execute(i) {
      if (!gate(i, PermissionFlagsBits.ManageNicknames)) return deny(i, 'Gateway bot aur Manage Nicknames permission chahiye.');
      const member = await target(i); if (!member || !member.manageable) return deny(i, 'Member nahi mila ya hierarchy ke kaaran action allowed nahi hai.');
      await member.setNickname(i.options.getString('name') || null, `Requested by ${i.user.id}`); return deny(i, '✅ Nickname update hua.');
    } },
  { guildOnly: true, data: base('warn', 'Member ko warning do', PermissionFlagsBits.ModerateMembers)
    .addUserOption(userOption).addStringOption(o => o.setName('reason').setDescription('Warning reason').setRequired(true).setMaxLength(300)),
    async execute(i) {
      if (!gate(i, PermissionFlagsBits.ModerateMembers)) return deny(i, 'Gateway bot aur Moderate Members permission chahiye.');
      const member = await target(i); if (!member) return deny(i, 'Member nahi mila ya hierarchy ke kaaran warning allowed nahi hai.');
      const data = warnings(), key = `${i.guild.id}:${member.id}`; data[key] ||= [];
      const id = require('crypto').randomBytes(6).toString('hex'); data[key].push({ id, reason: i.options.getString('reason'), moderator: i.user.id, time: Date.now() }); save('warnings', data);
      return deny(i, `✅ Warning saved. ID: ${id}`);
    } },
  { guildOnly: true, data: base('warnings', 'Member ki warnings dekho', PermissionFlagsBits.ModerateMembers).addUserOption(userOption),
    async execute(i) {
      if (!gate(i, PermissionFlagsBits.ModerateMembers)) return deny(i, 'Gateway bot aur Moderate Members permission chahiye.');
      const user = i.options.getUser('user'), list = warnings()[`${i.guild.id}:${user.id}`] || [];
      const lines = list.slice(-10).map(w => `• \`${w.id}\` — ${w.reason} (<t:${Math.floor(w.time / 1000)}:d>)`);
      return i.reply({ content: `Warnings for ${user.id}: ${list.length}\n${lines.join('\n').slice(0, 1800) || 'Koi warning nahi.'}`, ephemeral: true, allowedMentions: { parse: [] } });
    } },
  { guildOnly: true, data: base('unwarn', 'Warning ID se warning delete karo', PermissionFlagsBits.ModerateMembers)
    .addUserOption(userOption).addStringOption(o => o.setName('id').setDescription('Warning ID').setRequired(true).setMaxLength(20)),
    async execute(i) {
      if (!gate(i, PermissionFlagsBits.ModerateMembers)) return deny(i, 'Gateway bot aur Moderate Members permission chahiye.');
      const member = await target(i); if (!member) return deny(i, 'Member nahi mila ya hierarchy ke kaaran action allowed nahi hai.');
      const data = warnings(), key = `${i.guild.id}:${member.id}`, entries = data[key] || [], id = i.options.getString('id');
      const filtered = entries.filter(w => w.id !== id); if (filtered.length === entries.length) return deny(i, 'Warning ID nahi mili.');
      data[key] = filtered; save('warnings', data); return deny(i, '✅ Warning delete ho gayi.');
    } },
];

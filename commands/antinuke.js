const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const settings = require('../lib/settings');
const anti = require('../lib/antinuke');
module.exports = {
  guildOnly: true,
  data: new SlashCommandBuilder().setName('antinuke').setDescription('Anti-nuke alerts configure karo (server owner only)')
    .setDMPermission(false).setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
    .addSubcommand(s => s.setName('on').setDescription('Anti-nuke alerts on karo')
      .addIntegerOption(o => o.setName('limit').setDescription('60 seconds me actions ki limit (default 3)').setMinValue(2).setMaxValue(20))
      .addStringOption(o => o.setName('action').setDescription('Alert only ya risky roles remove').addChoices({ name: 'Alert only (default)', value: 'alert' }, { name: 'Remove dangerous roles', value: 'strip' })))
    .addSubcommand(s => s.setName('off').setDescription('Anti-nuke alerts off karo'))
    .addSubcommand(s => s.setName('status').setDescription('Anti-nuke status dekho')),
  async execute(i) {
    if (!i.guild || !i.guild.members.me) return i.reply({ content: 'Gateway bot online hona chahiye.', ephemeral: true });
    if (i.user.id !== i.guild.ownerId) return i.reply({ content: 'Sirf server owner anti-nuke configure kar sakta hai.', ephemeral: true });
    const sub = i.options.getSubcommand();
    if (sub === 'off') { settings.set(i.guild.id, { antiNuke: false }); return i.reply({ content: 'Anti-nuke alerts off hain.', ephemeral: true }); }
    const cfg = settings.get(i.guild.id);
    if (sub === 'status') return i.reply({ content: `Anti-nuke alerts: ${cfg.antiNuke ? 'ON' : 'OFF'}; limit: ${cfg.antiNukeLimit || 3}/60s; log channel: ${cfg.logChannelId ? `<#${cfg.logChannelId}>` : 'set nahi'}; View Audit Log: ${anti.botReady(i.guild) ? 'yes' : 'no'}. Action: ${cfg.antiNukeAction || 'alert'}.`, ephemeral: true, allowedMentions: { parse: [] } });
    if (!anti.botReady(i.guild)) return i.reply({ content: 'Bot ko View Audit Log permission do.', ephemeral: true });
    const channel = cfg.logChannelId && i.guild.channels.cache.get(cfg.logChannelId);
    if (!channel?.isTextBased?.() || !channel.permissionsFor(i.guild.members.me)?.has([PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages])) return i.reply({ content: 'Pehle /setlogs se accessible log channel set karo; bot ko View Channel aur Send Messages chahiye.', ephemeral: true });
    const limit = i.options.getInteger('limit') || 3;
    const action = i.options.getString('action') || 'alert';
    if (action === 'strip' && !i.guild.members.me.permissions.has(PermissionFlagsBits.ManageRoles)) return i.reply({ content: 'Role removal mode ke liye bot ko Manage Roles permission chahiye.', ephemeral: true });
    settings.set(i.guild.id, { antiNuke: true, antiNukeLimit: limit, antiNukeAction: action });
    return i.reply({ content: `Anti-nuke ON: ${limit} actions / 60 seconds; mode: ${action}. Ye actions undo nahi karta; false positives possible hain.`, ephemeral: true });
  },
};

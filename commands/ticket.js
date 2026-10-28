const { SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const { hasMemberPerm } = require('../lib/perms');
const settings = require('../lib/settings');
const tickets = require('../lib/tickets');
module.exports = {
  guildOnly: true,
  data: new SlashCommandBuilder().setName('ticket-panel').setDescription('Private support ticket panel bhejo')
    .setDMPermission(false).setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addRoleOption(o => o.setName('staff').setDescription('Tickets dekhne wala support role'))
    .addChannelOption(o => o.setName('category').setDescription('Tickets ki category').addChannelTypes(ChannelType.GuildCategory)),
  async execute(i) {
    if (!i.guild || !i.guild.members.me || !i.channel?.send) return i.reply({ content: 'Gateway bot online hona chahiye.', ephemeral: true });
    if (!hasMemberPerm(i, PermissionFlagsBits.ManageGuild)) return i.reply({ content: 'Manage Server permission chahiye.', ephemeral: true });
    if (!i.guild.members.me.permissions.has(PermissionFlagsBits.ManageChannels)) return i.reply({ content: 'Bot ko Manage Channels permission do.', ephemeral: true });
    const role = i.options.getRole('staff'), category = i.options.getChannel('category');
    if (role && (role.id === i.guild.id || role.guild.id !== i.guild.id)) return i.reply({ content: '@everyone ko staff role nahi bana sakte.', ephemeral: true });
    if (category && (category.guild.id !== i.guild.id || category.type !== ChannelType.GuildCategory)) return i.reply({ content: 'Valid category select karo.', ephemeral: true });
    await i.deferReply({ ephemeral: true });
    // Panel in all channels uses this server's latest settings.
    settings.set(i.guild.id, { ticketStaffRoleId: role?.id || null, ticketCategoryId: category?.id || null });
    await i.channel.send({ embeds: [{ title: '🎫 Support tickets', description: 'Naya private ticket kholne ke liye button dabao.', color: 0x5865f2 }], components: [tickets.panel()] });
    return i.editReply('✅ Ticket panel bhej diya. Staff role/category badalne ke liye command dobara chalao.');
  },
};

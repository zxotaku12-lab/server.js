const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { hasMemberPerm } = require('../lib/perms');
const giveaways = require('../lib/giveaways');
const base = (name, description) => new SlashCommandBuilder().setName(name).setDescription(description).setDMPermission(false).setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild);
const guard = i => i.guild && i.client?.channels && hasMemberPerm(i, PermissionFlagsBits.ManageGuild);
module.exports = [
  { guildOnly: true, data: base('giveaway-start', 'Giveaway shuru karo')
    .addStringOption(o => o.setName('prize').setDescription('Prize').setRequired(true).setMaxLength(200))
    .addIntegerOption(o => o.setName('minutes').setDescription('Kitne minutes').setRequired(true).setMinValue(1).setMaxValue(43200))
    .addIntegerOption(o => o.setName('winners').setDescription('Winners ki sankhya').setMinValue(1).setMaxValue(20)),
    async execute(i) {
      if (!guard(i) || !i.channel?.send) return i.reply({ content: 'Manage Server permission aur Gateway bot zaroori hai.', ephemeral: true });
      const prize = i.options.getString('prize'), end = Date.now() + i.options.getInteger('minutes') * 60000, winners = i.options.getInteger('winners') || 1;
      const message = await i.channel.send({ content: `🎉 **GIVEAWAY** 🎉\nPrize: **${prize}**\nWinners: ${winners}\nEnds: <t:${Math.floor(end / 1000)}:R>`, components: [giveaways.button()], allowedMentions: { parse: [] } });
      giveaways.create(message, prize, end, winners);
      return i.reply({ content: `✅ Giveaway started: ${message.url}`, ephemeral: true });
    } },
  { guildOnly: true, data: base('giveaway-end', 'Giveaway jaldi khatam karo').addStringOption(o => o.setName('message-id').setDescription('Giveaway message ID').setRequired(true)),
    async execute(i) {
      if (!guard(i)) return i.reply({ content: 'Manage Server permission aur Gateway bot zaroori hai.', ephemeral: true });
      const id = i.options.getString('message-id'), g = giveaways.read()[id];
      if (!g || g.guildId !== i.guildId || g.status !== 'open') return i.reply({ content: 'Open giveaway nahi mila.', ephemeral: true });
      await i.deferReply({ ephemeral: true }); await giveaways.finish(i.client, id); return i.editReply('✅ Giveaway khatam ho gaya.');
    } },
];

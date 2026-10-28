const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { hasMemberPerm } = require('../lib/perms');
const settings = require('../lib/settings');
const { buildWelcome } = require('../lib/welcome');
const data = new SlashCommandBuilder().setName('welcome-embed').setDescription('Welcome embed customize ya preview karo')
  .setDMPermission(false).setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
  .addSubcommand(s => s.setName('set').setDescription('Welcome embed settings badlo')
    .addStringOption(o => o.setName('title').setDescription('Title; placeholders: {user}, {username}, {server}, {count}').setMinLength(1).setMaxLength(256))
    .addStringOption(o => o.setName('description').setDescription('Description; placeholders: {user}, {username}, {server}, {count}').setMinLength(1).setMaxLength(4000))
    .addStringOption(o => o.setName('color').setDescription('Hex colour, jaise #57F287').setMinLength(6).setMaxLength(7))
    .addStringOption(o => o.setName('image').setDescription('HTTPS image URL; none likhne se image hat jayegi').setMaxLength(1000)))
  .addSubcommand(s => s.setName('preview').setDescription('Apna welcome embed preview dekho'))
  .addSubcommand(s => s.setName('reset').setDescription('Welcome embed default par reset karo'));
module.exports = {
  guildOnly: true, data,
  async execute(i) {
    if (!i.guild || !i.member?.user) return i.reply({ content: 'Welcome embed ke liye Gateway bot online hona chahiye.', ephemeral: true });
    if (!hasMemberPerm(i, PermissionFlagsBits.ManageGuild)) return i.reply({ content: 'Manage Server permission chahiye.', ephemeral: true });
    const sub = i.options.getSubcommand();
    if (sub === 'preview') return i.reply({ embeds: [buildWelcome(i.member, settings.get(i.guild.id))], ephemeral: true, allowedMentions: { parse: [] } });
    if (sub === 'reset') {
      settings.unset(i.guild.id, ['welcomeTitle', 'welcomeDescription', 'welcomeColor', 'welcomeImage']);
      return i.reply({ content: '✅ Welcome embed default par reset ho gaya. Welcome channel nahi badla.', ephemeral: true });
    }
    const title = i.options.getString('title'), description = i.options.getString('description');
    const color = i.options.getString('color'), image = i.options.getString('image');
    if (title === null && description === null && color === null && image === null) return i.reply({ content: 'Kam se kam ek setting do.', ephemeral: true });
    const patch = {};
    if (title !== null) patch.welcomeTitle = title;
    if (description !== null) patch.welcomeDescription = description;
    if (color !== null) {
      if (!/^#?[0-9a-f]{6}$/i.test(color)) return i.reply({ content: 'Colour #57F287 jaise 6-digit hex me do.', ephemeral: true });
      patch.welcomeColor = parseInt(color.replace('#', ''), 16);
    }
    if (image !== null) {
      if (image.toLowerCase() === 'none') patch.welcomeImage = null;
      else {
        try { const url = new URL(image); if (url.protocol !== 'https:' || !url.hostname) throw new Error('invalid'); }
        catch { return i.reply({ content: 'Image ke liye valid HTTPS URL do ya none likho.', ephemeral: true }); }
        patch.welcomeImage = image;
      }
    }
    settings.set(i.guild.id, patch);
    return i.reply({ content: '✅ Welcome embed save ho gaya. /welcome-embed preview se dekho; /setwelcome se channel set karo.', ephemeral: true });
  },
};

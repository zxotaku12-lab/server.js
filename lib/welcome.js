const { EmbedBuilder } = require('discord.js');

const DEFAULT_TITLE = '🎉 Welcome!';
const DEFAULT_DESCRIPTION = 'Namaste {user}! **{server}** me swagat hai! 🥳\n\n📜 Rules padho, 👋 intro do, aur maze karo!\n\n👥 Ab hum **{count}** members hain!';
function render(text, member) {
  const values = { user: `<@${member.id}>`, username: member.user.username, server: member.guild.name, count: String(member.guild.memberCount) };
  return text.replace(/\{(user|username|server|count)\}/g, (_, key) => values[key]);
}
function buildWelcome(member, config = {}) {
  const embed = new EmbedBuilder()
    .setTitle(render(config.welcomeTitle || DEFAULT_TITLE, member).slice(0, 256))
    .setDescription(render(config.welcomeDescription || DEFAULT_DESCRIPTION, member).slice(0, 4096))
    .setColor(config.welcomeColor ?? 0x57f287);
  const avatar = member.user.displayAvatarURL?.({ size: 128 });
  if (avatar) embed.setThumbnail(avatar);
  if (config.welcomeImage) embed.setImage(config.welcomeImage);
  return embed;
}
module.exports = { buildWelcome, render, DEFAULT_TITLE, DEFAULT_DESCRIPTION };

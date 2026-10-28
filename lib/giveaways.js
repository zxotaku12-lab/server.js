const { load, save } = require('../store');
const { ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');
const KEY = 'giveaways';
const read = () => load(KEY, {});
const write = data => save(KEY, data);
const button = () => new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('giveaway-enter').setLabel('🎉 Enter giveaway').setStyle(ButtonStyle.Primary));
function create(message, prize, end, winners) {
  const data = read(); data[message.id] = { guildId: message.guildId, channelId: message.channelId, prize, end, winners, entrants: [], status: 'open' }; write(data);
}
async function enter(i) {
  const data = read(), g = data[i.message.id];
  if (!g || g.guildId !== i.guildId || g.status !== 'open' || Date.now() >= g.end) return i.reply({ content: 'Giveaway khatam ho chuka hai.', ephemeral: true });
  if (i.user.bot) return i.reply({ content: 'Bots enter nahi kar sakte.', ephemeral: true });
  const index = g.entrants.indexOf(i.user.id);
  if (index === -1) g.entrants.push(i.user.id); else g.entrants.splice(index, 1);
  write(data);
  return i.reply({ content: index === -1 ? '🎉 Giveaway me entry ho gayi!' : 'Giveaway se entry hata di.', ephemeral: true });
}
async function finish(client, id) {
  const data = read(), g = data[id];
  if (!g || g.status !== 'open') return false;
  // Mark first to prevent concurrent timers from announcing twice.
  g.status = 'ended'; write(data);
  const entrants = [...g.entrants];
  const winners = [];
  while (entrants.length && winners.length < g.winners) winners.push(entrants.splice(require('crypto').randomInt(entrants.length), 1)[0]);
  try {
    const channel = await client.channels.fetch(g.channelId);
    const message = await channel.messages.fetch(id);
    await message.edit({ components: [] });
    await channel.send({ content: winners.length ? `🎉 **${g.prize}** winner: ${winners.map(x => `<@${x}>`).join(', ')}` : `🎉 **${g.prize}**: koi entry nahi thi.`, allowedMentions: { users: winners } });
  } catch (err) { console.error('[giveaway] Announcement failed:', err.message); }
  return true;
}
function startScheduler(client) {
  const run = () => { for (const [id, g] of Object.entries(read())) if (g.status === 'open' && g.end <= Date.now()) finish(client, id); };
  run(); const timer = setInterval(run, 15000); timer.unref(); return timer;
}
module.exports = { button, create, enter, finish, startScheduler, read };

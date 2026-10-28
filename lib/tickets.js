const { ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType, PermissionFlagsBits } = require('discord.js');
const settings = require('./settings');
const opening = new Set();
const panel = () => new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('ticket-open').setLabel('🎫 Ticket kholo').setStyle(ButtonStyle.Primary));
const closeButton = () => new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('ticket-close').setLabel('🔒 Ticket close karo').setStyle(ButtonStyle.Danger));
const ownerFrom = channel => /^ticket-owner:(\d{17,20})$/.exec(channel?.topic || '')?.[1] || null;
async function open(i) {
  const guild = i.guild;
  if (!guild || !guild.members.me?.permissions.has(PermissionFlagsBits.ManageChannels)) return i.reply({ content: 'Bot ko Manage Channels permission chahiye.', ephemeral: true });
  const key = `${guild.id}:${i.user.id}`;
  if (opening.has(key)) return i.reply({ content: 'Tumhara ticket ban raha hai, please wait.', ephemeral: true });
  opening.add(key);
  try {
    await i.deferReply({ ephemeral: true });
    const existing = guild.channels.cache.find(ch => ownerFrom(ch) === i.user.id);
    if (existing) return await i.editReply(`Tumhara ticket pehle se hai: <#${existing.id}>`);
    const cfg = settings.get(guild.id), overwrites = [
      { id: guild.id, deny: [PermissionFlagsBits.ViewChannel] },
      { id: i.user.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory] },
      { id: guild.members.me.id, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.ManageChannels] },
    ];
    if (cfg.ticketStaffRoleId && guild.roles.cache.has(cfg.ticketStaffRoleId)) overwrites.push({ id: cfg.ticketStaffRoleId, allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory] });
    const parent = cfg.ticketCategoryId && guild.channels.cache.get(cfg.ticketCategoryId);
    const channel = await guild.channels.create({ name: `ticket-${i.user.id}`, type: ChannelType.GuildText, parent: parent?.type === ChannelType.GuildCategory ? parent.id : null, topic: `ticket-owner:${i.user.id}`, permissionOverwrites: overwrites, reason: `Ticket opened by ${i.user.id}` });
    try {
      await channel.send({ content: `<@${i.user.id}> 🎫 Apni problem yahan likho. Staff jaldi help karegi.`, components: [closeButton()], allowedMentions: { users: [i.user.id] } });
    } catch (err) {
      // Avoid leaving an inaccessible or unusable orphan channel on setup failure.
      await channel.delete('Ticket setup failed').catch(() => {});
      throw err;
    }
    return await i.editReply(`✅ Ticket khul gaya: <#${channel.id}>`);
  } catch (err) {
    console.error('[tickets] open failed:', err.message);
    if (i.deferred) return i.editReply('❌ Ticket nahi bana. Bot permissions aur channel limits check karo.').catch(() => {});
    if (!i.replied) return i.reply({ content: '❌ Ticket nahi bana.', ephemeral: true }).catch(() => {});
  } finally { opening.delete(key); }
}
async function close(i) {
  const owner = ownerFrom(i.channel);
  if (!i.guild || !owner) return i.reply({ content: 'Ye ticket channel nahi hai.', ephemeral: true });
  const cfg = settings.get(i.guild.id);
  const staff = cfg.ticketStaffRoleId && i.member?.roles?.cache?.has(cfg.ticketStaffRoleId);
  if (i.user.id !== owner && !staff && !i.memberPermissions?.has(PermissionFlagsBits.ManageChannels)) return i.reply({ content: 'Sirf ticket owner ya staff ticket close kar sakte hain.', ephemeral: true });
  await i.deferReply({ ephemeral: true });
  try { await i.channel.delete(`Ticket closed by ${i.user.id}`); }
  catch (err) { console.error('[tickets] close failed:', err.message); await i.editReply('❌ Ticket delete nahi hua. Bot ki Manage Channels permission check karo.').catch(() => {}); }
}
module.exports = { panel, closeButton, ownerFrom, open, close };

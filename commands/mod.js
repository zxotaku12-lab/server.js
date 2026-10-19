/**
 * Moderation commands: /kick /ban /purge /timeout
 * ------------------------------------------------
 * Ye commands Gateway-only hain — inhe asli `guild` object chahiye (roles, permissions,
 * bulkDelete). HTTP interactions mode me `interaction.guild` null hota hai, isliye ye
 * saaf-saaf bata deti hain ki Gateway bot online hona chahiye — chupchap fail nahi hoti.
 *
 * Har command me:
 *   - guildOnly: true          -> DM me clean message
 *   - permission check         -> moderator aur bot dono ki permissions
 *   - role hierarchy check     -> apne se upar waale ko mod nahi kar sakte
 *   - audit log reason         -> "command chalane wala (id): reason"
 *   - log channel entry        -> agar /setlogs se channel set ho (settings me)
 */
const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const settings = require('../lib/settings');
const { hasMemberPerm, hasBotPerm } = require('../lib/perms');

const MAX_TIMEOUT_MINUTES = 40320; // 28 din — Discord ki limit

const GATEWAY_ONLY =
  '⚠️ Moderation commands ke liye **Gateway bot** ka online hona zaroori hai.\n' +
  'Server pe `DISCORD_TOKEN` set karo, ya Developer Portal se **Interactions Endpoint URL** hata do ' +
  '(tab Discord commands Gateway pe bhejega).';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const reply = (interaction, payload) => interaction.reply(payload);
const deny = (interaction, content) => interaction.reply({ content, ephemeral: true });

/** Gateway pe asli guild chahiye — HTTP shim pe null hota hai */
function requireGuild(interaction) {
  if (!interaction.guild) {
    deny(interaction, GATEWAY_ONLY);
    return null;
  }
  return interaction.guild;
}

/** permission checks lib/perms.js se — Gateway aur HTTP dono mode me kaam karte hain */
const hasModPerm = hasMemberPerm;
const botHasPerm = hasBotPerm;

/** Audit log reason me actor ka zikr rakho */
const auditReason = (interaction, reason) =>
  `${interaction.user?.tag ?? interaction.user?.username ?? 'unknown'} (${interaction.user?.id ?? '?'}): ${
    reason || 'koi reason nahi diya'
  }`;

/** Role hierarchy — apne se upar/braabar waale ko mod nahi kar sakte */
function blockedByHierarchy(interaction, target) {
  const me = interaction.guild?.members?.me;
  if (!me || !target?.roles?.highest) return false;
  if (target.id === interaction.guild.ownerId) return true;
  return target.roles.highest.comparePositionTo(me.roles.highest) >= 0;
}

/** settings me set kiya hua log channel (agar ho) */
function logChannelOf(guild) {
  try {
    const cfg = settings.get(guild.id);
    if (!cfg.logChannelId) return null;
    const ch = guild.channels?.cache?.get(cfg.logChannelId);
    return ch?.isTextBased?.() ? ch : null;
  } catch {
    return null;
  }
}

function sendLog(guild, embed) {
  const ch = logChannelOf(guild);
  if (ch) ch.send({ embeds: [embed] }).catch(() => {});
}

function modEmbed(color, title, fields) {
  return new EmbedBuilder().setColor(color).setTitle(title).addFields(fields).setTimestamp();
}

/**
 * Sabhi mod commands ka shared pre-flight:
 * guild + permission + target validity check karke target member deta hai, warna null.
 */
async function prepare(interaction, { perm, permName, action }) {
  const guild = requireGuild(interaction);
  if (!guild) return null;

  if (!hasModPerm(interaction, perm)) {
    await deny(interaction, `❌ Tumhare paas **${permName}** permission nahi hai.`);
    return null;
  }
  if (!botHasPerm(interaction, perm)) {
    await deny(
      interaction,
      `❌ Mere paas **${permName}** permission nahi hai — role settings check karo (mera role target se upar hona chahiye).`
    );
    return null;
  }

  const target = interaction.options.getUser('user', true);
  if (!target) {
    await deny(interaction, '❌ User nahi mila.');
    return null;
  }
  if (target.id === interaction.user?.id) {
    await deny(interaction, `❌ Tum khud ko ${action} nahi kar sakte 😅`);
    return null;
  }
  if (target.bot) {
    await deny(interaction, `❌ Bot pe ${action} is command se nahi hota.`);
    return null;
  }

  // Guild me hai ya nahi
  let member = null;
  try {
    member = await guild.members.fetch(target.id);
  } catch {
    member = null;
  }
  if (!member) {
    await deny(interaction, `❌ ${target.username ?? 'ye user'} is server me nahi hai.`);
    return null;
  }
  if (blockedByHierarchy(interaction, member)) {
    await deny(interaction, `❌ ${member.user?.username ?? 'target'} ka role mere role se upar (ya braabar) hai — main ${action} nahi kar sakta.`);
    return null;
  }

  return { guild, member, target };
}

/* ------------------------------------------------------------------ */
/*  Commands                                                           */
/* ------------------------------------------------------------------ */
module.exports = [
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('kick')
      .setDescription('Kisi member ko server se kick karo')
      .setDefaultMemberPermissions(PermissionFlagsBits.KickMembers)
      .setDMPermission(false)
      .addUserOption((o) => o.setName('user').setDescription('Kisko kick karna hai?').setRequired(true))
      .addStringOption((o) =>
        o.setName('reason').setDescription('Reason (audit log + log channel me jaayega)').setMaxLength(400)
      ),
    async execute(interaction) {
      const ctx = await prepare(interaction, {
        perm: PermissionFlagsBits.KickMembers,
        permName: 'Kick Members',
        action: 'kick',
      });
      if (!ctx) return;
      const { guild, member, target } = ctx;
      const reason = interaction.options.getString('reason') || null;

      await guild.members.kick(member, auditReason(interaction, reason));

      sendLog(
        guild,
        modEmbed(0xf0b232, '👢 Member kicked', [
          { name: 'User', value: `${target.username ?? target} (${target.id})`, inline: true },
          { name: 'By', value: `${interaction.user?.username ?? '?'} (${interaction.user?.id ?? '?'})`, inline: true },
          { name: 'Reason', value: reason || '—' },
        ])
      );

      await reply(interaction, {
        content: `👢 **${target.username ?? target}** ko kick kar diya.${reason ? `\n📝 Reason: ${reason}` : ''}`,
        ephemeral: true,
      });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('ban')
      .setDescription('Kisi member ko server se ban karo')
      .setDefaultMemberPermissions(PermissionFlagsBits.BanMembers)
      .setDMPermission(false)
      .addUserOption((o) => o.setName('user').setDescription('Kisko ban karna hai?').setRequired(true))
      .addStringOption((o) => o.setName('reason').setDescription('Reason').setMaxLength(400))
      .addIntegerOption((o) =>
        o
          .setName('delete_days')
          .setDescription('Kitne din ke messages delete karein? (default 0)')
          .setMinValue(0)
          .setMaxValue(7)
      ),
    async execute(interaction) {
      const ctx = await prepare(interaction, {
        perm: PermissionFlagsBits.BanMembers,
        permName: 'Ban Members',
        action: 'ban',
      });
      if (!ctx) return;
      const { guild, member, target } = ctx;
      const reason = interaction.options.getString('reason') || null;
      const deleteDays = interaction.options.getInteger('delete_days') ?? 0;

      await guild.members.ban(member, {
        deleteMessageSeconds: deleteDays * 86400,
        reason: auditReason(interaction, reason),
      });

      sendLog(
        guild,
        modEmbed(0xf23f43, '🔨 Member banned', [
          { name: 'User', value: `${target.username ?? target} (${target.id})`, inline: true },
          { name: 'By', value: `${interaction.user?.username ?? '?'} (${interaction.user?.id ?? '?'})`, inline: true },
          { name: 'Messages deleted', value: `${deleteDays} din`, inline: true },
          { name: 'Reason', value: reason || '—' },
        ])
      );

      await reply(interaction, {
        content: `🔨 **${target.username ?? target}** ko ban kar diya.${reason ? `\n📝 Reason: ${reason}` : ''}`,
        ephemeral: true,
      });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('timeout')
      .setDescription('Kisi member ko timeout (mute) karo')
      .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
      .setDMPermission(false)
      .addUserOption((o) => o.setName('user').setDescription('Kisko timeout karna hai?').setRequired(true))
      .addIntegerOption((o) =>
        o
          .setName('minutes')
          .setDescription('Kitne minute? (0 = timeout hatao)')
          .setMinValue(0)
          .setMaxValue(MAX_TIMEOUT_MINUTES)
          .setRequired(true)
      )
      .addStringOption((o) => o.setName('reason').setDescription('Reason').setMaxLength(400)),
    async execute(interaction) {
      const ctx = await prepare(interaction, {
        perm: PermissionFlagsBits.ModerateMembers,
        permName: 'Moderate Members (Timeout)',
        action: 'timeout',
      });
      if (!ctx) return;
      const { guild, member, target } = ctx;
      const minutes = interaction.options.getInteger('minutes', true);
      const reason = interaction.options.getString('reason') || null;

      await member.timeout(minutes > 0 ? minutes * 60_000 : null, auditReason(interaction, reason));

      const label = minutes > 0 ? `⏰ ${minutes} minute ke liye timeout` : '✅ timeout hata diya';
      sendLog(
        guild,
        modEmbed(0xfee75c, minutes > 0 ? '⏰ Member timed out' : '✅ Timeout removed', [
          { name: 'User', value: `${target.username ?? target} (${target.id})`, inline: true },
          { name: 'By', value: `${interaction.user?.username ?? '?'} (${interaction.user?.id ?? '?'})`, inline: true },
          { name: 'Duration', value: minutes > 0 ? `${minutes} min` : 'removed', inline: true },
          { name: 'Reason', value: reason || '—' },
        ])
      );

      await reply(interaction, {
        content: `${label} — **${target.username ?? target}**.${reason ? `\n📝 Reason: ${reason}` : ''}`,
        ephemeral: true,
      });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('purge')
      .setDescription('Channel se messages bulk-delete karo (max 100)')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageMessages)
      .setDMPermission(false)
      .addIntegerOption((o) =>
        o.setName('count').setDescription('Kitne messages? (1-100)').setMinValue(1).setMaxValue(100).setRequired(true)
      )
      .addUserOption((o) => o.setName('user').setDescription('Sirf is user ke messages delete karo')),
    async execute(interaction) {
      const guild = requireGuild(interaction);
      if (!guild) return;

      if (!hasModPerm(interaction, PermissionFlagsBits.ManageMessages)) {
        return deny(interaction, '❌ Tumhare paas **Manage Messages** permission nahi hai.');
      }
      const channel = interaction.channel;
      if (!channel || typeof channel.bulkDelete !== 'function') {
        return deny(interaction, '❌ Ye channel text-based nahi hai — yahan purge nahi ho sakta.');
      }
      if (!botHasPerm(interaction, PermissionFlagsBits.ManageMessages)) {
        return deny(interaction, '❌ Mere paas **Manage Messages** permission nahi hai.');
      }

      const count = interaction.options.getInteger('count', true);
      const filterUser = interaction.options.getUser('user');

      // Discord ki hard limit 100 hai — clamp kar do taaki API error na aaye
      const limit = Math.max(1, Math.min(100, Math.trunc(count)));

      await interaction.deferReply({ ephemeral: true });

      let deleted;
      try {
        if (filterUser) {
          const fetched = await channel.messages.fetch({ limit });
          const mine = fetched.filter((m) => m.author?.id === filterUser.id);
          deleted = mine.size ? await channel.bulkDelete(mine, true) : new Map();
        } else {
          deleted = await channel.bulkDelete(limit, true);
        }
      } catch (err) {
        return interaction.editReply(
          `❌ Purge fail hua: ${err.message}\n(14 din se purane messages bulk-delete nahi ho sakte.)`
        );
      }

      const n = deleted?.size ?? 0;
      sendLog(
        guild,
        modEmbed(0x5865f2, '🧹 Messages purged', [
          { name: 'Channel', value: `${channel}`, inline: true },
          { name: 'Deleted', value: `${n} / ${limit}`, inline: true },
          { name: 'Filter', value: filterUser ? `${filterUser.username ?? filterUser.id}` : 'sab', inline: true },
          { name: 'By', value: `${interaction.user?.username ?? '?'} (${interaction.user?.id ?? '?'})` },
        ])
      );

      await interaction.editReply(`🧹 **${n}** messages delete kiye${filterUser ? ` (${filterUser.username ?? 'user'} ke)` : ''}.`);
    },
  },
];

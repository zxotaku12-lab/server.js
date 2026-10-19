/**
 * Settings commands — welcome / auto-role / log channel configure karna
 * ---------------------------------------------------------------------
 * Bina inke bot.js ki welcome, auto-role aur moderation-logging features
 * configure hi nahi ho sakti thi (settings padhi jaati thi, likhi kahin nahi).
 *
 * Ye commands Gateway AUR HTTP dono mode me kaam karti hain:
 *   - Gateway: channel/role objects milte hain -> full validation
 *   - HTTP:    Discord ke `resolved` payload se ID + naam mil jaata hai, aur
 *              `member.permissions` se permission check REAL rehta hai
 *              (object-level validation skip hoti hai, reply me bata diya jaata hai)
 *
 * Likhai lib/settings.js ke shared cache se hoti hai, isliye bot.js ko
 * turant pata chal jaata hai (stale cache wali bug nahi).
 */
const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const settings = require('../lib/settings');
const { hasMemberPerm, hasBotPerm, PERM_NAMES } = require('../lib/perms');

/**
 * Channel/role ka display label.
 * Gateway me discord.js objects ka apna toString() hota hai (<#id> / <@&id>),
 * HTTP mode me Discord ka `resolved` plain object hota hai — uska toString
 * Object.prototype se aata hai aur "[object Object]" deta hai. Isliye check karte
 * hain ki toString khud ka hai ya inherited.
 */
const describe = (obj, fallbackPrefix) => {
  if (!obj) return null;
  const own = typeof obj.toString === 'function' && obj.toString !== Object.prototype.toString;
  const label = own ? obj.toString() : `${fallbackPrefix}${obj.id}>`;
  return { id: obj.id, label, name: obj.name ?? null };
};

const isTextChannel = (ch) => (typeof ch?.isTextBased === 'function' ? ch.isTextBased() : true);

async function requireGuildId(interaction) {
  const guildId = interaction.guildId ?? interaction.guild?.id;
  if (!guildId) {
    await interaction.reply({ content: '⚠️ Settings sirf server ke andar change hoti hain — DM me nahi.', ephemeral: true });
    return null;
  }
  return guildId;
}

async function requirePerm(interaction, flag, name) {
  if (!hasMemberPerm(interaction, flag)) {
    await interaction.reply({
      content: `❌ Iske liye tumhare paas **${name}** permission honi chahiye.`,
      ephemeral: true,
    });
    return false;
  }
  return true;
}

/** Channel set/clear karne ka shared logic (welcome + logs) */
async function setChannelSetting(interaction, { key, what, label }) {
  const guildId = await requireGuildId(interaction);
  if (!guildId) return;
  if (!(await requirePerm(interaction, PermissionFlagsBits.ManageGuild, PERM_NAMES.ManageGuild))) return;

  const raw = interaction.options.getChannel('channel');

  // option diya hi nahi -> setting OFF
  if (!raw) {
    settings.unset(guildId, key);
    return interaction.reply({
      content: `✅ ${label} **band** kar diya. ${what} ab nahi hoga.`,
      ephemeral: true,
    });
  }

  const ch = describe(raw, '<#');

  if (!isTextChannel(raw)) {
    return interaction.reply({ content: '❌ Ye text channel nahi hai — message bhej nahi sakta wahan.', ephemeral: true });
  }
  if (!hasBotPerm(interaction, PermissionFlagsBits.ViewChannel) || !hasBotPerm(interaction, PermissionFlagsBits.SendMessages)) {
    return interaction.reply({
      content: `❌ Mujhe ${ch.label} me **View Channel** + **Send Messages** permission nahi hai. Pehle wo de do.`,
      ephemeral: true,
    });
  }

  // Gateway mode me channel ke asli guild ka cross-check
  if (interaction.guild && raw.guildId && raw.guildId !== guildId) {
    return interaction.reply({ content: '❌ Ye channel kisi doosre server ka hai.', ephemeral: true });
  }

  settings.set(guildId, { [key]: ch.id });
  const note = interaction.guild ? '' : '\n_ℹ️ HTTP mode: channel type ki full validation Gateway bot karega._';
  return interaction.reply({ content: `✅ ${label} ab ${ch.label} pe set hai.${note}`, ephemeral: true });
}

module.exports = [
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('setwelcome')
      .setDescription('Welcome message ka channel set karo (ya band karo)')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
      .setDMPermission(false)
      .addChannelOption((o) =>
        o
          .setName('channel')
          .setDescription('Welcome message kahan jaaye? (khaali chhodo = band)')
          .addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement)
      ),
    async execute(interaction) {
      await setChannelSetting(interaction, {
        key: 'welcomeChannelId',
        what: 'Naye members ka welcome message',
        label: 'Welcome channel',
      });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('setlogs')
      .setDescription('Log channel set karo — join/leave + moderation actions (ya band karo)')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
      .setDMPermission(false)
      .addChannelOption((o) =>
        o
          .setName('channel')
          .setDescription('Logs kahan jaayein? (khaali chhodo = band)')
          .addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement)
      ),
    async execute(interaction) {
      await setChannelSetting(interaction, {
        key: 'logChannelId',
        what: 'Join/leave aur moderation logs',
        label: 'Log channel',
      });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('setautorole')
      .setDescription('Join par automatically dene waala role set karo (ya band karo)')
      .setDefaultMemberPermissions(PermissionFlagsBits.ManageRoles)
      .setDMPermission(false)
      .addRoleOption((o) => o.setName('role').setDescription('Kaunsa role dein? (khaali chhodo = band)')),
    async execute(interaction) {
      const guildId = await requireGuildId(interaction);
      if (!guildId) return;
      if (!(await requirePerm(interaction, PermissionFlagsBits.ManageRoles, PERM_NAMES.ManageRoles))) return;

      const raw = interaction.options.getRole('role');

      if (!raw) {
        settings.unset(guildId, 'memberRoleId');
        return interaction.reply({ content: '✅ Auto-role **band** kar diya.', ephemeral: true });
      }

      const role = describe(raw, '<@&');

      if (role.id === guildId) {
        return interaction.reply({ content: '❌ `@everyone` auto-role me nahi de sakte.', ephemeral: true });
      }

      // Gateway mode me hierarchy check — bot apne se upar waala role nahi de sakta
      const me = interaction.guild?.members?.me;
      if (me?.roles?.highest && typeof raw.comparePositionTo === 'function') {
        if (raw.comparePositionTo(me.roles.highest) >= 0) {
          return interaction.reply({
            content: `❌ ${role.label} mera role se upar (ya braabar) hai — main ye role de nahi sakta. Mera role upar karo.`,
            ephemeral: true,
          });
        }
      }
      if (!hasBotPerm(interaction, PermissionFlagsBits.ManageRoles)) {
        return interaction.reply({
          content: '❌ Mere paas **Manage Roles** permission nahi hai.',
          ephemeral: true,
        });
      }

      settings.set(guildId, { memberRoleId: role.id });
      const note = interaction.guild ? '' : '\n_ℹ️ HTTP mode: role hierarchy ki full validation Gateway bot karega._';
      return interaction.reply({ content: `✅ Auto-role ab ${role.label} set hai.${note}`, ephemeral: true });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('settings')
      .setDescription('Is server ki current bot settings dekho')
      .setDMPermission(false),
    async execute(interaction) {
      const guildId = await requireGuildId(interaction);
      if (!guildId) return;

      const s = settings.get(guildId);
      const guild = interaction.guild;

      // Gateway mode me cache se resolve karke validate kar sakte hain.
      // HTTP mode me guild object hota hi nahi, isliye "nahi mila" warning jhoothi hogi —
      // wahan sirf mention dikhao (Discord khud resolve kar leta hai).
      const showChannel = (id) => {
        if (!id) return '_set nahi_';
        if (!guild) return `<#${id}>`;
        const ch = guild.channels?.cache?.get(id);
        return ch ? `${ch}` : `<#${id}> ⚠️ _(channel nahi mila — dobara set karo)_`;
      };
      const showRole = (id) => {
        if (!id) return '_set nahi_';
        if (!guild) return `<@&${id}>`;
        const r = guild.roles?.cache?.get(id);
        return r ? `${r}` : `<@&${id}> ⚠️ _(role nahi mila — dobara set karo)_`;
      };

      const embed = new EmbedBuilder()
        .setTitle('⚙️ Bot Settings')
        .setColor(0x5865f2)
        .addFields(
          { name: '👋 Welcome channel', value: s.welcomeChannelId ? showChannel(s.welcomeChannelId) : '_system channel (default)_', inline: false },
          { name: '🏷️ Auto-role', value: showRole(s.memberRoleId), inline: true },
          { name: '📋 Log channel', value: showChannel(s.logChannelId), inline: true },
          {
            name: '🔗 Gateway bot',
            value: interaction.client?.isReady?.() ? '✅ online' : '⚠️ offline — welcome/leveling nahi chalenge',
            inline: false,
          }
        )
        .setFooter({ text: 'Change karne ke liye: /setwelcome · /setautorole · /setlogs' });

      await interaction.reply({ embeds: [embed] });
    },
  },
];

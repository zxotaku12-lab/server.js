/**
 * Leveling commands: /rank aur /leaderboard
 * -----------------------------------------
 * XP bot.js pehle se collect karta tha, par dekhne ka koi tarika nahi tha.
 * Ye commands sirf data PADHTI hain (disk se fresh), isliye Gateway aur HTTP
 * dono mode me chalti hain — guild object ki zaroorat nahi, sirf guildId.
 */
const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const xp = require('../lib/xp');
const { bar } = require('../lib/levels');

const MEDAL = ['🥇', '🥈', '🥉'];
const display = (entry, fallbackId) => entry.username ?? `<@${entry.userId ?? fallbackId}>`;

function guildIdOf(interaction) {
  return interaction.guildId ?? interaction.guild?.id ?? null;
}

module.exports = [
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('rank')
      .setDescription('Apna (ya kisi ka) level, XP aur rank dekho')
      .setDMPermission(false)
      .addUserOption((o) => o.setName('user').setDescription('Kiska rank dekhna hai? (default: tum)')),
    async execute(interaction) {
      const guildId = guildIdOf(interaction);
      if (!guildId) {
        return interaction.reply({ content: '⚠️ XP sirf server ke andar track hota hai — DM me nahi.', ephemeral: true });
      }

      const target = interaction.options.getUser('user') ?? interaction.user;
      const targetId = target?.id ?? null;
      if (!targetId) {
        return interaction.reply({ content: '❌ User resolve nahi hua.', ephemeral: true });
      }

      const entry = xp.getEntry(guildId, targetId);
      const { rank, total } = xp.rankOf(guildId, targetId);

      if (!entry || entry.xp <= 0) {
        return interaction.reply({
          content: `📭 **${target.username ?? 'Is user'}** ka abhi tak koi XP record nahi hai.\nMessages bhejna shuru karo — XP apne aap milta rahega (har 60 second me ek baar).`,
          ephemeral: targetId !== interaction.user?.id,
        });
      }

      const embed = new EmbedBuilder()
        .setTitle(`📊 ${target.username ?? 'Rank'}`)
        .setColor(0x57f287)
        .setThumbnail(target.displayAvatarURL?.({ size: 128 }) ?? null)
        .addFields(
          { name: 'Level', value: `**${entry.level}**`, inline: true },
          { name: 'Total XP', value: `**${entry.xp.toLocaleString('en-IN')}**`, inline: true },
          { name: 'Rank', value: rank ? `**#${rank}** / ${total}` : '—', inline: true },
          {
            name: `Level ${entry.level + 1} tak`,
            value: `${bar(entry.percent)} **${entry.percent}%**\n\`${entry.into.toLocaleString('en-IN')} / ${entry.span.toLocaleString('en-IN')} XP\` (${entry.next.toLocaleString('en-IN')} total chahiye)`,
            inline: false,
          }
        );

      await interaction.reply({ embeds: [embed] });
    },
  },

  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('leaderboard')
      .setDescription('Is server ka XP leaderboard (top 10)')
      .setDMPermission(false),
    async execute(interaction) {
      const guildId = guildIdOf(interaction);
      if (!guildId) {
        return interaction.reply({ content: '⚠️ Leaderboard sirf server ke andar dikhta hai.', ephemeral: true });
      }

      const board = xp.leaderboard(guildId, 10);
      const { total } = { total: xp.guildBoard(guildId).length };

      if (!board.length) {
        return interaction.reply({
          content: '📭 Abhi tak kisi ka XP record nahi hai. Baat-cheet shuru karo — leaderboard apne aap ban jaayega!',
        });
      }

      const lines = board.map((e, i) => {
        const medal = MEDAL[i] ?? `**${i + 1}.**`;
        return `${medal} ${display(e)} — Level **${e.level}** · ${e.xp.toLocaleString('en-IN')} XP`;
      });

      const myRank = xp.rankOf(guildId, interaction.user?.id);
      const embed = new EmbedBuilder()
        .setTitle(`🏆 Leaderboard — ${interaction.guild?.name ?? 'is server'}`)
        .setColor(0xfeb75c)
        .setDescription(lines.join('\n'))
        .setFooter({
          text: myRank.rank
            ? `${total} members tracked · tumhara rank #${myRank.rank}`
            : `${total} members tracked`,
        });

      await interaction.reply({ embeds: [embed] });
    },
  },
];

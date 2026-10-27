/**
 * Quest commands — /quest  /questlist  /questall  /questtop  /premium
 * -------------------------------------------------------------------
 * Sab kuch free hai: premium bhi ek click me milta hai, koi paisa/grind nahi.
 */
const { SlashCommandBuilder, EmbedBuilder, ButtonBuilder, ButtonStyle, ActionRowBuilder } = require('discord.js');
const quests = require('../lib/quests');
const users = require('../lib/users');
const periods = require('../lib/periods');
const { bar } = require('../lib/levels');

const COLOR = 0x5865f2;
const GOLD = 0xf1c40f;
const GREEN = 0x57f287;
const GREY = 0x95a5a6;

const guildIdOf = (i) => i.guildId ?? i.guild?.id ?? null;
const displayUser = (u, fallback = 'dost') => u?.username ?? fallback;

/** Quest card: emoji title — progress bar — reward */
function questLine(quest, { showReset = false } = {}) {
  const pct = quest.percent;
  const status = quest.claimed ? '✅ claimed' : quest.done ? '🎁 **claim karo!**' : `${quest.current}/${quest.target}`;
  const reset = showReset && quest.resetAt ? ` · reset ${periods.discordRelative(quest.resetAt)}` : '';
  return (
    `${quest.emoji} **${quest.title}** — \`${quest.current}/${quest.target}\` ${bar(pct, 8)} ${pct}%\n` +
    `> ${status} · reward **${quest.rewardCoins} 🪙 + ${quest.rewardXp} XP**${quest.premiumOnly ? ' · ⭐ premium' : ''}${reset}`
  );
}

function summaryLine(user) {
  const lvl = users.levelOf(user);
  const streak = Number(user.stats?.streak) || 0;
  return `🪙 **${(user.coins || 0).toLocaleString('en-IN')}** coins · ✨ **${(user.xp || 0).toLocaleString('en-IN')}** XP · Level **${lvl.level}** ${bar(lvl.percent, 6)}\n🔥 Streak: **${streak}** din · 🏅 Quests done: **${user.stats?.questsDone || 0}**`;
}

/** Claim-all button (sirf apne liye) */
function claimRow(userId) {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`quest:claimall:${userId}`).setLabel('🎁 Sab claim karo').setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId(`quest:refresh:${userId}`).setLabel('🔄 Refresh').setStyle(ButtonStyle.Secondary)
  );
}

module.exports = [
  /* ------------------------------- /quest ------------------------------- */
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('quest')
      .setDescription('Aaj ke quests + tumhara progress (free rewards!)')
      .setDMPermission(false)
      .addUserOption((o) => o.setName('user').setDescription('Kiska progress dekhna hai? (default: tum)')),
    async execute(interaction) {
      const guildId = guildIdOf(interaction);
      if (!guildId) return interaction.reply({ content: '⚠️ Quests sirf server ke andar chalti hain.', ephemeral: true });

      const target = interaction.options.getUser('user') ?? interaction.user;
      const isSelf = target.id === interaction.user.id;
      const user = users.ensure(guildId, target.id);
      const list = quests.activeQuests(user, new Date(), 'daily');
      const premium = users.isPremium(user);

      const embed = new EmbedBuilder()
        .setTitle(`🎯 ${displayUser(target)} ke aaj ke quests`)
        .setColor(premium ? GOLD : COLOR)
        .setDescription(
          headerText(premium) + '\n\n' + list.map((item) => questLine(item, { showReset: true })).join('\n\n')
        )
        .addFields({ name: '📊 Tumhara progress', value: summaryLine(user) })
        .setFooter({ text: `Daily reset: ${periods.discordRelative(periods.nextReset(new Date(), 'daily'))} · sab free` })
        .setTimestamp();

      const canClaim = isSelf && list.some((item) => item.claimable);
      return interaction.reply({
        embeds: [embed],
        components: isSelf ? [claimRow(target.id)] : [],
        ...(canClaim ? {} : {}),
      });
    },
  },

  /* ----------------------------- /questlist ----------------------------- */
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('questlist')
      .setDescription('Saari quests ki list — type ke hisaab se')
      .setDMPermission(false)
      .addStringOption((o) =>
        o
          .setName('type')
          .setDescription('Kaunsi list? (default: sab)')
          .addChoices(
            { name: '🏆 Saari (daily + weekly + one-time)', value: 'all' },
            { name: '📅 Daily pool', value: 'daily' },
            { name: '⭐ Premium daily', value: 'premium' },
            { name: '🗓️ Weekly', value: 'weekly' },
            { name: '🎖️ One-time', value: 'once' }
          )
      ),
    async execute(interaction) {
      const type = interaction.options.getString('type') ?? 'all';
      const cat = quests.catalog();

      const section = (title, items, note) =>
        `**${title}**${note ? ` — ${note}` : ''}\n` +
        items.map((q) => `> ${q.emoji} **${q.title}** · ${q.target} ${q.metricLabel} → **${q.reward.coins} 🪙 + ${q.reward.xp} XP**`).join('\n');

      const parts = [];
      if (type === 'all' || type === 'daily') parts.push(section('📅 Daily', cat.daily, `har din ${cat.rotation.daily} rotate`));
      if (type === 'all' || type === 'premium') parts.push(section('⭐ Premium daily', cat.premium, `FREE — premium walon ko +${cat.rotation.premium} daily`));
      if (type === 'all' || type === 'weekly') parts.push(section('🗓️ Weekly', cat.weekly, `har hafte ${cat.rotation.weekly} rotate`));
      if (type === 'all' || type === 'once') parts.push(section('🎖️ One-time', cat.once, 'kabhi bhi'));

      let text = parts.join('\n\n');
      if (text.length > 4000) text = text.slice(0, 3900) + '\n…';

      const embed = new EmbedBuilder()
        .setTitle('📜 Quest list')
        .setColor(COLOR)
        .setDescription(text)
        .addFields({
          name: '⭐ Premium — bilkul FREE',
          value: `Premium lene ke liye kuch **kharidna ya grind nahi** karna — bas \`/premium\` chalao.\nPremium = **${cat.rotation.premium} extra daily quests** + **×${cat.premiumMultiplier} rewards**.`,
        })
        .setFooter({ text: 'Aaj ke quests dekhne ke liye /quest · sab claim karne ke liye /questall' });

      return interaction.reply({ embeds: [embed] });
    },
  },

  /* ----------------------------- /questall ------------------------------ */
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('questall')
      .setDescription('Daily + weekly + one-time — sab ek saath, ek click me claim')
      .setDMPermission(false),
    async execute(interaction) {
      const guildId = guildIdOf(interaction);
      if (!guildId) return interaction.reply({ content: '⚠️ Quests sirf server ke andar chalti hain.', ephemeral: true });

      const user = users.ensure(guildId, interaction.user.id);
      const daily = quests.activeQuests(user, new Date(), 'daily');
      const weekly = quests.activeQuests(user, new Date(), 'weekly');
      const once = quests.activeQuests(user, new Date(), 'once');

      const embed = new EmbedBuilder()
        .setTitle('🎯 Saare quests — ek jagah')
        .setColor(users.isPremium(user) ? GOLD : GREEN)
        .setDescription(headerText(users.isPremium(user)))
        .setFooter({ text: `Daily reset ${periods.discordRelative(periods.nextReset(new Date(), 'daily'))} · Weekly reset ${periods.discordRelative(periods.nextReset(new Date(), 'weekly'))}` });

      const blocks = [
        ['📅 Daily', daily],
        ['🗓️ Weekly', weekly],
        ['🎖️ One-time', once],
      ];

      for (const [title, list] of blocks) {
        const value = list.map((item) => questLine(item)).join('\n\n');
        if (value) embed.addFields({ name: title, value: value.slice(0, 1024), inline: false });
      }

      embed.addFields({ name: '📊 Tumhara progress', value: summaryLine(user) });

      const claimable = [...daily, ...weekly, ...once].filter((item) => item.claimable).length;

      return interaction.reply({
        content: claimable
          ? `🎁 **${claimable} quest${claimable > 1 ? 's' : ''} ready hai** — neeche button dabao!`
          : '👍 Sab clear hai — naye quests ke liye thoda aur grind karo (free hai bhai 😄)',
        embeds: [embed],
        components: [claimRow(interaction.user.id)],
      });
    },
  },

  /* ----------------------------- /questtop ------------------------------ */
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('questtop')
      .setDescription('Server ka quest leaderboard — sabse zyada quests kaun kar raha hai')
      .setDMPermission(false),
    async execute(interaction) {
      const guildId = guildIdOf(interaction);
      if (!guildId) return interaction.reply({ content: '⚠️ Leaderboard sirf server me dikhta hai.', ephemeral: true });

      const rows = Object.entries(users.all())
        .filter(([key]) => key.startsWith(`${guildId}:`))
        .map(([key, user]) => ({
          id: key.slice(guildId.length + 1),
          quests: Number(user.stats?.questsDone) || 0,
          coins: Number(user.coins) || 0,
          xp: Number(user.xp) || 0,
          streak: Number(user.stats?.streak) || 0,
        }))
        .filter((row) => row.quests > 0)
        .sort((a, b) => b.quests - a.quests || b.coins - a.coins)
        .slice(0, 10);

      if (!rows.length) {
        return interaction.reply({
          content: '📭 Abhi tak kisi ne quest claim nahi ki. Pehle bano! `/quest` chalao.',
        });
      }

      const medals = ['🥇', '🥈', '🥉'];
      const lines = rows.map((row, index) => {
        const medal = medals[index] ?? `**${index + 1}.**`;
        return `${medal} <@${row.id}> — **${row.quests}** quests · ${row.coins.toLocaleString('en-IN')} 🪙 · 🔥 ${row.streak}`;
      });

      const myIndex = rows.findIndex((row) => row.id === interaction.user.id);
      const embed = new EmbedBuilder()
        .setTitle(`🏆 Quest leaderboard — ${interaction.guild?.name ?? 'server'}`)
        .setColor(GOLD)
        .setDescription(lines.join('\n'))
        .setFooter({ text: myIndex >= 0 ? `Tumhara rank #${myIndex + 1}` : 'Tum abhi top 10 me nahi ho — /quest se shuru karo!' });

      return interaction.reply({ embeds: [embed] });
    },
  },

  /* ----------------------------- /premium ------------------------------- */
  {
    guildOnly: true,
    data: new SlashCommandBuilder()
      .setName('premium')
      .setDescription('Premium FREE hai — ek click me activate karo')
      .setDMPermission(false),
    async execute(interaction) {
      const guildId = guildIdOf(interaction);
      if (!guildId) return interaction.reply({ content: '⚠️ Premium sirf server ke andar milta hai.', ephemeral: true });

      const user = users.ensure(guildId, interaction.user.id);
      const active = users.isPremium(user);

      if (active) {
        const embed = new EmbedBuilder()
          .setTitle('⭐ Premium active hai')
          .setColor(GOLD)
          .setDescription(
            `Tumhare paas premium **already active** hai — bilkul free. 🎉\n\n` +
              `✅ +${quests.PREMIUM_PER_DAY} extra daily quests\n` +
              `✅ ×${quests.PREMIUM_MULTIPLIER} rewards\n` +
              `✅ ⭐ badge\n\n` +
              `_Kabhi kuch pay nahi karna padta. Enjoy!_`
          )
          .setFooter({ text: `Active since ${user.premiumSince ? periods.prettyDate(new Date(user.premiumSince)) : 'abhi'}` });
        return interaction.reply({ embeds: [embed], ephemeral: true });
      }

      const embed = new EmbedBuilder()
        .setTitle('⭐ Premium — FREE hai')
        .setColor(GOLD)
        .setDescription(
          `Koi paisa nahi, koi grind nahi. Button dabao, premium on. ✅\n\n` +
            `**Kya milta hai:**\n` +
            `• +${quests.PREMIUM_PER_DAY} extra daily quests\n` +
            `• ×${quests.PREMIUM_MULTIPLIER} rewards (coins + XP)\n` +
            `• ⭐ badge profile me\n\n` +
            `_Ye bot kabhi bhi tumse paisa nahi maangega._`
        );

      const row = new ActionRowBuilder().addComponents(
        new ButtonBuilder().setCustomId(`prem:activate:${interaction.user.id}`).setLabel('⭐ Premium free me lo').setStyle(ButtonStyle.Success)
      );

      return interaction.reply({ embeds: [embed], components: [row], ephemeral: true });
    },
  },
];

/** Embed ke top ka chhota header */
function headerText(premium) {
  return premium
    ? '⭐ **Premium active** — extra quests + ×1.5 rewards unlocked (free)'
    : '⭐ Premium **FREE** hai — `/premium` se ek click me lo';
}

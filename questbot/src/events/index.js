/**
 * Bot events — yahi se quest progress badhti hai
 * ----------------------------------------------
 * messageCreate      -> messages + XP (60s cooldown) + level-up announce
 * messageReactionAdd -> reactions
 * voiceStateUpdate   -> VC minutes (10 min ticker se live count)
 * guildMemberAdd     -> invites (invite uses compare karke)
 * interactionCreate  -> slash commands + buttons + commands metric
 */
const { Events, EmbedBuilder, ButtonBuilder, ButtonStyle, ActionRowBuilder } = require('discord.js');

const quests = require('../lib/quests');
const users = require('../lib/users');
const periods = require('../lib/periods');
const commands = require('../commands');
const { levelFromXp, progress, bar } = require('../lib/levels');

const XP_COOLDOWN_MS = 60_000;
const VOICE_TICK_MS = 10 * 60_000; // 10 minute

const xpCooldown = new Map();
const voiceSince = new Map(); // `${guildId}:${userId}` -> timestamp
const inviteCache = new Map(); // guildId -> Map(code -> uses)

const guildIdOf = (i) => i.guildId ?? i.guild?.id ?? null;

/** Ek event se quest progress — daily + weekly + lifetime, teeno */
function track(guildId, userId, metric, amount = 1) {
  if (!guildId || !userId) return;
  users.bump(guildId, userId, metric, amount);
}

/** Claim-all ka result embed */
function claimEmbed(result, targetUser) {
  const embed = new EmbedBuilder().setColor(result.claimed.length ? 0x57f287 : 0x95a5a6);

  if (!result.claimed.length) {
    return embed
      .setTitle('⏳ Abhi koi quest claim karne layak nahi')
      .setDescription('Quests complete karo — progress apne aap badhta hai (messages, reactions, VC, commands).');
  }

  const lines = result.claimed.map((q) => `✅ ${q.emoji} **${q.title}** → **${q.rewardCoins} 🪙 + ${q.rewardXp} XP**`);
  embed
    .setTitle(`🎁 ${result.claimed.length} quest${result.claimed.length > 1 ? 's' : ''} claimed!`)
    .setDescription(lines.join('\n'))
    .addFields(
      { name: 'Reward', value: `**+${result.coins.toLocaleString('en-IN')} 🪙 · +${result.xp.toLocaleString('en-IN')} XP**`, inline: true },
      { name: 'Level', value: `**${result.after.level}**${result.after.level > result.before.level ? ' 🎉 level up!' : ''}`, inline: true }
    )
    .setFooter({ text: `Total quests done: ${targetUser ? targetUser.stats.questsDone : 0}` });

  return embed;
}

module.exports = function register(client) {
  /* ------------------------------- READY ------------------------------- */
  client.once(Events.ClientReady, async () => {
    // Invite tracking ke liye baseline
    for (const guild of client.guilds.cache.values()) {
      guild.invites
        ?.fetch()
        .then((invites) => inviteCache.set(guild.id, new Map(invites.map((inv) => [inv.code, inv.uses ?? 0]))))
        .catch(() => {});
    }
  });

  client.on(Events.GuildCreate, (guild) => {
    guild.invites
      ?.fetch()
      .then((invites) => inviteCache.set(guild.id, new Map(invites.map((inv) => [inv.code, inv.uses ?? 0]))))
      .catch(() => {});
  });

  /* ---------------------------- MESSAGES ------------------------------ */
  client.on(Events.MessageCreate, async (message) => {
    if (message.author?.bot || !message.guild) return;
    if (message.system) return;

    const guildId = message.guild.id;
    const userId = message.author.id;
    const key = `${guildId}:${userId}`;
    const now = Date.now();

    // Quest progress har message par (XP sirf 60s me ek baar)
    track(guildId, userId, 'messages', 1);

    if (now - (xpCooldown.get(key) ?? 0) < XP_COOLDOWN_MS) return;
    xpCooldown.set(key, now);

    const user = users.ensure(guildId, userId);
    const oldLevel = levelFromXp(user.xp || 0);
    user.xp = (Number(user.xp) || 0) + 15 + Math.floor(Math.random() * 11);
    users.markDirty();

    const newLevel = levelFromXp(user.xp);
    if (newLevel > oldLevel && message.channel?.send) {
      const info = progress(user.xp);
      const embed = new EmbedBuilder()
        .setColor(0xf1c40f)
        .setDescription(`🎉 ${message.author} **Level ${newLevel}** pe pahunch gaya! ${bar(info.percent, 10)}`);
      message.channel.send({ embeds: [embed] }).catch(() => {});
    }
  });

  /* ---------------------------- REACTIONS ----------------------------- */
  client.on(Events.MessageReactionAdd, (reaction, user) => {
    if (user?.bot) return;
    const guildId = reaction?.message?.guildId ?? reaction?.message?.guild?.id;
    if (!guildId) return;
    track(guildId, user.id, 'reactions', 1);
  });

  /* ------------------------------ VOICE ------------------------------- */
  client.on(Events.VoiceStateUpdate, (oldState, newState) => {
    const guildId = newState.guild?.id ?? oldState.guild?.id;
    const userId = newState.id ?? oldState.id;
    if (!guildId || !userId) return;
    if (userId === client.user?.id) return;

    const key = `${guildId}:${userId}`;
    const wasIn = Boolean(oldState.channelId);
    const isIn = Boolean(newState.channelId);

    if (!wasIn && isIn) {
      voiceSince.set(key, Date.now());
    } else if (wasIn && !isIn) {
      const since = voiceSince.get(key);
      voiceSince.delete(key);
      if (!since) return;
      const minutes = Math.floor((Date.now() - since) / 60_000);
      if (minutes > 0) track(guildId, userId, 'voice', minutes);
    }
  });

  // VC me lambe time baithe logon ka bhi count — har 10 min me tick
  const voiceTimer = setInterval(() => {
    const now = Date.now();
    for (const [key, since] of voiceSince) {
      const minutes = Math.floor((now - since) / 60_000);
      if (minutes < 1) continue;
      const [guildId, userId] = key.split(':');
      track(guildId, userId, 'voice', minutes);
      voiceSince.set(key, now);
    }
    // XP cooldown map saaf karo
    for (const [key, ts] of xpCooldown) if (now - ts > XP_COOLDOWN_MS * 5) xpCooldown.delete(key);
  }, VOICE_TICK_MS);
  if (typeof voiceTimer.unref === 'function') voiceTimer.unref();

  /* ------------------------------ INVITES ----------------------------- */
  client.on(Events.GuildMemberAdd, async (member) => {
    if (member.user?.bot) return;
    const guild = member.guild;
    const before = inviteCache.get(guild.id);
    if (!before) return;

    try {
      const invites = await guild.invites?.fetch();
      if (!invites) return;

      let usedBy = null;
      for (const invite of invites.values()) {
        const previous = before.get(invite.code) ?? 0;
        if ((invite.uses ?? 0) > previous) {
          usedBy = invite.inviter?.id ?? null;
          break;
        }
      }
      inviteCache.set(guild.id, new Map(invites.map((inv) => [inv.code, inv.uses ?? 0])));
      if (usedBy) track(guild.id, usedBy, 'invites', 1);
    } catch {
      /* permissions nahi hain to chhod do */
    }
  });

  /* --------------------------- INTERACTIONS --------------------------- */
  client.on(Events.InteractionCreate, async (interaction) => {
    /* ---------- Buttons ---------- */
    if (interaction.isButton?.()) {
      const [scope, action, ownerId] = String(interaction.customId).split(':');
      const guildId = guildIdOf(interaction);

      if (ownerId && ownerId !== interaction.user.id) {
        return interaction.reply({ content: '❌ Ye button kisi aur ka hai — apna `/quest` chalao.', ephemeral: true }).catch(() => {});
      }
      if (!guildId) return interaction.reply({ content: '⚠️ Sirf server me chalta hai.', ephemeral: true }).catch(() => {});

      try {
        if (scope === 'quest' && action === 'claimall') {
          const result = quests.claimAll(guildId, interaction.user.id);
          const user = users.peek(guildId, interaction.user.id);
          return await interaction.reply({ embeds: [claimEmbed(result, user)], ephemeral: true });
        }

        if (scope === 'quest' && action === 'refresh') {
          const user = users.ensure(guildId, interaction.user.id);
          const list = quests.activeQuests(user);
          const embed = new EmbedBuilder()
            .setTitle('🔄 Refreshed — aaj ke quests')
            .setColor(users.isPremium(user) ? 0xf1c40f : 0x5865f2)
            .setDescription(list.map((q) => `> ${q.emoji} **${q.title}** — ${q.current}/${q.target} ${bar(q.percent, 6)}`).join('\n'))
            .setFooter({ text: `Reset ${periods.discordRelative(periods.nextReset(new Date(), 'daily'))}` });
          return await interaction.reply({ embeds: [embed], ephemeral: true });
        }

        if (scope === 'prem' && action === 'activate') {
          users.grantPremium(guildId, interaction.user.id);
          users.commit();
          const embed = new EmbedBuilder()
            .setTitle('⭐ Premium activated — FREE!')
            .setColor(0xf1c40f)
            .setDescription(
              `Ho gaya! 🎉 Ab tumhe **+${quests.PREMIUM_PER_DAY} extra daily quests** aur **×${quests.PREMIUM_MULTIPLIER} rewards** milenge.\n\n` +
                `\`/quest\` se naye quests dekho.`
            );
          return await interaction.reply({ embeds: [embed], ephemeral: true });
        }

        return interaction.reply({ content: '⚠️ Ye button purana hai — dobara `/quest` chalao.', ephemeral: true }).catch(() => {});
      } catch (err) {
        console.error('[events] button error:', err.message);
        return interaction.reply({ content: '❌ Kuch gadbad ho gayi. Dobara try karo.', ephemeral: true }).catch(() => {});
      }
    }

    /* ---------- Slash commands ---------- */
    if (!interaction.isChatInputCommand?.()) return;

    const command = commands.get(interaction.commandName);
    if (!command) return;

    const guildId = guildIdOf(interaction);
    if (command.guildOnly && !guildId) {
      return interaction.reply({ content: '⚠️ Ye command sirf server ke andar chalti hai.', ephemeral: true }).catch(() => {});
    }

    // Quest progress: commands (bots ke apne commands nahi ginte)
    if (guildId) track(guildId, interaction.user.id, 'commands', 1);

    try {
      await command.execute(interaction);
    } catch (err) {
      console.error(`[events] /${interaction.commandName} error:`, err);
      const payload = { content: '❌ Command me error aayi — logs check karo.', ephemeral: true };
      if (interaction.deferred || interaction.replied) {
        await interaction.editReply(payload).catch(() => {});
      } else {
        await interaction.reply(payload).catch(() => {});
      }
    }
  });

  client.on(Events.Error, (err) => console.error('[events] client error:', err?.message ?? err));
};

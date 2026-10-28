/**
 * Discord Bot — Gateway client (discord.js v14)
 * ---------------------------------------------
 * Do tarah se chal sakta hai:
 *   - server.js ke saath (DISCORD_TOKEN set ho to automatically)  <- recommended
 *   - akela:  npm run bot
 *
 * Kya-kya karta hai:
 *   - commands/ folder ki saari slash commands load + auto-register
 *   - Welcome message + auto-role (naya member aane par)
 *   - Leave message + join/leave logs
 *   - XP / leveling (har message pe, 60s cooldown)
 *
 * Env:
 *   DISCORD_TOKEN  - zaroori (Developer Portal -> Bot -> Reset Token)
 *   GUILD_ID       - optional; set karne par commands us guild me TURANT register hoti hain
 *                    (global registration me 1 ghanta lag sakta hai)
 *
 * Developer Portal -> Bot -> Privileged Gateway Intents ON karna zaroori hai:
 *   ✅ SERVER MEMBERS INTENT   (welcome / auto-role ke liye)
 *   ✅ MESSAGE CONTENT INTENT  zaroori NAHI hai (hum content padhte nahi, sirf XP ginte hain)
 */
const {
  Client,
  GatewayIntentBits,
  Partials,
  Events,
  ActivityType,
} = require('discord.js');

const { getCommands } = require('./commands');
const { load, save } = require('./store');
const settings = require('./lib/settings');
const giveaways = require('./lib/giveaways');
const antinuke = require('./lib/antinuke');
const { buildWelcome } = require('./lib/welcome');
const tickets = require('./lib/tickets');
const { levelFromXp } = require('./lib/levels');

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMembers, GatewayIntentBits.GuildMessages, GatewayIntentBits.GuildModeration],
  partials: [Partials.GuildMember],
});

/* ---------------- Commands load (shared registry) ---------------- */
const registry = getCommands();
client.commands = registry.map;
console.log(`[bot] ${registry.names.length} commands loaded (${registry.files.join(', ')})`);

/* ---------------- Settings ---------------- */
// Cache ab lib/settings.js me shared hai — commands/settings.js likhta hai aur bot.js
// wahi cache padhta hai, isliye /setwelcome ka asar turant hota hai (stale cache nahi).
const getSettings = settings.get;
const saveSettings = settings.set;
client.getSettings = getSettings;
client.saveSettings = saveSettings;

/* ---------------- Ready + auto register ---------------- */
client.once(Events.ClientReady, async (c) => {
  giveaways.startScheduler(c);
  console.log(`[bot] ✅ ${c.user.tag} live hai! ${c.guilds.cache.size} servers me.`);
  c.user.setActivity(`/help | ${registry.names.length} commands`, { type: ActivityType.Watching });

  try {
    const guildId = process.env.GUILD_ID;
    if (guildId) {
      const guild = await c.guilds.fetch(guildId).catch(() => null);
      if (guild) {
        await guild.commands.set(registry.json);
        console.log(`[bot] ${registry.names.length} commands guild "${guild.name}" me INSTANT register ho gaye ✅`);
        return;
      }
      console.warn(`[bot] GUILD_ID "${guildId}" nahi mila — global register kar raha hoon.`);
    }
    await c.application.commands.set(registry.json);
    console.log(
      `[bot] ${registry.names.length} commands GLOBALLY register ho gaye (1 ghanta lag sakta hai; GUILD_ID env se instant hota hai)`
    );
  } catch (e) {
    console.error('[bot] Command register fail:', e.message);
  }
});

client.on(Events.GuildAuditLogEntryCreate, (entry, guild) => {
  antinuke.handle(entry, guild).catch(err => console.error('[antinuke] error:', err));
});

/* ---------------- Slash command handler ---------------- */
client.on(Events.InteractionCreate, async (interaction) => {
  if (interaction.isButton() && ['ticket-open', 'ticket-close'].includes(interaction.customId)) {
    try { await (interaction.customId === 'ticket-open' ? tickets.open(interaction) : tickets.close(interaction)); }
    catch (err) { console.error('[tickets] interaction error:', err); }
    return;
  }
  if (interaction.isButton() && interaction.customId === 'giveaway-enter') {
    try { await giveaways.enter(interaction); } catch (err) { console.error('[giveaway] Entry error:', err); }
    return;
  }
  if (!interaction.isChatInputCommand()) return;
  const command = client.commands.get(interaction.commandName);
  if (!command) return;

  if (command.guildOnly && !interaction.inGuild()) {
    return interaction.reply({ content: '⚠️ Ye command sirf server ke andar chalti hai.', ephemeral: true }).catch(() => {});
  }

  try {
    await command.execute(interaction);
  } catch (err) {
    console.error(`[bot] /${interaction.commandName} error:`, err);
    if (interaction.deferred || interaction.replied) {
      await interaction.editReply({ content: '❌ Command me error aayi!' }).catch(() => {});
    } else {
      await interaction
        .reply({ content: '❌ Command me error aayi! Logs check karo.', ephemeral: true })
        .catch(() => {});
    }
  }
});

/* ---------------- Welcome + auto-role ---------------- */
client.on(Events.GuildMemberAdd, async (member) => {
  const settings = getSettings(member.guild.id);

  if (settings.memberRoleId) {
    const role = member.guild.roles.cache.get(settings.memberRoleId);
    if (role) await member.roles.add(role).catch(() => {});
  }

  const welcomeChannel = settings.welcomeChannelId
    ? member.guild.channels.cache.get(settings.welcomeChannelId)
    : member.guild.systemChannel;
  if (welcomeChannel?.isTextBased()) {
    const embed = buildWelcome(member, settings);
    welcomeChannel.send({ content: `<@${member.id}>`, embeds: [embed], allowedMentions: { users: [member.id] } }).catch(() => {});
  }

  if (settings.logChannelId) {
    const log = member.guild.channels.cache.get(settings.logChannelId);
    if (log?.isTextBased()) log.send(`📥 **${member.user.tag}** server join kiya.`).catch(() => {});
  }
});

client.on(Events.GuildMemberRemove, async (member) => {
  const settings = getSettings(member.guild.id);
  const welcomeChannel = settings.welcomeChannelId
    ? member.guild.channels.cache.get(settings.welcomeChannelId)
    : null;
  if (welcomeChannel?.isTextBased())
    welcomeChannel.send(`👋 **${member.user.tag}** server chhod gaya.`).catch(() => {});
  if (settings.logChannelId) {
    const log = member.guild.channels.cache.get(settings.logChannelId);
    if (log?.isTextBased()) log.send(`📤 **${member.user.tag}** leave kar gaya.`).catch(() => {});
  }
});

/* ---------------- XP / Leveling ---------------- */
const XP_COOLDOWN_MS = 60_000;
const xpCooldown = new Map();
let xpStore = null;

// Cooldown map ko saaf karte raho, warna lambi uptime pe memory badhti jaayegi.
setInterval(() => {
  const cutoff = Date.now() - XP_COOLDOWN_MS;
  for (const [key, ts] of xpCooldown) if (ts < cutoff) xpCooldown.delete(key);
}, 5 * 60_000).unref();

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot || !message.guild) return;

  const key = `${message.guild.id}:${message.author.id}`;
  const now = Date.now();
  if (now - (xpCooldown.get(key) ?? 0) < XP_COOLDOWN_MS) return;
  xpCooldown.set(key, now);

  if (!xpStore) xpStore = load('xp');
  const entry = xpStore[key] || { xp: 0 };
  const oldLevel = levelFromXp(entry.xp);

  entry.xp += 15 + Math.floor(Math.random() * 11);
  entry.username = message.author.username; // leaderboard ke liye naam yaad rakho
  xpStore[key] = entry;
  save('xp', xpStore);

  const newLevel = levelFromXp(entry.xp);
  if (newLevel > oldLevel) {
    message.channel
      .send(`🎉 Congrats ${message.author}! Tum **Level ${newLevel}** pe pahunch gaye!`)
      .catch(() => {});
  }
});

/* ---------------- Error safety ---------------- */
process.on('unhandledRejection', (err) => console.error('[bot] unhandled:', err?.message ?? err));

/* ---------------- Start / status ---------------- */
let started = false;
let lastError = null;

function start() {
  const TOKEN = process.env.DISCORD_TOKEN;
  if (!TOKEN) {
    console.warn('[bot] ⚠️ DISCORD_TOKEN nahi mila — Gateway bot start nahi ho raha.');
    return null;
  }
  if (started) return client;
  started = true;

  client.login(TOKEN).catch((err) => {
    started = false;
    lastError = err?.message ?? String(err);
    console.error('[bot] ❌ Login FAIL:', lastError);

    const msg = lastError.toLowerCase();
    if (err?.name === 'DisallowedIntents' || msg.includes('disallowed intents')) {
      console.error('[bot] 👉 FIX: Developer Portal → Bot → Privileged Gateway Intents me "SERVER MEMBERS INTENT" ON karo.');
    } else if (msg.includes('token')) {
      console.error('[bot] 👉 Token galat/purana hai — Developer Portal → Bot → Reset Token karke naya daalo.');
    } else if (msg.includes('used disallowed intents')) {
      console.error('[bot] 👉 Intent approval pending hai.');
    }
  });

  return client;
}

function getStatus() {
  if (!started) {
    return {
      ready: false,
      state: lastError ? 'error' : 'off',
      detail: lastError ?? (process.env.DISCORD_TOKEN ? 'start() call nahi hua' : 'DISCORD_TOKEN set nahi hai'),
    };
  }
  if (client.isReady?.()) {
    return {
      ready: true,
      state: 'ready',
      user: client.user?.tag ?? null,
      guilds: client.guilds?.cache?.size ?? 0,
      ping: client.ws?.ping ?? null,
      commands: registry.names.length,
    };
  }
  return { ready: false, state: lastError ? 'error' : 'connecting', detail: lastError ?? 'login/connect ho raha hai' };
}

if (require.main === module) start();

module.exports = client;
module.exports.start = start;
module.exports.getStatus = getStatus;

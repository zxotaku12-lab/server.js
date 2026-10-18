// Discord Bot — Gateway client (discord.js v14)
const fs = require('fs');
const path = require('path');
const {
  Client,
  GatewayIntentBits,
  Partials,
  Collection,
  Events,
  EmbedBuilder,
  ActivityType,
} = require('discord.js');
const { load, save } = require('./store');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
  ],
  partials: [Partials.GuildMember],
});

/* ---------------- Commands load ---------------- */
client.commands = new Collection();
const commandsPath = path.join(__dirname, 'commands');
const commandJson = [];
for (const f of fs.readdirSync(commandsPath).filter((x) => x.endsWith('.js'))) {
  const cmds = require(path.join(commandsPath, f));
  for (const cmd of Array.isArray(cmds) ? cmds : [cmds]) {
    client.commands.set(cmd.data.name, cmd);
    commandJson.push(cmd.data.toJSON());
  }
}
console.log(`[bot] ${commandJson.length} commands loaded`);

/* ---------------- Ready + auto register ---------------- */
client.once(Events.ClientReady, async (c) => {
  console.log(`[bot] ✅ ${c.user.tag} live hai! ${c.guilds.cache.size} servers me.`);
  c.user.setActivity('/help | All-in-one bot', { type: ActivityType.Watching });

  try {
    const guildId = process.env.GUILD_ID;
    if (guildId) {
      const guild = await c.guilds.fetch(guildId).catch(() => null);
      if (guild) {
        await guild.commands.set(commandJson);
        console.log(`[bot] ${commandJson.length} commands guild "${guild.name}" me INSTANT register ho gaye ✅`);
        return;
      }
      console.warn(`[bot] GUILD_ID "${guildId}" nahi mila — global register kar raha hoon.`);
    }
    await c.application.commands.set(commandJson);
    console.log(`[bot] ${commandJson.length} commands GLOBALLY register ho gaye (1 ghant tak lag sakta hai; GUILD_ID env se instant hota hai)`);
  } catch (e) {
    console.error('[bot] Command register fail:', e.message);
  }
});

/* ---------------- Slash command handler ---------------- */
client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand()) return;
  const command = client.commands.get(interaction.commandName);
  if (!command) return;

  try {
    await command.execute(interaction);
  } catch (err) {
    console.error(`[bot] /${interaction.commandName} error:`, err);
    const payload = { content: '❌ Command me error aayi! Logs check karo.', ephemeral: true };
    if (interaction.deferred || interaction.replied) {
      await interaction.editReply({ content: '❌ Command me error aayi!' }).catch(() => {});
    } else {
      await interaction.reply(payload).catch(() => {});
    }
  }
});

/* ---------------- Welcome + auto-role ---------------- */
client.on(Events.GuildMemberAdd, async (member) => {
  const settings = load('settings')[member.guild.id] || {};

  if (settings.memberRoleId) {
    const role = member.guild.roles.cache.get(settings.memberRoleId);
    if (role) await member.roles.add(role).catch(() => {});
  }

  const welcomeChannel = settings.welcomeChannelId
    ? member.guild.channels.cache.get(settings.welcomeChannelId)
    : member.guild.systemChannel;
  if (welcomeChannel?.isTextBased()) {
    const embed = new EmbedBuilder()
      .setTitle('🎉 Welcome!')
      .setColor(0x57f287)
      .setThumbnail(member.user.displayAvatarURL({ size: 128 }))
      .setDescription(
        `Namaste ${member}! **${member.guild.name}** me swagat hai! 🥳\n\n` +
          `📜 Rules padho, 👋 #general me intro do, aur maze karo!\n\n` +
          `👥 Ab hum **${member.guild.memberCount}** members hain!`
      );
    welcomeChannel.send({ content: `${member}`, embeds: [embed] }).catch(() => {});
  }

  if (settings.logChannelId) {
    const log = member.guild.channels.cache.get(settings.logChannelId);
    if (log?.isTextBased())
      log.send(`📥 **${member.user.tag}** server join kiya.`).catch(() => {});
  }
});

client.on(Events.GuildMemberRemove, async (member) => {
  const settings = load('settings')[member.guild.id] || {};
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
const xpCooldown = new Map();
client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot || !message.guild) return;

  const key = message.author.id;
  const now = Date.now();
  if (xpCooldown.get(key) && now - xpCooldown.get(key) < 60000) return;
  xpCooldown.set(key, now);

  const all = load('xp');
  const xpKey = `${message.guild.id}:${message.author.id}`;
  const entry = all[xpKey] || { xp: 0 };
  const oldLevel = Math.floor(0.1 * Math.sqrt(entry.xp));
  entry.xp += 15 + Math.floor(Math.random() * 11);
  const newLevel = Math.floor(0.1 * Math.sqrt(entry.xp));
  all[xpKey] = entry;
  save('xp', all);

  if (newLevel > oldLevel) {
    message.channel
      .send(`🎉 Congrats ${message.author}! Tum **Level ${newLevel}** pe pahunch gaye!`)
      .catch(() => {});
  }
});

/* ---------------- Error safety ---------------- */
process.on('unhandledRejection', (err) => console.error('[bot] unhandled:', err));

/* ---------------- Login ---------------- */
const TOKEN = process.env.DISCORD_TOKEN;
if (!TOKEN) {
  console.warn('[bot] ⚠️ DISCORD_TOKEN nahi mila — sirf web server chal raha hai. Bot offline rahega.');
} else {
  client.login(TOKEN).catch((err) => {
    console.error('[bot] ❌ Login FAIL:', err.message);
    if (String(err.message).toLowerCase().includes('disallowed intents')) {
      console.error('[bot] 👉 FIX: Discord Developer Portal → Bot → "Server Members Intent" ON karo!');
    } else if (String(err.message).toLowerCase().includes('token')) {
      console.error('[bot] 👉 Token galat hai — Developer Portal → Bot → Reset Token karke naya daalo.');
    }
  });
}

module.exports = client;

// Core commands: ping, hello, help
const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

const BLURB = {
  ping: 'Bot zinda hai ya nahi — check karo',
  hello: 'Bot tumhe greet karta hai',
  help: 'Saari commands ki list',
};

module.exports = [
  {
    data: new SlashCommandBuilder().setName('ping').setDescription('Check if the bot is alive'),
    async execute(interaction) {
      const ws = interaction.client?.ws?.ping;
      const latency = Number.isFinite(ws) && ws >= 0 ? ` (gateway ${Math.round(ws)}ms)` : '';
      await interaction.reply(`🏓 Pong! Bot is alive ✅${latency}`);
    },
  },

  {
    data: new SlashCommandBuilder().setName('hello').setDescription('Bot greets you'),
    async execute(interaction) {
      const who = interaction.user?.toString?.() ?? 'dost';
      await interaction.reply(`👋 Namaste, ${who}!`);
    },
  },

  {
    data: new SlashCommandBuilder().setName('help').setDescription('Show all commands'),
    async execute(interaction) {
      // Registry ko execute ke andar require karte hain — load-time circular dependency se bachne ke liye.
      const { getCommands, commandUsage } = require('./index');
      const { map } = getCommands();

      const lines = [...map.values()]
        .sort((a, b) => a.data.name.localeCompare(b.data.name))
        .map((cmd) => `\`${commandUsage(cmd)}\` — ${cmd.data.description || BLURB[cmd.data.name] || ''}`);

      const embed = new EmbedBuilder()
        .setTitle('📖 Commands')
        .setColor(0x5865f2)
        .setDescription(lines.join('\n') || 'Koi command load nahi hui 😅')
        .setFooter({ text: `${map.size} commands · /help` });

      await interaction.reply({ embeds: [embed] });
    },
  },
];

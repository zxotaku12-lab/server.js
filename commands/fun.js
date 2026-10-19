// Fun commands: 8ball, coinflip, roll, rps
const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

const BALL = [
  '💯 Haan bilkul!', '✅ Pakka yes', '🌟 Signs aise bata rahe hain — haan',
  '🤔 Ho sakta hai', '❓ Dhyan se soch ke batao', '😅 Abhi nahi',
  '❌ Nahi', '🚫 Bilkul nahi', '🔮 Future bright dikh raha hai', '🗿 Mujhe kya pata bhai',
];

module.exports = [
  {
    data: new SlashCommandBuilder()
      .setName('8ball')
      .setDescription('Magic ball se sawal poocho')
      .addStringOption((o) => o.setName('question').setDescription('Sawal?').setRequired(true)),
    async execute(interaction) {
      const q = interaction.options.getString('question', true);
      const answer = BALL[Math.floor(Math.random() * BALL.length)];
      const embed = new EmbedBuilder()
        .setTitle('🎱 Magic 8-Ball')
        .setColor(0x2b2d31)
        .addFields({ name: '❓ Sawal', value: q }, { name: '💬 Jawab', value: answer });
      await interaction.reply({ embeds: [embed] });
    },
  },
  {
    data: new SlashCommandBuilder().setName('coinflip').setDescription('Toss — heads ya tails?'),
    async execute(interaction) {
      const result = Math.random() < 0.5 ? '🪙 **HEADS!**' : '🪙 **TAILS!**';
      await interaction.reply(`${result}\n(${interaction.user.username} ka toss)`);
    },
  },
  {
    data: new SlashCommandBuilder()
      .setName('roll')
      .setDescription('Dice pheko (1-100)')
      .addIntegerOption((o) =>
        o.setName('max').setDescription('Max number? (default 100)').setMinValue(2).setMaxValue(1000000)
      ),
    async execute(interaction) {
      const max = interaction.options.getInteger('max') || 100;
      const roll = Math.floor(Math.random() * max) + 1;
      await interaction.reply(`🎲 ${interaction.user.username} ne **${max}** me se **${roll}** roll kiya!`);
    },
  },
  {
    data: new SlashCommandBuilder()
      .setName('rps')
      .setDescription('Rock-Paper-Scissors khelo bot ke against!')
      .addStringOption((o) =>
        o
          .setName('choice')
          .setDescription('Kya kheloge?')
          .setRequired(true)
          .addChoices(
            { name: '🪨 Rock', value: 'rock' },
            { name: '📄 Paper', value: 'paper' },
            { name: '✂️ Scissors', value: 'scissors' }
          )
      ),
    async execute(interaction) {
      const userChoice = interaction.options.getString('choice', true);
      const botChoice = ['rock', 'paper', 'scissors'][Math.floor(Math.random() * 3)];
      const emoji = { rock: '🪨', paper: '📄', scissors: '✂️' };

      let result;
      if (userChoice === botChoice) result = '🤝 **Tie!** Dono ne same khela!';
      else if (
        (userChoice === 'rock' && botChoice === 'scissors') ||
        (userChoice === 'paper' && botChoice === 'rock') ||
        (userChoice === 'scissors' && botChoice === 'paper')
      )
        result = '🎉 **Tum jeet gaye!**';
      else result = '😈 **Main jeet gaya!**';

      await interaction.reply(
        `Tum: ${emoji[userChoice]} vs Main: ${emoji[botChoice]}\n${result}`
      );
    },
  },
];

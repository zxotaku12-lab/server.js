const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const { randomInt } = require('crypto');
const base = (name, desc) => new SlashCommandBuilder().setName(name).setDescription(desc);
const textOption = o => o.setName('text').setDescription('Text likho').setRequired(true).setMaxLength(1000);
const safe = (i, content) => i.reply({ content: content.slice(0, 1900) || 'Khaali text.', allowedMentions: { parse: [] } });
const pick = list => list[randomInt(list.length)];
const funLists = {
  joke: ['Programmer ne light kyun band ki? Dark mode pasand tha!', 'Computer ko thand kyun lagi? Windows khuli thi!', 'Bug party me kyun nahi gaya? Usko fix kar diya gaya.'],
  compliment: ['Tumhari energy kamaal hai! ✨', 'Tum is community ko better banate ho! 🌟', 'Tumhari creativity zabardast hai! 🎨'],
  motivation: ['Ek step aaj, ek step kal — tum kar loge! 💪', 'Break lena bhi progress ka hissa hai. 🌱', 'Mistakes se seekho, phir dobara try karo! 🚀'],
  fortune: ['Aaj kuch naya seekhne ka mauka milega. 🔮', 'Ek achha surprise tumhara intezaar kar raha hai. ✨', 'Aaj apne dost ko hello kehna lucky rahega. 🍀'],
};
module.exports = [
  ...Object.entries(funLists).map(([name, list]) => ({ data: base(name, `${name} suno`), async execute(i) { return safe(i, pick(list)); } })),
  { data: base('choose', 'Comma separated options me se choose karo').addStringOption(o => o.setName('options').setDescription('Jaise chai, coffee, juice').setRequired(true).setMaxLength(1000)),
    async execute(i) { const choices = i.options.getString('options').split(',').map(s => s.trim()).filter(Boolean); if (choices.length < 2) return safe(i, 'Kam se kam do comma-separated options do.'); return safe(i, `🎲 Choice: **${pick(choices)}**`); } },
  { data: base('reverse', 'Text ulta karo').addStringOption(textOption), async execute(i) { return safe(i, [...i.options.getString('text')].reverse().join('')); } },
  { data: base('uppercase', 'Text uppercase me badlo').addStringOption(textOption), async execute(i) { return safe(i, i.options.getString('text').toUpperCase()); } },
  { data: base('lowercase', 'Text lowercase me badlo').addStringOption(textOption), async execute(i) { return safe(i, i.options.getString('text').toLowerCase()); } },
  { data: base('wordcount', 'Words aur characters gino').addStringOption(textOption), async execute(i) { const t = i.options.getString('text').trim(); return safe(i, `Words: ${t ? t.split(/\s+/u).length : 0} · Characters: ${[...t].length}`); } },
  { data: base('rate', 'Kisi cheez ko random rating do').addStringOption(o => o.setName('thing').setDescription('Kya rate karein?').setRequired(true).setMaxLength(200)), async execute(i) { return safe(i, `⭐ ${i.options.getString('thing')}: ${randomInt(11)}/10`); } },
  { data: base('avatar', 'User ka avatar dekho').addUserOption(o => o.setName('user').setDescription('User (default: tum)')),
    async execute(i) { const u = i.options.getUser('user') || i.user; return i.reply({ embeds: [new EmbedBuilder().setTitle(`${u.username} ka avatar`).setImage(u.displayAvatarURL({ size: 1024 }))], allowedMentions: { parse: [] } }); } },
  { data: base('dice', 'Kai dice roll karo').addIntegerOption(o => o.setName('count').setDescription('Dice ki sankhya').setMinValue(1).setMaxValue(20)).addIntegerOption(o => o.setName('sides').setDescription('Har die ki sides').setMinValue(2).setMaxValue(100)),
    async execute(i) { const count = i.options.getInteger('count') || 1, sides = i.options.getInteger('sides') || 6, rolls = Array.from({ length: count }, () => randomInt(1, sides + 1)); return safe(i, `🎲 ${rolls.join(', ')} | Total: ${rolls.reduce((a,b) => a+b, 0)}`); } },
  { data: base('timestamp', 'Unix timestamp ko Discord timestamp me badlo').addIntegerOption(o => o.setName('unix').setDescription('Unix time in seconds').setRequired(true).setMinValue(0).setMaxValue(2147483647)), async execute(i) { const n = i.options.getInteger('unix'); return safe(i, `<t:${n}:F> · <t:${n}:R>\n\`<t:${n}:F>\``); } },
];

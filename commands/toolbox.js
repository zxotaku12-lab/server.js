// Each subcommand is an independently invocable command action. No network services needed.
const { SlashCommandBuilder } = require('discord.js');
const { randomInt } = require('crypto');
const make = (name, desc) => new SlashCommandBuilder().setName(name).setDescription(desc);
const reply = (i, text) => i.reply({ content: String(text).slice(0, 1900) || '(empty)', allowedMentions: { parse: [] } });

const textOps = {
  titlecase: ['Capitalize each word', s => s.toLowerCase().replace(/(^|\s)\S/gu, x => x.toUpperCase())],
  sentencecase: ['Capitalize sentence beginnings', s => s.toLowerCase().replace(/(^\s*|[.!?]\s+)\p{L}/gu, x => x.toUpperCase())],
  trim: ['Remove outer whitespace', s => s.trim()],
  collapse: ['Collapse repeated whitespace', s => s.replace(/\s+/gu, ' ').trim()],
  characters: ['Count Unicode characters', s => `Characters: ${[...s].length}`],
  lines: ['Count lines', s => `Lines: ${s.split(/\r?\n/).length}`],
  vowels: ['Count English vowels', s => `Vowels: ${(s.match(/[aeiou]/gi) || []).length}`],
  consonants: ['Count English consonants', s => `Consonants: ${(s.match(/[b-df-hj-np-tv-z]/gi) || []).length}`],
  digits: ['Count digits', s => `Digits: ${(s.match(/[0-9]/g) || []).length}`],
  letters: ['Count Unicode letters', s => `Letters: ${(s.match(/\p{L}/gu) || []).length}`],
  spaces: ['Count spaces', s => `Spaces: ${(s.match(/ /g) || []).length}`],
  unique: ['Count unique characters', s => `Unique characters: ${new Set([...s]).size}`],
  palindrome: ['Check a text palindrome', s => { const t = [...s.toLowerCase()].filter(c => /[\p{L}\p{N}]/u.test(c)); return t.join('') === t.reverse().join('') ? 'Palindrome ✅' : 'Palindrome nahi hai.'; }],
  sortwords: ['Sort words alphabetically', s => s.trim().split(/\s+/u).sort((a,b) => a.localeCompare(b)).join(' ')],
  sortlines: ['Sort lines alphabetically', s => s.split(/\r?\n/).sort((a,b) => a.localeCompare(b)).join('\n')],
  dedupewords: ['Remove duplicate words', s => [...new Set(s.trim().split(/\s+/u))].join(' ')],
  dedupelines: ['Remove duplicate lines', s => [...new Set(s.split(/\r?\n/))].join('\n')],
  slug: ['Create a URL slug', s => s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')],
  base64encode: ['Encode text as Base64', s => Buffer.from(s, 'utf8').toString('base64')],
  base64decode: ['Decode valid Base64 text', s => { if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(s)) throw Error('Invalid Base64'); return Buffer.from(s, 'base64').toString('utf8'); }],
  urlencode: ['URL-encode text', s => encodeURIComponent(s)],
};
const text = make('text-tools', 'Text utilities');
for (const [name, [desc]] of Object.entries(textOps)) text.addSubcommand(s => s.setName(name).setDescription(desc).addStringOption(o => o.setName('text').setDescription('Input text').setRequired(true).setMaxLength(1000)));

const mathOps = {
  square: ['Square', x => x*x], cube: ['Cube', x => x*x*x], sqrt: ['Square root', x => Math.sqrt(x)], cbrt: ['Cube root', x => Math.cbrt(x)],
  abs: ['Absolute value', x => Math.abs(x)], floor: ['Round down', x => Math.floor(x)], ceil: ['Round up', x => Math.ceil(x)], round: ['Round nearest', x => Math.round(x)], trunc: ['Remove decimals', x => Math.trunc(x)],
  reciprocal: ['Reciprocal', x => 1/x], factorial: ['Factorial of integer 0 to 170', x => { if (!Number.isInteger(x) || x < 0 || x > 170) return NaN; let r=1; for(let n=2;n<=x;n++) r*=n; return r; }],
  sin: ['Sine (degrees)', x => Math.sin(x*Math.PI/180)], cos: ['Cosine (degrees)', x => Math.cos(x*Math.PI/180)], tan: ['Tangent (degrees)', x => Math.abs(Math.cos(x*Math.PI/180)) < 1e-12 ? NaN : Math.tan(x*Math.PI/180)],
  asin: ['Inverse sine in degrees', x => Math.asin(x)*180/Math.PI], acos: ['Inverse cosine in degrees', x => Math.acos(x)*180/Math.PI], atan: ['Inverse tangent in degrees', x => Math.atan(x)*180/Math.PI],
  ln: ['Natural logarithm', x => Math.log(x)], log10: ['Base-10 logarithm', x => Math.log10(x)], log2: ['Base-2 logarithm', x => Math.log2(x)],
  exp: ['e raised to the input', x => Math.exp(x)], sign: ['Sign of a number', x => Math.sign(x)], degrees: ['Radians to degrees', x => x*180/Math.PI], radians: ['Degrees to radians', x => x*Math.PI/180], percent: ['Convert percentage to decimal', x => x/100],
};
const math = make('math-tools', 'Single-number mathematics');
for (const [name, [desc]] of Object.entries(mathOps)) math.addSubcommand(s => s.setName(name).setDescription(desc).addNumberOption(o => o.setName('number').setDescription('Input number').setRequired(true)));

const conversionOps = {
  'km-miles': ['Kilometres to miles', x => x/1.609344], 'miles-km': ['Miles to kilometres', x => x*1.609344],
  'metres-feet': ['Metres to feet', x => x/0.3048], 'feet-metres': ['Feet to metres', x => x*0.3048],
  'cm-inches': ['Centimetres to inches', x => x/2.54], 'inches-cm': ['Inches to centimetres', x => x*2.54],
  'kg-pounds': ['Kilograms to pounds', x => x/0.45359237], 'pounds-kg': ['Pounds to kilograms', x => x*0.45359237],
  'grams-ounces': ['Grams to ounces', x => x/28.349523125], 'ounces-grams': ['Ounces to grams', x => x*28.349523125],
  'celsius-fahrenheit': ['Celsius to Fahrenheit', x => x*9/5+32], 'fahrenheit-celsius': ['Fahrenheit to Celsius', x => (x-32)*5/9],
  'celsius-kelvin': ['Celsius to Kelvin', x => x+273.15], 'kelvin-celsius': ['Kelvin to Celsius', x => x-273.15],
  'litres-gallons': ['Litres to US gallons', x => x/3.785411784], 'gallons-litres': ['US gallons to litres', x => x*3.785411784],
  'ml-floz': ['Millilitres to US fluid ounces', x => x/29.5735295625], 'floz-ml': ['US fluid ounces to millilitres', x => x*29.5735295625],
  'kmh-mph': ['Kilometres per hour to mph', x => x/1.609344], 'mph-kmh': ['Miles per hour to km/h', x => x*1.609344],
  'seconds-minutes': ['Seconds to minutes', x => x/60], 'minutes-seconds': ['Minutes to seconds', x => x*60],
  'minutes-hours': ['Minutes to hours', x => x/60], 'hours-minutes': ['Hours to minutes', x => x*60], 'days-hours': ['Days to hours', x => x*24],
};
const convert = make('convert', 'Unit conversion tools');
for (const [name, [desc]] of Object.entries(conversionOps)) convert.addSubcommand(s => s.setName(name).setDescription(desc).addNumberOption(o => o.setName('value').setDescription('Value to convert').setRequired(true)));

const randomLists = {
  colour: ['red','blue','green','yellow','purple','orange','pink'],
  animal: ['cat','dog','fox','panda','otter','tiger','elephant'],
  fruit: ['apple','mango','banana','orange','kiwi','pear','grape'],
  vegetable: ['carrot','tomato','potato','broccoli','spinach','cucumber'],
  emoji: ['😀','😎','🥳','🐼','✨','🚀','🎉','🌈'],
  planet: ['Mercury','Venus','Earth','Mars','Jupiter','Saturn','Uranus','Neptune'],
  weekday: ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
  month: ['January','February','March','April','May','June','July','August','September','October','November','December'],
  season: ['spring','summer','autumn','winter'],
  direction: ['north','south','east','west'],
  suit: ['hearts','diamonds','clubs','spades'],
  card: ['ace','2','3','4','5','6','7','8','9','10','jack','queen','king'],
  chesspiece: ['king','queen','rook','bishop','knight','pawn'],
  weather: ['sunny','rainy','cloudy','windy','snowy','foggy'],
  drink: ['water','tea','coffee','juice','lemonade'],
  snack: ['popcorn','fruit','biscuits','nuts','sandwich'],
  sport: ['football','cricket','basketball','badminton','tennis'],
  hobby: ['reading','drawing','music','gaming','cooking','gardening'],
  genre: ['comedy','mystery','fantasy','sci-fi','adventure'],
  mood: ['happy','calm','excited','curious','sleepy'],
  element: ['fire','water','earth','air'],
  instrument: ['guitar','piano','drums','flute','violin'],
  number: ['1','2','3','4','5','6','7','8','9','10'],
  letter: [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'],
  coin: ['heads','tails'],
};
const random = make('random-pick', 'Random picks for games and ideas');
for (const name of Object.keys(randomLists)) random.addSubcommand(s => s.setName(name).setDescription(`Random ${name}`));

const numberOps = {
  add: ['Add two numbers', (a,b) => a+b], subtract: ['Subtract second from first', (a,b) => a-b], multiply: ['Multiply two numbers', (a,b) => a*b],
  divide: ['Divide first by second', (a,b) => a/b], power: ['First raised to second', (a,b) => a**b], remainder: ['Remainder of first divided by second', (a,b) => a%b],
  average: ['Average of two numbers', (a,b) => (a+b)/2], difference: ['Absolute difference', (a,b) => Math.abs(a-b)],
};
const calculate = make('calculate', 'Two-number calculations');
for (const [name,[desc]] of Object.entries(numberOps)) calculate.addSubcommand(s => s.setName(name).setDescription(desc).addNumberOption(o => o.setName('first').setDescription('First number').setRequired(true)).addNumberOption(o => o.setName('second').setDescription('Second number').setRequired(true)));
const outputNumber = n => Number.isFinite(n) ? String(Number(n.toPrecision(12))) : 'Invalid input or result outside supported range.';
module.exports = [
  { data: text, async execute(i) { try { return await reply(i, textOps[i.options.getSubcommand()][1](i.options.getString('text'))); } catch { return reply(i, 'Input invalid hai.'); } } },
  { data: math, async execute(i) { return reply(i, outputNumber(mathOps[i.options.getSubcommand()][1](i.options.getNumber('number')))); } },
  { data: convert, async execute(i) { return reply(i, outputNumber(conversionOps[i.options.getSubcommand()][1](i.options.getNumber('value')))); } },
  { data: random, async execute(i) { const list = randomLists[i.options.getSubcommand()]; return reply(i, list[randomInt(list.length)]); } },
  { data: calculate, async execute(i) { return reply(i, outputNumber(numberOps[i.options.getSubcommand()][1](i.options.getNumber('first'), i.options.getNumber('second')))); } },
];

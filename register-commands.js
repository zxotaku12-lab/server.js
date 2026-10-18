/**
 * Slash commands register karne ke liye (sirf ek baar chalana hai):
 *
 *   Render Dashboard -> Environment me set karo:
 *     DISCORD_TOKEN = Discord Developer Portal -> Bot -> Reset Token se copy karo
 *     CLIENT_ID     = General Information -> Application ID
 *
 *   Phir locally:  DISCORD_TOKEN=xxx CLIENT_ID=yyy npm run register
 *   (ya Render Shell me `npm run register`)
 *
 * Node 18+ chahiye (built-in fetch).
 */

const TOKEN = process.env.DISCORD_TOKEN;
const APP_ID = process.env.CLIENT_ID || process.env.APPLICATION_ID;

if (!TOKEN || !APP_ID) {
  console.error('DISCORD_TOKEN aur CLIENT_ID dono env vars chahiye.');
  process.exit(1);
}

const commands = [
  { name: 'ping', description: 'Check if the bot is alive' },
  { name: 'hello', description: 'Bot greets you' },
  { name: 'help', description: 'Show all commands' },
];

const res = await fetch(`https://discord.com/api/v10/applications/${APP_ID}/commands`, {
  method: 'PUT',
  headers: {
    Authorization: `Bot ${TOKEN}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify(commands),
});

if (!res.ok) {
  console.error('Failed:', res.status, await res.text());
  process.exit(1);
}

console.log('✅ Slash commands registered:', await res.json());

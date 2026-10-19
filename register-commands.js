/**
 * Slash commands ko Discord pe register karna (one-time)
 * ------------------------------------------------------
 * Normally ye zaroori NAHI hai — bot.js Gateway pe ready hote hi khud register kar deta hai.
 * Ye script tab kaam aati hai jab Gateway bot na chala rahe ho (sirf HTTP interactions endpoint).
 *
 * Env:
 *   DISCORD_TOKEN = Developer Portal -> Bot -> Reset Token se copy karo
 *   CLIENT_ID     = General Information -> Application ID
 *   GUILD_ID      = (optional) sirf us guild me register karo -> TURANT dikh jaati hain
 *                   (bina GUILD_ID ke global registration me 1 ghanta lag sakta hai)
 *
 * Chalane ka tarika:
 *   DISCORD_TOKEN=xxx CLIENT_ID=yyy npm run register
 *   DISCORD_TOKEN=xxx CLIENT_ID=yyy GUILD_ID=zzz npm run register
 *
 * Node 18+ chahiye (built-in fetch). Ye file CommonJS hai — top-level await jaan-boojh ke
 * avoid kiya gaya hai taaki Node 18 pe bhi SyntaxError na aaye.
 */

const { getCommands } = require('./commands');

const TOKEN = process.env.DISCORD_TOKEN;
const APP_ID = process.env.CLIENT_ID || process.env.APPLICATION_ID;
const GUILD_ID = process.env.GUILD_ID;

async function main() {
  if (!TOKEN || !APP_ID) {
    console.error('❌ DISCORD_TOKEN aur CLIENT_ID dono env vars chahiye.');
    console.error('   Example: DISCORD_TOKEN=xxx CLIENT_ID=yyy npm run register');
    process.exit(1);
  }

  const { json, names } = getCommands();
  if (!json.length) {
    console.error('❌ commands/ folder me koi command nahi mili.');
    process.exit(1);
  }

  const endpoint = GUILD_ID
    ? `https://discord.com/api/v10/applications/${APP_ID}/guilds/${GUILD_ID}/commands`
    : `https://discord.com/api/v10/applications/${APP_ID}/commands`;

  console.log(`⏫ ${json.length} commands register kar raha hoon -> ${GUILD_ID ? `guild ${GUILD_ID}` : 'GLOBAL'}`);

  const res = await fetch(endpoint, {
    method: 'PUT',
    headers: { Authorization: `Bot ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(json),
  });

  if (!res.ok) {
    const body = await res.text();
    console.error(`❌ Discord API ${res.status}: ${body}`);
    if (res.status === 401) console.error('👉 Token galat hai — Developer Portal -> Bot -> Reset Token.');
    if (res.status === 403) console.error('👉 Token ke paas applications.commands permission nahi hai.');
    if (res.status === 404 && GUILD_ID) console.error('👉 GUILD_ID galat hai, ya bot us server me nahi hai.');
    process.exit(1);
  }

  const created = await res.json();
  console.log(`✅ Registered (${Array.isArray(created) ? created.length : json.length}):`);
  for (const name of names) console.log(`   /${name}`);
  if (!GUILD_ID) console.log('ℹ️  Global commands dikhne me 1 ghanta tak lag sakta hai.');
}

main().catch((err) => {
  console.error('❌ Register fail:', err?.message ?? err);
  if (String(err?.message ?? '').includes('fetch failed')) {
    console.error('👉 Network/DNS issue — internet connection ya proxy check karo.');
  }
  process.exit(1);
});

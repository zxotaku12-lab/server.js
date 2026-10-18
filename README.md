# server.js — Discord Bot

Ek all-in-one Discord bot: **fun commands**, **welcome / auto-role**, **XP leveling** aur **utility** — do tarah se chalne layak:

- **HTTP Interactions server** (Express) — Gateway ke bina bhi slash commands chal jaati hain
- **Gateway client** (discord.js v14) — welcome messages, leveling, aur full bot features

Dono ek hi process me chal sakte hain: `DISCORD_TOKEN` set ho to Gateway bot apne aap start ho jaata hai, warna sirf HTTP server chalta hai.

## Slash commands

| Command | Kya karta hai |
|---|---|
| `/ping` | Bot alive hai ya nahi (Gateway ping ke saath, jab bot online ho) |
| `/hello` | Bot tumhe greet karta hai |
| `/help` | Saari commands ki dynamic list (embed) |
| `/8ball question:<sawal>` | Magic 8-Ball se jawaab |
| `/coinflip` | Heads ya tails |
| `/roll max:<number>` | Dice pheko (default 1–100) |
| `/rps choice:🪨/📄/✂️` | Rock-Paper-Scissors bot ke against |

Commands `commands/` folder me hain. Naya file daalo, command **apne aap** teen jagah pahunch jaati hai — Gateway bot, HTTP endpoint, aur `npm run register`. Dobara kahin hardcode nahi karna padta.

## Endpoints

| Route | Purpose |
|---|---|
| `POST /interactions` | Discord interactions endpoint (PING + slash commands + components) |
| `GET /` | Status page — live command list aur Gateway state ke saath |
| `GET /health` | Health JSON (uptime, commands, signature ON/OFF, gateway status) |
| `GET /commands` | Loaded commands ka Discord-shaped JSON (debug) |
| `GET /terms-of-service` | ToS page (Developer Portal ke liye) |
| `GET /privacy-policy` | Privacy Policy page (Developer Portal ke liye) |

## Setup

### 1. Environment variables

| Variable | Zaroori? | Kahan se |
|---|---|---|
| `DISCORD_TOKEN` | Gateway bot ke liye | Developer Portal → Bot → Reset Token |
| `DISCORD_PUBLIC_KEY` | **Recommended** | Developer Portal → General Information → Public Key |
| `CLIENT_ID` | `npm run register` ke liye | General Information → Application ID |
| `GUILD_ID` | Optional | Commands ko **turant** register karne ke liye (global me ~1 ghanta lagta hai) |
| `PORT` | Nahi | Render khud set karta hai |

`DISCORD_PUBLIC_KEY` set na ho to signature verification **skip** ho jaati hai (dev mode). Production me ise zaroor set karo.

### 2. Privileged Gateway Intents

Developer Portal → Bot → **Privileged Gateway Intents**:

- ✅ **SERVER MEMBERS INTENT** — welcome message + auto-role ke liye zaroori
- ⬜ **MESSAGE CONTENT INTENT** — zaroori **nahi** (XP sirf message gin-ta hai, content padhta nahi)
- `GUILD_MESSAGES` intent leveling ke liye chahiye (non-privileged, code me already enabled)

### 3. Render

- **Build Command:** `npm install`
- **Start Command:** `npm start`

Ek hi service me HTTP + Gateway dono chal jaayenge. Agar Discord Developer Portal me **Interactions Endpoint URL** set hai to Discord commands HTTP pe bhejta hai; URL hata do to Gateway pe. Bot dono raaste handle karta hai, isliye koi command "handle nahi hui" waali situation nahi aati.

## Local run

```bash
npm install
npm start                       # HTTP server (+ Gateway agar DISCORD_TOKEN hai)
DISCORD_TOKEN=xxx npm run bot   # sirf Gateway bot
```

## Register slash commands (one-time, optional)

Gateway bot ready hote hi commands khud register kar deta hai. Sirf HTTP mode me ye chalao:

```bash
DISCORD_TOKEN=xxx CLIENT_ID=yyy npm run register                  # global (~1 ghanta)
DISCORD_TOKEN=xxx CLIENT_ID=yyy GUILD_ID=zzz npm run register     # instant
```

## Self-check (bina Discord ke test)

```bash
npm run check
```

Ye ek asli ed25519 keypair bana kar server ko child process me start karta hai, phir **signed / unsigned / tampered** requests aur har slash command ko test karta hai (35 checks). Discord account ya token ki zaroorat nahi.

## Project layout

```
server.js              Express HTTP interactions server (+ Gateway boot)
bot.js                 discord.js Gateway client: welcome, auto-role, XP/leveling
commands/index.js      shared command registry (teeno consumers isi ko use karte hain)
commands/core.js       /ping /hello /help
commands/fun.js        /8ball /coinflip /roll /rps
lib/http-interaction.js  raw HTTP payload -> discord.js-jaisa interaction shim
register-commands.js   Discord API pe commands register karna
store.js               chhota JSON storage helper (data/ folder)
scripts/selfcheck.js   local end-to-end test harness
```

### Naya command kaise add karein

`commands/` me ek file banao:

```js
const { SlashCommandBuilder } = require('discord.js');

module.exports = {
  data: new SlashCommandBuilder().setName('dice').setDescription('Roll a dice'),
  async execute(interaction) {
    await interaction.reply(`🎲 ${1 + Math.floor(Math.random() * 6)}`);
  },
};
```

Bas. Registry use khud utha legi — Gateway, HTTP aur register script teeno me.

> **Note:** jo features sirf Gateway pe possible hain (role dena, kick/ban, `followUp`, `editReply`), wo HTTP mode pe clear error dete hain — chupchap fail nahi hote. Aise commands par `guildOnly: true` laga do to DM me bhi saaf message milega.

## Data storage

XP aur settings `data/*.json` me jaate hain (gitignored). Render ki free tier pe disk ephemeral hai — restart par data chala jaata hai. Persistent chahiye to koi DB (Mongo/Postgres) ya Render Disk laga lena.

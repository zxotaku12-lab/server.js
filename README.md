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
| `/kick user:<user> reason:[reason]` | 🔒 Member ko kick karo |
| `/ban user:<user> reason:[reason] delete_days:[0-7]` | 🔒 Member ko ban karo |
| `/timeout user:<user> minutes:<0-40320> reason:[reason]` | 🔒 Timeout karo / hatao (`minutes: 0`) |
| `/purge count:<1-100> user:[user]` | 🔒 Bulk-delete, optional user filter |
| `/setwelcome channel:[channel]` | ⚙️ Welcome channel set karo (khaali = band) · Manage Server |
| `/setautorole role:[role]` | ⚙️ Join pe auto-role (khaali = band) · Manage Roles |
| `/setlogs channel:[channel]` | ⚙️ Log channel — join/leave + mod actions · Manage Server |
| `/settings` | ⚙️ Current config dekho (sabke liye, koi permission nahi) |
| `/rank user:[user]` | 📊 Level, XP, rank aur next-level progress bar |
| `/leaderboard` | 🏆 Top 10 XP leaderboard |

🔒 = **Gateway-only**. Inhe asli `guild` object chahiye (roles, permissions, `bulkDelete`), jo HTTP interactions mode me nahi milta — wahan ye saaf message deti hain ki Gateway bot online karo, chupchap fail nahi hoti.

Har moderation command me ye sab built-in hai:

- `setDefaultMemberPermissions` + `setDMPermission(false)` → Discord UI bina permission waalon ko command dikhata hi nahi
- moderator **aur** bot dono ki permission check
- **role hierarchy** — apne se upar/braabar waale role ya server owner pe action refuse
- self-target aur bot-target refuse
- audit log reason me actor ka naam + ID
- log channel pe embed (agar settings me `logChannelId` ho)
- `/purge` count ko Discord ki 100 limit pe **clamp** karta hai, aur `deferReply` karta hai

Commands `commands/` folder me hain. Naya file daalo, command **apne aap** teen jagah pahunch jaati hai — Gateway bot, HTTP endpoint, aur `npm run register`. Dobara kahin hardcode nahi karna padta.

## 153 command actions

Bot me 50 top-level slash commands aur unke subcommands mila kar **153 invocable actions** hain (152 alag top-level slash commands nahi). Inme moderation, roles, welcome, leveling aur giveaways ke saath kaafi simple utility/timepass actions bhi shamil hain. Discord ki top-level slash command limit ko dhyan me rakh kar utilities group ki gayi hain:

- `/text-tools` — text transformations aur counts
- `/math-tools` — single-number math
- `/calculate` — two-number calculations
- `/convert` — unit conversions
- `/random-pick` — games aur ideas ke liye random categories

`/help` me har group ke subcommand names milte hain. Example: `/calculate add first:2 second:3`, `/convert km-miles value:10`, `/random-pick animal`. Gateway-only commands aur button giveaways ke liye Developer Portal se Interactions Endpoint URL hata kar Gateway bot use karein.

## Ticket system

`/ticket-panel staff:@Support category:Support` se panel bhejo (role aur category optional). Button se member ka private channel khulta hai, aur owner ya configured staff usko close kar sakte hain. Command ke liye Manage Server aur bot ko Manage Channels, category aur role overwrites manage karne ki permissions chahiye. Bot ka role staff role se upar rakhein aur channel/category me access dein. Ek member ka ek hi open ticket ho sakta hai. Panel ki staff/category settings server-wide hain; command dobara chalane se naye tickets ke liye latest settings apply hoti hain; existing ticket channels ke permissions automatically update nahi hote. Close karne par channel **delete** hota hai; transcript/backup nahi banta. Gateway bot online rakho aur Interactions Endpoint URL khaali rakho.

## Extra moderation aur timepass

- `/unban`, `/slowmode`, `/nickname`: respective Ban Members, Manage Channels ya Manage Nicknames permissions aur Gateway bot chahiye.
- `/warn`, `/warnings`, `/unwarn`: Moderate Members permission ke saath warning records manage karo; `/warnings` latest 10 dikhata hai. Warning data `data/warnings.json` me rehta hai; production me persistent disk zaroori hai.
- `/choose`, `/dice`, `/joke`, `/compliment`, `/motivation`, `/fortune`, `/rate`, `/reverse`, `/uppercase`, `/lowercase`, `/wordcount`, `/avatar`, `/timestamp` timepass aur utilities ke liye hain. `/help` current list dikhata hai.

## Naye role aur giveaway commands

- `/role-create name`, `/role-delete role`, `/role-add user role`, `/role-remove user role`: Manage Roles permission aur role hierarchy zaroori hai. Naya role bina permissions ke banta hai.
- `/giveaway-start prize minutes winners`: Manage Server permission se giveaway shuru karo; button se join/leave. `/giveaway-end message-id` se jaldi khatam karo. Gateway bot online hona chahiye aur Discord Developer Portal me Interactions Endpoint URL hataana hoga, taaki button interactions Gateway par aayein.
- Giveaways `data/giveaways.json` me save hote hain; restart ke baad scheduler pending giveaways resume karta hai. Persistent disk zaroori hai, warna deployment/restart par data kho sakta hai. Bot offline ho to result online aane par announce hota hai. Message ya channel delete hone ya permissions missing hone par announcement nahi hogi.

### Custom welcome embed

`/setwelcome channel:#welcome` se channel set karo. `/welcome-embed set` se title, description, hex color aur HTTPS image URL customize karo (sirf diye hue fields badlenge). Description/title me `{user}`, `{username}`, `{server}` aur `{count}` placeholders use kar sakte ho. `/welcome-embed preview` se private preview dekho, `/welcome-embed reset` se default embed wapas lao. Image remove karne ke liye `image:none` do. Commands ke liye Manage Server permission aur Gateway bot chahiye. Bot ko welcome channel me View Channel, Send Messages aur Embed Links permissions do; SERVER MEMBERS intent on rakho.

### Anti-nuke alerts

Server owner `/setlogs` ke baad `/antinuke on limit:3` se alerts enable kare. `/antinuke status` aur `/antinuke off` bhi available hain. Bot ko View Audit Log permission aur log channel par View Channel + Send Messages chahiye. 60 seconds me ek executor ke channel/role deletion, ban, kick, webhook creation ya bot addition ki combined limit cross hone par alert milta hai. Owner aur bot ke apne actions exempt hain.

**Default alert-only** hai. Owner `/antinuke on action:strip` se optional role removal enable kar sakta hai: threshold par bot executor ke manageable roles jinme dangerous permissions hain unhe remove karne ki koshish karta hai. Iske liye Manage Roles aur bot role hierarchy zaroori hai. False positives se legitimate staff ke roles bhi hat sakte hain; managed, higher roles aur @everyone ki permissions nahi hatengi. Ye actions block ya reverse nahi karta. Logs miss ho sakte hain jab bot offline ho, permission hat jaaye ya log channel delete ho; ye complete anti-nuke protection ka substitute nahi hai. Alert counters memory me hain aur restart par reset hote hain. Discord gateway use karein. Is project me **153 invocable command actions** hain: 50 top-level slash commands ke andar kai subcommands hain. `/help` se poori list dekho.

## Endpoints

| Route | Purpose |
|---|---|
| `POST /interactions` | Discord interactions endpoint (PING + slash commands + components) |
| `GET /` | Status page — live command list aur Gateway state ke saath |
| `GET /health` | Health JSON (uptime, commands, signature ON/OFF, gateway status) |
| `GET /commands` | Loaded commands ka Discord-shaped JSON (debug) |
| `GET /terms-of-service` | ToS page (Developer Portal ke liye) |
| `GET /privacy-policy` | Privacy Policy page (Developer Portal ke liye) |

## GitHub Actions: community bot (temporary runner)

Workflow **Community Bot (free runner)** Quest bot se alag hai. Repository Actions secrets me `COMMUNITY_DISCORD_TOKEN` (is bot ka alag token) aur optional `COMMUNITY_GUILD_ID` (server ID) set karo; secrets chat ya repository files me kabhi na likho. Quest bot ka token is workflow me use mat karo: ek hi application ke do bots ek saath command registrations overwrite kar sakte hain. Bot ke Developer Portal me Server Members Intent on aur Interactions Endpoint URL khaali rakho.

Workflow default branch me hone ke baad Actions tab se manually start kar sakte ho; schedule sirf default branch se chalta hai. Har 6 ghante par run attempt hota hai, aur process 5 ghante 45 minute baad band hota hai. Scheduling delays, repository inactivity, Actions limits aur usage charges ke kaaran offline gaps ya stoppage ho sakte hain; ye 24/7 hosting nahi hai. GitHub-hosted runner ephemeral hai: **XP, settings, warnings, giveaways aur ticket configuration har run ke baad mit jayenge**. Public repo me in data files ko Actions cache par save nahi karte, kyunki cache confidential storage nahi hai. Permanent data aur reliable hosting ke liye persistent disk/database ke saath host karein. Existing tickets ke channels Discord par rahenge, lekin bot configuration reset ho jayegi.

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

## Tests (bina Discord ke)

```bash
npm test               # chaaron suites (199 checks)
npm run test:mod       # moderation unit tests      (49)
npm run test:settings  # settings unit tests        (51)
npm run test:level     # leveling + XP maths tests  (63)
npm run check          # integration self-check     (36)
```

**`npm run check`** — ek asli ed25519 keypair bana kar server ko child process me start karta hai, phir **signed / unsigned / tampered** requests, har slash command aur saare pages test karta hai.

**`npm run test:mod`** — moderation commands ko asli `guild` chahiye jo Discord ke bina nahi milta, isliye guild/member/channel/permissions ke **mocks** banake `execute()` ko directly call karta hai. Isse real logic test hota hai: permission denial, role hierarchy, owner/self/bot protection, `delete_days → deleteMessageSeconds` conversion, 100-message clamp, user-filtered bulk delete, bulkDelete failure handling, aur log-channel integration.

**`npm run test:settings`** — settings commands ke liye, aur specially isliye kyunki HTTP mode me `guild` object nahi milta. Test karta hai ki Discord ke `member.permissions` **string** se permission enforcement REAL rehti hai (koi bhi settings na badal sake), Gateway mode me channel/role validation, `@everyone` aur role-hierarchy guards, cross-guild channel refusal, cache coherence (command likhe to bot.js ko turant dikhe), multi-guild isolation, aur ek regression sweep jo har reply me `[object Object]` / `undefined` leak pakadta hai.

**`npm run test:level`** — XP maths (`level = floor(0.1·√xp)`, level boundaries, progress %, bar rendering) aur `/rank` + `/leaderboard` — sorting, medals, top-10 cap, khaali/corrupt store, DM refusal, aur HTTP mode.

Sab suites exit code 1 dete hain fail hone par, isliye CI (`.github/workflows/ci.yml`) inhe Node **18 / 20 / 22** pe chalata hai.

> Tests jaan-boojh ke mocks use karte hain — asli Discord ke bina permission checks, role hierarchy aur XP maths verify karne ka yahi ek raasta hai. Is sandbox se `discord.com` reachable nahi hai.

## Project layout

```
server.js              Express HTTP interactions server (+ Gateway boot)
bot.js                 discord.js Gateway client: welcome, auto-role, XP/leveling
commands/index.js      shared command registry (teeno consumers isi ko use karte hain)
commands/core.js       /ping /hello /help
commands/fun.js        /8ball /coinflip /roll /rps
commands/mod.js        /kick /ban /timeout /purge  (Gateway-only, permission + hierarchy checks)
commands/settings.js   /setwelcome /setautorole /setlogs /settings
commands/level.js      /rank /leaderboard
lib/http-interaction.js  raw HTTP payload -> discord.js-jaisa interaction shim
lib/perms.js           permission checks — Gateway objects AUR HTTP `member.permissions` string dono se
lib/settings.js        guild settings ka SHARED cache (bot.js + commands dono isi ko use karte hain)
lib/levels.js          XP -> level maths aur progress bar (ek hi jagah, taaki kabhi disagree na ho)
lib/xp.js              XP store reads + leaderboard/rank computation
register-commands.js   Discord API pe commands register karna
store.js               chhota JSON storage helper (data/ folder)
scripts/selfcheck.js   integration test harness (HTTP + signatures)
scripts/mod.test.js    moderation unit tests (mock guild)
scripts/settings.test.js  settings unit tests (HTTP permission strings, cache coherence)
scripts/level.test.js  leveling + XP maths tests

python-bot/            ALAG project: Gogeta's Pet (discord.py) — is Node bot se independent
```

## Python bot (Gogeta's Pet)

`python-bot/` me ek **alag** project hai — `discord.py` v2 wala Gogeta's Pet bot (moderation, AutoMod, Anti-Nuke/Anti-Betray, tickets, giveaways, applications, invites, logs, embed builder, AI router). Ye is Node bot se koi file share nahi karta aur iske bina bhi independently chalta hai.

```bash
cd python-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # TOKEN + GOGETAS_PET_OWNER_ID bharo
python check_deploy.py        # preflight
python bot.py
```

Tests: `python -m pytest -q` (60 tests) aur `python tests/smoke_cogs.py` (saare cogs offline load). Poora detail, structure aur env table `python-bot/README.md` me hai; command list `python-bot/COMMANDS.md`.

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

> **Note:** jo features sirf Gateway pe possible hain (role dena, kick/ban, `followUp`, `editReply`), wo HTTP mode pe clear error dete hain — chupchap fail nahi hote. Aise commands par `guildOnly: true` laga do to DM me bhi saaf message milega. `commands/mod.js` iska reference implementation hai.

Moderation commands ke liye bot ke role ko target roles se **upar** rakho aur ye permissions do: Kick Members, Ban Members, Moderate Members, Manage Messages.

## Data storage

XP aur settings `data/*.json` me jaate hain (gitignored):

- `data/settings.json` — `{ "<guildId>": { welcomeChannelId, memberRoleId, logChannelId } }`
- `data/xp.json` — `{ "<guildId>:<userId>": { xp, username } }`

Settings ka cache `lib/settings.js` me **shared** hai — pehle wo `bot.js` ke andar tha, jiski wajah se koi command settings badalti to bot ka cache stale reh jaata aur welcome/auto-role/logs kabhi update na hote. Ab command likhti hai to bot ko turant dikhta hai.

> ⚠️ Render ki free tier pe disk **ephemeral** hai — restart par XP aur settings chale jaayenge. Persistent chahiye to Render Disk laga lo, ya koi DB (Mongo/Postgres) — `store.js` ek hi jagah hai, swap karna aasaan hai.

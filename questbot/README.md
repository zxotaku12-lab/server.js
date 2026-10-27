# 🎯 Quest Bot

Standalone Discord quest bot — **daily / weekly / one-time quests**, **free premium**, aur ek **browser dashboard**
jisme token paste karke bot link hota hai aur **access kisi ko bhi diya ja sakta hai**.

> ⭐ Premium **bilkul free** hai. Koi payment nahi, koi grind nahi — member `/premium` chala ke ek click me le leta hai.
> Bot kabhi kisi se paisa nahi maangta.

---

## Quick start

```bash
cd questbot
npm install
npm start
```

Terminal me dashboard URL aur (pehli baar) **owner password** print hoga:

```
[server] Dashboard live: http://0.0.0.0:3000
┌──────────────────────────────────────────────┐
│  DASHBOARD PASSWORD (pehli baar bani — save!) │
│  xY7kQ2mP9a                                 │
└──────────────────────────────────────────────┘
```

1. Dashboard kholo → password daalo
2. Discord Developer Portal → **Bot → Reset Token** se token copy karo
3. Dashboard ke **Overview** me token paste karke **"Link bot"** dabao — bot live 🚀
4. Discord me `/quest` chalao

`DASHBOARD_PASSWORD` env set kar do to apna password use hoga (recommended):

```bash
DASHBOARD_PASSWORD=mera-password npm start
```

### Bot intents (zaroori)

Developer Portal → Bot → **Privileged Gateway Intents** me ON karo:

- ✅ **Server Members Intent** — invites / member count / premium lookup
- ✅ **Message Content Intent** — quest progress (messages) + XP

---

## Commands

| Command | Kya karta hai |
|---|---|
| `/quest [user]` | Aaj ke daily quests + progress + claim button |
| `/questlist [type]` | Poora quest catalog (`all` / `daily` / `premium` / `weekly` / `once`) |
| `/questall` | Daily + weekly + one-time — sab ek saath, ek click me claim |
| `/questtop` | Server ka quest leaderboard (top 10) |
| `/premium` | ⭐ Premium **free** me activate (button) |

Quest complete karna apne aap hota hai — messages, reactions, VC minutes, bot commands aur invites count hote hain.

### ⚡ Unlimited mode — sab ek saath, koi grind nahi

Dashboard → **Quests** tab → **⚡ Unlimited ON karo**. Ya env se hamesha ON:

```bash
QUEST_UNLIMITED=1 npm start
```

ON hone par:

| Normal | Unlimited |
|---|---|
| Daily 3 rotate | **Poore 10 daily** ek saath |
| Priority premium +2 | **Poore 3 premium** (premium walon ko) |
| Weekly 2 rotate | **Poore 5 weekly** |
| Grind karke complete karo | **Sab turant complete** |
| `/questall` = jitne complete hue | `/questall` = **saare (20+) ek click me** |

Ek click me poori reward (~780 🪙 + 460 XP bina premium, ~1000+ premium ke saath).
Reward **har period me ek baar** milta hai — daily roz reset, weekly har hafte, one-time ek dafa.
(Isse coins/leaderboard ka matlab bana rehta hai; warna infinite farm ban jaata.)

### Quest types

| Type | Rotation | Example |
|---|---|---|
| 📅 Daily | Har din **3** quests (UTC midnight reset) | 15 messages, 5 reactions, 10 VC minutes |
| ⭐ Premium daily | Premium walon ko **+2** extra | 75 messages, 45 VC minutes, 3 invites |
| 🗓️ Weekly | Har hafte **2** quests (Monday reset) | 250 messages, 120 VC minutes |
| 🎖️ One-time | Kabhi bhi | pehla message / pehla invite… |

Rotation deterministic hai — sab members ko same din same quests milti hain, par roz badalti hain.
Rewards: **coins + XP** (premium par ×1.5).

---

## Dashboard

| Tab | Kya hai |
|---|---|
| **Overview** | Bot status (ready / connecting / error), token paste karke link, **commands connect**, **invite link**, stop / restart, premium dena, live stats, reset timers |
| **Quests** | Aaj ke daily + weekly quests aur poora catalog |
| **Leaderboard** | Players, quests, coins, level, streak |
| **Access** | 🔑 Naye access keys banao aur kisi ko bhi do (owner only) |

### ⌨️ Commands ko bot se connect karna

Bot ready hote hi commands **apne aap** register ho jaati hain. Dashboard ke **Overview** me do buttons hain:

- **⌨️ Commands connect karo** — abhi turant register (dobara try karne / refresh ke liye). `GUILD_ID` set ho to
  us server me instant, warna global (~1 ghanta).
- **🔗 Bot ko server me add karo** — invite link jisme `applications.commands` scope + zaroori permissions hain.

> ⚠️ Sabse common problem: bot ko **galat invite link** se add karna (bina `applications.commands` scope).
> Tab commands register to ho jaati hain par server me dikhti nahi. Isliye dashboard ka invite button hi use karo.

### 🔑 Access kisko de sakte ho

Owner dashboard ke **Access** tab se keys banata hai:

| Role | Kya kar sakta hai |
|---|---|
| **Owner** (password) | Sab kuch + access keys banana / revoke karna |
| **Admin** (`adm_…`) | Bot start/stop/restart, premium dena, sab dekhna |
| **Viewer** (`vw_…`) | Sirf dekhna (status, quests, leaderboard) |

- Key **sirf ek baar** dikhti hai — copy karke bhej do
- **Disable** ya **Revoke** karte hi us key ke saare active sessions band ho jaate hain
- 12 ghante ke session, 10 minute me 12 se zyada galat attempts par rate-limit

---

## Env variables

| Variable | Default | Kya karta hai |
|---|---|---|
| `DISCORD_TOKEN` | — | Bot token (optional — dashboard se bhi paste kar sakte ho) |
| `GUILD_ID` | — | Commands us server me **turant** register (warna global, ~1 ghanta) |
| `DASHBOARD_PASSWORD` | auto | Owner password |
| `PORT` | `3000` | Server port (Render khud set karta hai) |
| `QUEST_DATA_DIR` | `questbot/data` | Data folder (tests isko override karte hain) |

---

## Data / privacy

Sab kuch local JSON me:

```
data/quests.json   -> users: coins, xp, premium, counters, claimed, stats
data/config.json   -> bot token, owner password, access keys
```

- Bot token sirf tumhare server pe rehta hai, kahin bheja nahi jaata
- Dashboard **HttpOnly + SameSite** cookie use karta hai, password timing-safe compare hota hai
- `data/` gitignored hai — repo me kabhi commit nahi hoga

---

## Tests

```bash
npm test        # 96 unit tests — rotation, counters, claim, premium, unlimited, access
npm run check   # 63 E2E checks — boot, login, permissions, commands, unlimited, keys
```

Dono bina Discord token ke chalte hain (isolated temp data dir).

---

## Deploy

Bot ko Discord se connect hone ke liye **internet chahiye** — kisi bhi aise sandbox/preview me jo discord.com
block karta hai, wahan bot `off` rahega (dashboard chalega, par link nahi hoga).

### Apne PC pe (sabse simple)

```bash
cd questbot
npm install
DASHBOARD_PASSWORD=mera-password npm start
# http://localhost:3000 -> token paste -> Link bot
```

### Docker / VPS

```bash
cd questbot
docker build -t questbot .
docker run -d --restart unless-stopped \
  -p 3000:3000 \
  -e DASHBOARD_PASSWORD=mera-password \
  -v questbot-data:/app/data \
  questbot
```

### Render (blueprint ready)

Repo me `questbot/render.yaml` hai — Render → **New → Blueprint** → repo choose karo, `DASHBOARD_PASSWORD`
set karo, deploy. Dashboard URL mil jaayega.

> ⚠️ Free plan thodi der me sleep karta hai, aur bot ko 24/7 gateway connection chahiye — ya to paid instance
> rakho ya VPS / Oracle free-tier VM use karo (`docker run ... --restart unless-stopped`).

---

## 🔐 Token safety

- Bot token **password jaisa** hota hai — jise bhi do, wo tumhara bot poora control kar sakta hai
- Token **chat me paste nahi karna chahiye**. Agar kabhi ho gaya, turant
  **Developer Portal → Bot → Reset Token** se naya lo (purana turant invalid ho jaata hai)
- Ye bot token sirf `data/config.json` me save karta hai (gitignored) — repo me kabhi commit nahi hota
- Shared hosting pe `DASHBOARD_PASSWORD` strong rakho; bahar waalon ko sirf `viewer` key do

---

## Structure

```
questbot/
├── src/
│   ├── index.js            # Express server + dashboard APIs
│   ├── commands/           # /quest /questlist /questall /questtop /premium
│   ├── events/             # message/reaction/voice/invite/interaction -> progress
│   └── lib/
│       ├── access.js       # access keys, roles, sessions
│       ├── bot.js          # token se start/stop/restart
│       ├── quests.js       # pools, rotation, claim logic
│       ├── users.js        # coins, xp, premium, counters
│       ├── periods.js      # daily/weekly keys
│       ├── levels.js       # level maths
│       └── store.js        # JSON store (debounced, atomic)
├── public/                 # dashboard (vanilla HTML/CSS/JS, koi build nahi)
└── scripts/                # test.js + selfcheck.js
```

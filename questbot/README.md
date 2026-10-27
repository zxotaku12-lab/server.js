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
| **Overview** | Bot status (ready / connecting / error), token paste karke link, stop / restart, premium dena, live stats, reset timers |
| **Quests** | Aaj ke daily + weekly quests aur poora catalog |
| **Leaderboard** | Players, quests, coins, level, streak |
| **Access** | 🔑 Naye access keys banao aur kisi ko bhi do (owner only) |

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
npm test        # 80 unit tests — rotation, counters, claim, premium, access
npm run check   # 45 E2E checks — server boot, login, permissions, keys, premium
```

Dono bina Discord token ke chalte hain (isolated temp data dir).

---

## Deploy (Render / Railway / VPS)

1. Repo push karo, service ka root `questbot` rakho
2. Build: `npm install` · Start: `npm start`
3. Env me `DASHBOARD_PASSWORD` (+ optionally `DISCORD_TOKEN`, `GUILD_ID`) set karo
4. Deploy ke baad dashboard URL kholo

> Bot ko 24/7 online rehna chahiye (gateway connection), isliye Render ke free plan me sleep se bachne ke liye
> paid instance ya VPS use karna better hai.

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

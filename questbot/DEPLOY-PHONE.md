# 📱 Sirf phone se Quest Bot chalao

Laptop ki zaroorat nahi — neeche ke teen me se **koi ek** tarika choose karo.
Sab kuch browser (Chrome/Safari) se ho jaata hai.

---

## 0. Pehle: naya token lo (2 min) ⚠️

Purana token chat me aa gaya tha, use **dead maano**:

1. [discord.com/developers/applications](https://discord.com/developers/applications) kholo (phone browser, desktop site mode better)
2. Apni app → **Bot** → **Reset Token** → **Yes, do it**
3. Naya token **copy** karo — kisi chat me mat bhejna

Saath hi **Bot → Privileged Gateway Intents** me ye ON karo:
- ✅ **Server Members Intent**
- ✅ **Message Content Intent**

**Save** dabao.

---

## Option A — GitHub Actions (FREE, 5 minute) ✅ recommended

Bilkul free, koi card nahi. Bot har 6 ghante me restart hota hai (beech me ~10 min gap).
**Dashboard ka public URL nahi milega**, par Discord me saari commands kaam karengi.

1. GitHub app/browser me apna repo kholo → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**:
   - Name: `DISCORD_TOKEN`
   - Secret: naya token paste karo → **Add secret**
3. Optional (commands turant register hongi): dusra secret `GUILD_ID` = tumhare server ki ID
   (Discord app → Server Settings → Widget → Server ID, ya desktop pe right-click)
4. **Actions** tab → left me **Quest Bot (free runner)** → **Run workflow** → **Run**
5. ~1 min me green tick ✅ — aur Discord me `/quest` chala ke dekho

> Actions free minutes khatam ho jaayein to bot ruk jaata hai — tab Option B pe shift ho jao.

---

## Option B — Render (24/7 + dashboard URL, paid ~$7/mo)

Phone se poori setup:

1. [render.com](https://render.com) → **Get Started** → **GitHub** se sign in karo
2. **New +** → **Blueprint**
3. Repo choose karo (`zxotaku12-lab/server.js`) → **Connect**
4. Render `render.yaml` khud padh lega. **DASHBOARD_PASSWORD** maange to apna strong password daalo
   (optional: `DISCORD_TOKEN` bhi daal do to bot seedha start hoga)
5. **Apply** → deploy hone do (~2 min)
6. Dashboard URL milega: `https://questbot-xxxx.onrender.com` → phone pe kholo →
   password daalo → **Overview** me token paste (agar env me nahi daala) → **Link bot**

> `plan: starter` isliye rakha hai ki data (coins/premium/access keys) restart par na ude.
> Free plan pe disk nahi milti — restart par sab reset ho jaata hai.

---

## Option C — Railway (simple, trial credits)

1. [railway.app](https://railway.app) → **Login with GitHub**
2. **New Project** → **Deploy from GitHub repo** → apna repo
3. Project → **Settings** → **Root Directory** = `questbot`
4. **Variables**:
   - `DISCORD_TOKEN` = naya token
   - `DASHBOARD_PASSWORD` = apna password
   - `QUEST_DATA_DIR` = `/data` (aur **Add Volume** → mount path `/data`)
5. **Deploy** → URL milega → usi pe dashboard khulega

---

## Deploy ke baad (Discord me)

| Command | Kya |
|---|---|
| `/quest` | Aaj ke quests + claim button |
| `/questlist` | Poora catalog |
| `/questall` | Daily + weekly + one-time — sab ek saath claim |
| `/questtop` | Leaderboard |
| `/premium` | ⭐ Premium **free** — ek click |

### Commands "add" karna (Developer Portal me nahi hota)

Developer Portal me commands add karne ki jagah **nahi** hai — wo portal ka feature hi nahi. Commands sirf
**API se register** hoti hain, aur ye bot khud kar deta hai. Aage apne aap:

1. Bot start hua → commands register ✅
2. Agar na ho → Dashboard → **⌨️ Commands connect karo**
3. Bot chal hi nahi raha? → GitHub → **Actions** → **Register commands** → **Run workflow**
   (ek baar `DISCORD_TOKEN` secret daalna hoga; optional input me server ID daal do to turant dikhengi)

**Commands nahi dikh rahe?** (sabse common problem)
1. Dashboard **Overview** → **🔗 Bot ko server me add karo** dabao — is link me `applications.commands` scope hai.
   (Developer Portal se manually banaya link agar sirf `bot` scope ka tha, to commands kabhi dikhengi nahi.)
2. Phir **⌨️ Commands connect karo** dabao — status pill me "registered" dikhna chahiye.
3. Global commands me ~1 ghanta lagta hai → `GUILD_ID` env set karo to turant aayengi.
4. Discord app ko **poori tarah band karke** kholo (commands cache hoti hain).
5. Bot offline dikh raha hai → **Server Members Intent** ON hai ya nahi check karo.

---

## Kya-chahiye quick map

| Tumhe chahiye | Option |
|---|---|
| Bilkul free, commands kaafi hain | **A (Actions)** |
| 24/7 online + dashboard ka link dusron ko dena | **B (Render)** |
| Free trial ke saath aasan setup | **C (Railway)** |

---

## Security (phone pe bhi important)

- Token = bot ka password. Kabhi kisi chat me nahi.
- Dashboard keys: sirf **viewer** do bahar waalon ko, **admin** sirf bharose waalon ko
- Access tab se **Revoke** karte hi uska access turant band

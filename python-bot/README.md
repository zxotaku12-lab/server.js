# Gogeta's Pet — Python bot (`discord.py`)

Ye is repo ke andar rakha gaya **Python wala Gogeta's Pet bot** hai (upar `server.js` / `bot.js` wala Node bot alag hai, dono ek dusre ko touch nahi karte).

`discord.py` v2 based, slash + prefix dono, SQLite state, AI provider router, moderation/security/tickets/giveaway/apply/invites sab included.

---

## Structure

```
python-bot/
├── bot.py                      # entrypoint: prefix, cogs loader, owner bypass, startup
├── activity.py                 # inactivity DB layer (sqlite)
├── inactivity.py               # daily inactivity scan + manual kick pass
├── banner.py                   # console banner (credits: gogeta_gg)
├── env_loader.py               # .env loader jo decorative headers ignore karta hai
├── command_collision_guard.py  # legacy MultiAI command rename guard
├── check_deploy.py             # preflight: token + required files check
├── requirements.txt
├── pytest.ini
├── .env.example
├── cogs/                       # 21 extensions + 21 helper/db/view modules
├── ui/                         # embeds, emoji registry, pagination, theme, rendering
├── knowledge/
│   ├── ticket_ai.md            # TicketAI ki canonical server knowledge
│   └── servers/                # per-guild knowledge (.md), runtime data
├── tests/                      # pytest suite + offline cog-load smoke test
└── docs/ai_intelligence_engine.md
```

`bot.py` khud `cogs/*.py` scan karta hai — jis file me module-level `setup()` hai wahi extension banti hai, baaki helper modules skip ho jaate hain. Isliye naya cog add karne ke liye kisi list me entry nahi karni, bas `cogs/` me file daal do.

---

## Quickstart

```bash
cd python-bot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # phir .env me TOKEN + GOGETAS_PET_OWNER_ID bharo
python check_deploy.py             # preflight (secrets print nahi karta)
python bot.py
```

Pehli baar chalane pe runtime DB files khud ban jayengi (`activity.db`, `cogs/*.db`) — wo gitignored hain.

### Zaroori env

| Variable | Kya hai |
|---|---|
| `TOKEN` | Bot token (required) |
| `GOGETAS_PET_OWNER_ID` | Bot owner ka numeric Discord ID |
| `CREATOR_USER_ID` | "dad"/creator persona target |
| `EMOJI_SOURCE_GUILD_ID` | Custom emoji copy karne wala guild |
| `AI_PROVIDER_ORDER` + koi ek `*_API_KEY` | AI replies ke liye (e.g. `OPENAI_API_KEY`) |
| `TICKET_PANEL_CHANNEL_ID` | Persistent ticket panel ka channel |

Baaki saare knobs (AI tuning, TicketAI, QuestBot/invite, logs) `.env.example` me defaults ke saath documented hain.

---

## Commands ko Discord pe register karna

`bot.py` jab start hota hai tab khud `setup_hook` me saari cogs load karke `tree.sync()` karta hai — matlab **normal run me commands apne aap connect ho jaate hain**. Sirf ek baar push karna hai, bot chalaye bina:

```bash
# test server pe instant (guild scope turant dikhta hai)
python scripts/sync_commands.py --guild <GUILD_ID>

# poore bot ke liye global (propagate hone me ~1 ghanta)
python scripts/sync_commands.py

# scope se commands hatao
python scripts/sync_commands.py --guild <GUILD_ID> --clear
```

Script wahi rule use karta hai jo `bot.py` use karta hai (sirf `setup()` wali files), token `.env` ke `TOKEN` se padhta hai, aur sync se peile batata hai kitni commands local me mili.

> Note: global aur guild scope alag hote hain. Guild me sync karne se sirf usi server me commands dikhengi; global sync sab jagah jaata hai (thoda late).

### GitHub Actions se sync (optional)

Bot ko host karne ke bajaye commands CI se register karne hain to:

```bash
# value prompt me paste hoti hai — chat/shell history me nahi jaati
gh secret set DISCORD_TOKEN
gh secret set DISCORD_GUILD_ID
```

Phir **Actions → “Sync slash commands” → Run workflow** (guild ya global chuno). Workflow manual-only hai (`workflow_dispatch`), kisi push pe apne aap nahi chalta, aur token ko kabhi print nahi karta.

⚠️ Secret me wo token daalo jo **naya** ho. Chat/issue me share ho chuka token reset karwao: Developer Portal → Application → Bot → *Reset Token*.

---

## Website (static docs + command explorer)

`website/` pure static hai — koi build step nahi, koi dependency nahi:

```bash
python scripts/gen_site_data.py     # website/commands.json ko asli cogs se regenerate karo
python3 -m http.server 8000 --directory website   # http://localhost:8000
```

Content: hero + feature cards, **command explorer** (search, type filter, cog sidebar, copy-to-clipboard), 4-step setup guide, aur **Connect** section jo Client ID + Guild ID se invite link banata hai (values sirf browser ke localStorage me rehti hain — token wahan kabhi nahi). GitHub Pages / Render static site / kisi bhi bucket pe seedha host ho jayega.

`commands.json` generated hai, isliye cog add karne ke baad `gen_site_data.py` dobara chalao (CI isko verify karta hai).

---

## Tests

```bash
python -m pytest -q                # 60 tests
python tests/smoke_cogs.py         # token/network ke bina saare cogs load test
```

`tests/smoke_cogs.py` wahi rule use karta hai jo `bot.py` use karta hai, aur duplicate command names / broken imports / tuta `setup()` turant pakad leta hai. `cv2_test` (interactive Components V2 demo) default me skip hota hai — `ENABLE_CV2_TEST_COG=true` se on karo.

---

## Setup ke waqt jo cheezein theek ki gayin

1. **`requirements.txt`** — `audioop-lts==0.2.2` sirf Python 3.13+ ke liye hai, isliye `; python_version >= "3.13"` marker lagaya. Warna 3.11/3.12 pe `pip install -r requirements.txt` shuru me hi fail hota hai.
2. **Tests `tests/` me** — test files `Path(__file__).resolve().parents[1]` se project root nikalte hain (aur `harness_am.py` bhi saath chahiye), isliye wo `tests/` subfolder me hi rehte hain; root me rakne se saare path-based checks galat root dhoondhte.
3. **`tests/test_chaos_conversation_integration.py`** — ye purane `MultiAI.ask()` API pe likha tha, jo ab `ask_custom()` ban chuka hai (code me comment bhi hai: *"ask_custom remains available to TicketAI; GogetasPet is the sole general-chat owner"*). Test ko current contract pe align kiya, assertions wahi hain (provider selection, policy prompt reaching provider, output budget + reasoning headroom, stats, aur "MultiAI koi second reply generate nahi karta"). Ek extra test bhi add kiya: bot-authored messages hi quest-hint path pe jaate hain.
4. **`knowledge/ticket_ai.md`** — `TICKET_AI_KNOWLEDGE` ka default path yahi hai, isliye uploaded doc ko `knowledge/ticket_ai.md` pe rakha (aur `docs/` me `ai_intelligence_engine.md`).

### Optional (missing ho to bhi chalta hai)

- `assets/help_banner.png` — `/help` ka banner; na ho to help embed bina image ke chalta hai.
- `ui/assets/fonts/Inter-Bold.ttf`, `Inter-SemiBold.ttf`, `Inter-Regular.ttf` — image cards (`/invites check`) ke liye; na ho to system font / Pillow bitmap fallback.

### Known loose ends

- `bot.py` ki exclusion list me `spam_whitelist_db.py` likha hai, par wo module is build me nahi hai (koi cog bhi use nahi karta).
- `cogs/automod_db.py` kisi bhi cog se import nahi hota — AutoMod v3 apna `cogs/automod_v2.db` khud manage karta hai. Legacy file lagti hai.

---

## Deployment (short)

- Host pe Python 3.11+ (3.13 pe `audioop-lts` khud aa jayega).
- `python bot.py` ko kisi process manager se chalao (systemd / pm2 / panel), working directory `python-bot/` rakho taaki `.env`, `knowledge/` aur DB paths resolve hon.
- SQLite files writable hone chahiye (`activity.db`, `cogs/*.db`).
- Message Content intent Discord Developer Portal me on karna zaroori hai (AutoMod, ghostping, AI chat sab isi pe depend karte hain).

Credits: **gogeta_gg**

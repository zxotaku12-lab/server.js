# server.js
A powerful Discord bot for moderation, welcome, leveling, utility and community management

Currently: an **HTTP Interactions** server for Discord (no Gateway needed).

## Endpoints
| Route | Purpose |
|---|---|
| `POST /interactions` | Discord interactions endpoint (PING + slash commands) |
| `GET /` | Status page |
| `GET /health` | Health check JSON |
| `GET /terms-of-service` | ToS page (Developer Portal) |
| `GET /privacy-policy` | Privacy Policy page (Developer Portal) |

## Slash commands
`/ping`, `/hello`, `/help`

## Render setup
- **Build Command:** `npm install`
- **Start Command:** `npm start`
- **Environment variables:**
  - `DISCORD_PUBLIC_KEY` — Discord Developer Portal → General Information → Public Key *(recommended, enables signature verification)*
  - `DISCORD_TOKEN`, `CLIENT_ID` — only needed for `npm run register` (slash command registration)

## Local run
```bash
npm install
npm start
```

## Register slash commands (one-time)
```bash
DISCORD_TOKEN=xxx CLIENT_ID=yyy npm run register
```

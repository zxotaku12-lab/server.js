# Credits: gogeta_gg
"""Canonical custom emoji registry for Gogeta's Pet.

Only the approved custom emoji names are rendered by the non-AI Discord UI.
The source guild is configurable through .env and is refreshed periodically.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import aiohttp

# Exact approved source names supplied by the server owner.
ALLOWED_NAMES = frozenset({
    "q_xp", "q_member", "q_streak", "q_online", "q_offline", "q_plus",
    "q_party", "q_star", "q_report", "q_premium", "q_win", "q_staff",
    "q_success", "q_rocket", "diamond", "flair2", "blackhole", "cyanodt",
    "purpledot", "pinkdot", "cancle", "q_owner", "q_mod", "q_role", "q_vip",
    "q_unmute", "q_trophy", "q_safe", "q_vitro", "q_search", "q_presence",
    "q_ticket", "q_verified", "q_verify", "q_backup", "q_bot", "q_arrow_down",
    "q_afk", "q_gem", "q_boost", "q_confetti", "q_arrow_up", "q_diamond",
    "q_heart", "q_quest", "q_unlink", "q_protection", "q_minus", "q_user",
    "q_rank", "q_sync", "q_paste", "q_sparkle", "q_reward", "q_shield",
    "q_nuke", "q_security", "q_mission", "q_time", "q_antinuke", "q_admin",
    "q_coin", "q_levelup", "q_audit", "q_medal", "q_arrow_left", "q_error",
    "q_giveaway", "q_cross", "q_invite", "q_info", "q_check", "q_clock",
    "q_complete", "q_arrow", "q_gg", "q_firewall", "q_lock", "q_key", "q_fire",
    "q_arrow_right", "q_emergency", "q_ban", "q_love", "q_danger", "q_link",
    "q_loading", "q_chest", "q_cleanup", "q_hype", "q_celebrate", "q_crown",
    "q_calendar", "q_copy", "q_coins", "q_kick", "q_challenge", "q_logs",
})

# Internal compatibility aliases. They never render an unapproved name.
ALIASES = {
    "cancel": "cancle",
    "q_danger": "q_error",
    "cyanodot": "cyanodt",
}

_CACHE: dict[str, str] = {}
_META: dict[str, dict[str, Any]] = {}
_SOURCE_GUILD_ID: int | None = None
_REFRESH_TASK: asyncio.Task | None = None


def _name(name: str) -> str:
    key = str(name).strip().strip(":").lower()
    return ALIASES.get(key, key)


def set_emojis(payload: list[Any]) -> dict[str, int]:
    global _CACHE, _META
    cache: dict[str, str] = {}
    meta: dict[str, dict[str, Any]] = {}

    for item in payload:
        if isinstance(item, dict):
            name = _name(item.get("name", ""))
            emoji_id = item.get("id")
            animated = bool(item.get("animated"))
        else:
            name = _name(getattr(item, "name", ""))
            emoji_id = getattr(item, "id", None)
            animated = bool(getattr(item, "animated", False))

        if name not in ALLOWED_NAMES:
            continue
        try:
            emoji_id = int(emoji_id)
        except (TypeError, ValueError):
            continue

        prefix = "a" if animated else ""
        cache[name] = f"<{prefix}:{name}:{emoji_id}>"
        meta[name] = {"id": emoji_id, "animated": animated}

    _CACHE = cache
    _META = meta
    return {"loaded": len(cache), "allowed": len(ALLOWED_NAMES), "missing": len(ALLOWED_NAMES - set(cache))}


def E(name: str) -> str:
    """Return an approved source emoji, or a safe fallback.

    Falls back to the approved q_info icon when the requested name isn't
    loaded — but if q_info itself is also missing, that fallback would
    otherwise resolve to an empty string, and an empty string embedded in
    a button/select-option emoji field is what makes Discord reject the
    whole component with a 400 (this is exactly what broke /devreact and
    /ownreact). A plain unicode character can never be "missing" the same
    way, so it's the true floor — nothing downstream of E() should ever
    receive "".
    """
    key = _name(name)
    return _CACHE.get(key) or _CACHE.get("q_info") or "❔"


text = E


def loaded() -> int:
    return len(_CACHE)


def source_guild_id() -> int | None:
    return _SOURCE_GUILD_ID


def status() -> dict[str, Any]:
    return {
        "source_guild_id": _SOURCE_GUILD_ID,
        "loaded": len(_CACHE),
        "allowed": len(ALLOWED_NAMES),
        "missing": sorted(ALLOWED_NAMES - set(_CACHE)),
        "refresh_seconds": _refresh_seconds(),
    }


def _refresh_seconds() -> int:
    try:
        return max(60, int(os.getenv("EMOJI_SOURCE_REFRESH_SECONDS", "300")))
    except ValueError:
        return 300


def _fallback_enabled() -> bool:
    return os.getenv("EMOJI_SOURCE_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}


async def _http_fetch(token: str, guild_id: int) -> list[dict[str, Any]]:
    url = f"https://discord.com/api/v10/guilds/{guild_id}/emojis"
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"Authorization": f"Bot {token}"}) as response:
            if response.status != 200:
                body = await response.text()
                raise RuntimeError(f"Discord emoji API returned HTTP {response.status}: {body[:200]}")
            data = await response.json()
            if not isinstance(data, list):
                raise RuntimeError("Discord emoji API returned an unexpected payload.")
            return data


async def bootstrap(token: str | None) -> dict[str, int]:
    """Load the designated source guild before Cogs are imported."""
    global _SOURCE_GUILD_ID

    raw = os.getenv("EMOJI_SOURCE_GUILD_ID", "").strip()
    if not raw.isdigit():
        set_emojis([])
        print("[Emoji] EMOJI_SOURCE_GUILD_ID is not configured; runtime discovery will be attempted after login.")
        return {"loaded": 0, "allowed": len(ALLOWED_NAMES), "missing": len(ALLOWED_NAMES)}

    _SOURCE_GUILD_ID = int(raw)
    if not token:
        set_emojis([])
        print("[Emoji] TOKEN is unavailable; source emoji fetch skipped.")
        return {"loaded": 0, "allowed": len(ALLOWED_NAMES), "missing": len(ALLOWED_NAMES)}

    try:
        data = await _http_fetch(token, _SOURCE_GUILD_ID)
        stats = set_emojis(data)
        print(f"[Emoji] Loaded {stats['loaded']}/{stats['allowed']} approved source emojis; missing={stats['missing']}.")
        return stats
    except Exception as exc:
        # Keep the bot bootable; the post-login fetch/discovery can recover.
        print(f"[Emoji] Initial source fetch failed: {type(exc).__name__}: {exc}")
        set_emojis([])
        return {"loaded": 0, "allowed": len(ALLOWED_NAMES), "missing": len(ALLOWED_NAMES)}


async def refresh_from_bot(bot) -> dict[str, int]:
    """Fetch emojis through the authenticated Discord client after login."""
    global _SOURCE_GUILD_ID

    configured = os.getenv("EMOJI_SOURCE_GUILD_ID", "").strip()
    guild = None

    if configured.isdigit():
        gid = int(configured)
        guild = bot.get_guild(gid)
        if guild is None:
            try:
                guild = await bot.fetch_guild(gid)
            except Exception as exc:
                if not _fallback_enabled():
                    raise
                print(f"[Emoji] Designated guild unavailable; trying discovery: {type(exc).__name__}: {exc}")

    # If fallback is enabled, find the connected guild containing the most
    # approved names. This is only used when the designated guild cannot load.
    if guild is None and _fallback_enabled() and not configured.isdigit():
        best = None
        best_score = 0
        for candidate in getattr(bot, "guilds", []):
            names = {_name(getattr(e, "name", "")) for e in getattr(candidate, "emojis", [])}
            score = len(names & ALLOWED_NAMES)
            if score > best_score:
                best = candidate
                best_score = score
        if best is not None and best_score:
            guild = best
            print(f"[Emoji] Auto-discovered emoji source guild {guild.id} with {best_score} approved names.")

    if guild is None:
        set_emojis([])
        return status()

    _SOURCE_GUILD_ID = guild.id
    try:
        emojis = await guild.fetch_emojis()
        stats = set_emojis(emojis)
        print(f"[Emoji] Refreshed source guild {guild.id}: {stats['loaded']}/{stats['allowed']} approved emojis.")
        return stats
    except Exception as exc:
        print(f"[Emoji] Post-login source refresh failed: {type(exc).__name__}: {exc}")
        return status()


async def _refresh_loop(bot) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await refresh_from_bot(bot)
        except Exception as exc:
            print(f"[Emoji] Refresh loop error: {type(exc).__name__}: {exc}")
        await asyncio.sleep(_refresh_seconds())


def start_refresh_task(bot) -> None:
    global _REFRESH_TASK
    if _REFRESH_TASK is None or _REFRESH_TASK.done():
        _REFRESH_TASK = asyncio.create_task(_refresh_loop(bot))


# Label/custom-id → approved emoji mapping for all non-AI interactive UI.
LABEL_EMOJIS = {
    "Confirm": "q_check", "Cancel": "cancle", "Back": "q_arrow_left",
    "Leaderboard": "q_trophy", "My Invites": "q_audit", "Refresh": "q_sync",
    "Enable": "q_online", "Enable Firewall": "q_online", "Enable Guard": "q_online",
    "Disable": "q_minus", "Toggle Layer": "q_mission", "Configure": "q_admin",
    "Configure Global Policy": "q_admin", "Configure Policy": "q_admin",
    "Deploy / Repair": "q_shield", "Deploy AutoMod": "q_bot",
    "Deploy Trust Guard": "q_lock", "Run Security Preflight": "q_audit",
    "Run AutoMod Preflight": "q_audit", "Run Trust Preflight": "q_audit",
    "Answer Question": "q_paste", "Submit Application": "q_rocket",
    "Start Application": "q_sparkle", "Previous": "q_arrow_left",
    "Approve": "q_success", "Deny": "q_error", "Enter": "q_celebrate",
    "Participants": "q_member", "Add Trusted User": "q_user",
    "Back to Rules": "q_arrow_left", "Back to Matrix": "q_arrow_left",
    "Back to Security Center": "q_arrow_left", "Deploy": "q_rocket",
}


def bind_view_emojis(view) -> None:
    """Resolve button emojis after the source registry is loaded/refreshed."""
    for child in getattr(view, "children", []):
        label = getattr(child, "label", None)
        if label in LABEL_EMOJIS:
            emoji = E(LABEL_EMOJIS[label])
            if emoji:
                child.emoji = emoji

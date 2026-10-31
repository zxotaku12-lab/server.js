# Credits: gogeta_gg
from __future__ import annotations

"""
Image-rendered cards — used where a plain embed can't do the job (progress
bars, circular avatars, per-pixel layout). Currently just the /invites check
stat card; anything else that wants this treatment goes here too, not in a
cog, so every rendered card shares one visual language.

Needs Pillow (see requirements.txt). CPU-bound drawing runs in a thread via
asyncio.to_thread so it never blocks the event loop.

FONTS: no font files ship with this — see _load_font()'s search order below.
Without a bundled .ttf, it falls back to whatever system font it can find,
and as a last resort Pillow's built-in bitmap font (readable, but flat and
not what the mockup looks like). For the real look, drop these into
ui/assets/fonts/:
    Inter-Bold.ttf
    Inter-SemiBold.ttf
    Inter-Regular.ttf
(Inter is free — https://rsms.me/inter/ — but any clean sans-serif works;
just keep the three filenames above or edit FONT_* below to match.)
"""

import asyncio
import io
import time
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
    PIL_IMPORT_ERROR = None
except Exception as exc:  # Pillow wheels can be unavailable/incompatible on some hosts.
    Image = ImageDraw = ImageFont = None
    PIL_AVAILABLE = False
    PIL_IMPORT_ERROR = exc

ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

FONT_BOLD = "Inter-Bold.ttf"
FONT_SEMIBOLD = "Inter-SemiBold.ttf"
FONT_REGULAR = "Inter-Regular.ttf"

# Fallback system paths tried in order if the bundled fonts above aren't
# there. Covers common Debian/Ubuntu VPS images; if none exist, we drop to
# Pillow's built-in bitmap font rather than crashing the render.
_SYSTEM_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]

_font_cache = {}


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    cache_key = (name, size)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    candidates = [ASSETS_DIR / name]
    if name != FONT_REGULAR:
        candidates.append(ASSETS_DIR / FONT_REGULAR)
    candidates += [Path(p) for p in _SYSTEM_FALLBACKS]

    font = None
    for path in candidates:
        if path.exists():
            try:
                font = ImageFont.truetype(str(path), size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default(size=size)

    _font_cache[cache_key] = font
    return font


# ── Palette ──────────────────────────────────────────────────────────────

BG = (13, 13, 20)
CARD_BG = (19, 19, 28)
TILE_BG = (24, 24, 35)
BORDER = (40, 40, 56)
PURPLE = (138, 99, 255)
PURPLE_DIM = (90, 70, 160)
WHITE = (240, 240, 245)
GREY = (150, 150, 165)
GREEN = (87, 242, 135)
RED = (237, 66, 69)
AMBER = (255, 176, 62)
GOLD = (240, 185, 80)


def _rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _circle_avatar(avatar_bytes: bytes, size: int) -> Image.Image:
    im = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def _text_w(draw, text, font):
    return draw.textlength(text, font=font)


def _center_text(draw, cx, y, text, font, fill):
    w = _text_w(draw, text, font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def _relative_time(ts: int) -> str:
    delta = max(0, int(time.time()) - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _stat_tile(draw, box, label, value, accent, sub=None):
    x0, y0, x1, y1 = box
    _rounded_rect(draw, box, 14, fill=TILE_BG, outline=BORDER, width=1)
    pad = 16
    val_font = _load_font(FONT_BOLD, 30)
    lbl_font = _load_font(FONT_SEMIBOLD, 13)
    draw.text((x0 + pad, y0 + pad), str(value), font=val_font, fill=accent)
    draw.text((x0 + pad, y1 - pad - 16), label.upper(), font=lbl_font, fill=GREY)
    if sub:
        sub_font = _load_font(FONT_REGULAR, 12)
        draw.text((x1 - pad - _text_w(draw, sub, sub_font), y0 + pad + 6), sub, font=sub_font, fill=GREY)


def _build_stat_card(
    display_name: str,
    handle: str,
    avatar_bytes: bytes,
    member_since_ts: int,
    stats: dict,
    rank: int | None,
    total_tracked: int,
    tracking_enabled: bool,
    recent: list,
) -> io.BytesIO:
    W, H = 1160, 620
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    _rounded_rect(draw, (16, 16, W - 16, H - 16), 20, fill=CARD_BG, outline=BORDER, width=1)

    title_font = _load_font(FONT_BOLD, 20)
    draw.text((48, 40), "INVITE STATISTICS", font=title_font, fill=WHITE)

    badge_text = "TRACKING" if tracking_enabled else "PAUSED"
    badge_color = GREEN if tracking_enabled else GREY
    badge_font = _load_font(FONT_SEMIBOLD, 13)
    bw = _text_w(draw, badge_text, badge_font)
    bx1 = W - 48
    bx0 = bx1 - bw - 34
    _rounded_rect(draw, (bx0, 34, bx1, 62), 14, fill=(20, 40, 30) if tracking_enabled else TILE_BG, outline=badge_color, width=1)
    draw.ellipse((bx0 + 12, 42, bx0 + 20, 50), fill=badge_color)
    draw.text((bx0 + 28, 40), badge_text, font=badge_font, fill=badge_color)

    # ── Band 1: avatar / identity (full width, nothing else shares this y-range) ──
    avatar_size = 110
    ax, ay = 48, 96
    ring = Image.new("RGBA", (avatar_size + 12, avatar_size + 12), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, avatar_size + 12, avatar_size + 12), outline=PURPLE, width=3)
    img.paste(ring, (ax - 6, ay - 6), ring)
    avatar = _circle_avatar(avatar_bytes, avatar_size)
    img.paste(avatar, (ax, ay), avatar)

    name_font = _load_font(FONT_BOLD, 26)
    handle_font = _load_font(FONT_REGULAR, 15)
    since_font = _load_font(FONT_REGULAR, 13)
    tx = ax + avatar_size + 24
    draw.text((tx, ay + 8), display_name, font=name_font, fill=WHITE)
    draw.text((tx, ay + 42), f"@{handle}", font=handle_font, fill=PURPLE)
    since_str = time.strftime("%b %d, %Y", time.gmtime(member_since_ts))
    draw.text((tx, ay + 70), f"Member since {since_str}", font=since_font, fill=GREY)

    band2_y = ay + avatar_size + 24  # = 230

    # ── Band 2, left column: rank tile ──────────────────────────────
    rank_col_w = 260
    rank_h = 160
    _rounded_rect(draw, (48, band2_y, 48 + rank_col_w, band2_y + rank_h), 16, fill=TILE_BG, outline=GOLD, width=1)
    rank_lbl_font = _load_font(FONT_SEMIBOLD, 13)
    draw.text((70, band2_y + 20), "RANK", font=rank_lbl_font, fill=GOLD)
    rank_val_font = _load_font(FONT_BOLD, 46)
    rank_str = f"#{rank}" if rank else "—"
    draw.text((70, band2_y + 46), rank_str, font=rank_val_font, fill=WHITE)
    out_of_font = _load_font(FONT_REGULAR, 13)
    draw.text((70, band2_y + 118), f"OUT OF {total_tracked}", font=out_of_font, fill=GREY)

    # ── Band 2, right column: big effective-invites tile + 2x2 breakdown ──
    rx0 = 48 + rank_col_w + 20  # = 328
    big_w = 220
    _rounded_rect(draw, (rx0, band2_y, rx0 + big_w, band2_y + rank_h), 16, fill=TILE_BG, outline=PURPLE, width=1)
    big_val_font = _load_font(FONT_BOLD, 52)
    _center_text(draw, rx0 + big_w / 2, band2_y + 46, str(stats["total"]), big_val_font, PURPLE)
    big_lbl_font = _load_font(FONT_SEMIBOLD, 13)
    _center_text(draw, rx0 + big_w / 2, band2_y + rank_h - 34, "EFFECTIVE INVITES", big_lbl_font, GREY)

    grid_x = rx0 + big_w + 20
    grid_w = (W - 48) - grid_x
    cell_w = (grid_w - 16) / 2
    cell_h = (rank_h - 16) / 2
    _stat_tile(draw, (grid_x, band2_y, grid_x + cell_w, band2_y + cell_h), "Regular", stats["regular"], GREEN)
    _stat_tile(draw, (grid_x + cell_w + 16, band2_y, grid_x + cell_w + 16 + cell_w, band2_y + cell_h), "Left", stats["leaves"], AMBER)
    _stat_tile(draw, (grid_x, band2_y + cell_h + 16, grid_x + cell_w, band2_y + rank_h), "Fake", stats["fake"], RED)
    bonus_val = f"+{stats['bonus']}" if stats["bonus"] >= 0 else str(stats["bonus"])
    _stat_tile(draw, (grid_x + cell_w + 16, band2_y + cell_h + 16, grid_x + cell_w + 16 + cell_w, band2_y + rank_h), "Bonus", bonus_val, PURPLE)

    # ── Band 3: full-width recent activity strip, below everything above ──
    act_y = band2_y + rank_h + 24  # = 414
    act_h = H - 16 - 24 - act_y
    _rounded_rect(draw, (48, act_y, W - 48, act_y + act_h), 16, fill=TILE_BG, outline=BORDER, width=1)
    act_title_font = _load_font(FONT_SEMIBOLD, 14)
    draw.text((72, act_y + 20), "RECENT INVITE ACTIVITY", font=act_title_font, fill=WHITE)

    if not recent:
        empty_font = _load_font(FONT_REGULAR, 14)
        draw.text((72, act_y + 64), "No recent activity yet.", font=empty_font, fill=GREY)
    else:
        row_font_name = _load_font(FONT_SEMIBOLD, 15)
        row_font_sub = _load_font(FONT_REGULAR, 13)
        n = min(5, len(recent))
        col_w = (W - 96 - 48) / n
        row_top = act_y + 64
        for i, entry in enumerate(recent[:5]):
            col_x = 72 + i * col_w
            dot_color = GREEN if entry["type"] == "joined" else AMBER
            draw.ellipse((col_x, row_top + 4, col_x + 9, row_top + 13), fill=dot_color)
            max_name_w = col_w - 24
            name = entry["name"]
            while _text_w(draw, name, row_font_name) > max_name_w and len(name) > 1:
                name = name[:-1]
            if name != entry["name"]:
                name = name[:-1] + "…"
            draw.text((col_x + 16, row_top), name, font=row_font_name, fill=WHITE)
            status_label = "Joined" if entry["type"] == "joined" else "Left"
            draw.text((col_x, row_top + 26), status_label, font=row_font_sub, fill=dot_color)
            draw.text((col_x, row_top + 48), _relative_time(entry["at"]), font=row_font_sub, fill=GREY)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_stat_card(member, stats: dict, rank, total_tracked: int, tracking_enabled: bool, recent: list) -> io.BytesIO:
    """Render an image card when Pillow is available; callers should offer an embed fallback otherwise."""
    if not PIL_AVAILABLE:
        raise RuntimeError(f"Pillow image rendering is unavailable: {PIL_IMPORT_ERROR}")
    avatar_bytes = await member.display_avatar.replace(size=256, format="png").read()
    return await asyncio.to_thread(
        _build_stat_card,
        member.display_name,
        str(member.name),
        avatar_bytes,
        int(member.joined_at.timestamp()) if member.joined_at else int(time.time()),
        stats,
        rank,
        total_tracked,
        tracking_enabled,
        recent,
    )

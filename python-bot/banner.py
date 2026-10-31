# Credits: gogeta_gg
"""Console banner + credits for Gogeta. Credits: gogeta_gg"""
import os

CREDITS = "gogeta_gg"

# 5x6 pixel font, drawn with full blocks.
_FONT = {
    "G": [" ████ ", "██    ", "██ ███", "██  ██", " ████ "],
    "O": [" ████ ", "██  ██", "██  ██", "██  ██", " ████ "],
    "E": ["██████", "██    ", "█████ ", "██    ", "██████"],
    "T": ["██████", "  ██  ", "  ██  ", "  ██  ", "  ██  "],
    "A": [" ████ ", "██  ██", "██████", "██  ██", "██  ██"],
}

# Top rows light cyan, middle rows blue, bottom row white.
_ROW_COLORS = [(138, 216, 255), (138, 216, 255), (122, 162, 255), (122, 162, 255), (255, 255, 255)]


def _paint(text: str, rgb, enabled: bool) -> str:
    if not enabled:
        return text
    r, g, b = rgb
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def render_banner(word: str = "GOGETA", color: bool = True) -> str:
    rows = []
    for i in range(5):
        line = " ".join(_FONT[ch][i] for ch in word)
        rows.append("  " + _paint(line, _ROW_COLORS[i], color))
    return "\n".join(rows)


def print_banner(bot_name: str = "Gogeta") -> None:
    color = "NO_COLOR" not in os.environ
    width = 42
    rule = _paint("  " + "─" * width, (120, 120, 120), color)
    tagline = f"  • {bot_name}  |  by {CREDITS}"
    support = os.getenv("SUPPORT_URL", "").strip()
    if support:
        tagline += f"  |  {support}"
    print()
    print(render_banner(color=color))
    print()
    print(rule)
    print(tagline)
    print(rule)
    print(flush=True)

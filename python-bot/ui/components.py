# Credits: gogeta_gg
"""
Small formatting helpers used across embeds — the "sentence-level"
building blocks that sit below embeds.py.
"""

from .theme import Icon


def status_row(label: str, enabled: bool) -> str:
    dot = Icon.ON if enabled else Icon.OFF
    return f"{dot} **{label}**"


def bullet_list(items: list[str], empty_text: str = "None configured") -> str:
    if not items:
        return f"*{empty_text}*"
    return "\n".join(f"• {item}" for item in items)


def ranked_list(items: list[str], empty_text: str = "No data yet") -> str:
    if not items:
        return f"*{empty_text}*"
    return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))


def key_value_block(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"**{k}**\n{v}" for k, v in pairs)

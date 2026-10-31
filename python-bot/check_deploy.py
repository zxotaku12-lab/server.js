# Credits: gogeta_gg
"""Preflight checks for a Gogeta's Pet deployment. Never prints secret values."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    from env_loader import load_clean_dotenv
    load_clean_dotenv(ROOT / ".env")
except Exception as exc:
    print(f"[FAIL] Could not load .env safely: {type(exc).__name__}")
    raise SystemExit(2)

errors = []
warnings = []

token = os.getenv("TOKEN", "").strip()
if not token or token.lower() in {"your_token_here", "replace_me", "changeme"}:
    errors.append("TOKEN is missing or still a placeholder in .env.")

provider_keys = (
    "GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
    "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "NVIDIA_API_KEY", "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY", "DEEPINFRA_API_KEY", "SAMBANOVA_API_KEY",
    "CLOUDFLARE_API_TOKEN", "GITHUB_TOKEN", "HF_TOKEN",
)
if not any(os.getenv(k, "").strip() for k in provider_keys):
    warnings.append("No recognized AI provider key detected; AI replies may not work.")
if not os.getenv("GIPHY_API_KEY", "").strip():
    warnings.append("GIPHY_API_KEY is unset; GIF reactions will be unavailable.")
owner = os.getenv("GOGETAS_PET_OWNER_ID", "").strip()
if owner and not owner.isdigit():
    errors.append("GOGETAS_PET_OWNER_ID must be a numeric Discord user ID.")
if not (ROOT / "cogs" / "gogetas_pet.py").is_file():
    errors.append("Missing cogs/gogetas_pet.py.")
if not (ROOT / "cogs" / "ticket_ai.py").is_file():
    errors.append("Missing cogs/ticket_ai.py.")
if not (ROOT / "bot.py").is_file():
    errors.append("Missing bot.py entrypoint.")

for warning in warnings:
    print(f"[WARN] {warning}")
for error in errors:
    print(f"[FAIL] {error}")
if errors:
    raise SystemExit(1)
print("[OK] Required files and token configuration look ready.")
print("[INFO] This preflight does not test Discord login or live AI-provider requests.")

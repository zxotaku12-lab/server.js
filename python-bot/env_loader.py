# Credits: gogeta_gg
"""Load the project's .env while safely ignoring decorative section headings.

Some deployed .env files include un-commented ASCII divider lines and headings
(e.g. GEMINI, GROQ). python-dotenv logs a parse warning for every such line.
This loader comments only parser-rejected statements in memory, then parses the
sanitized stream. It never rewrites the user's .env file or prints values.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional, Union

from dotenv.parser import parse_stream
from dotenv import dotenv_values

PathLike = Union[str, os.PathLike[str]]
_REPORTED_SIGNATURES: set[tuple[str, int, int]] = set()


def load_clean_dotenv(
    dotenv_path: Optional[PathLike] = None,
    *,
    override: bool = False,
) -> int:
    """Load valid .env assignments and return the number of ignored statements.

    Existing environment variables win unless ``override=True``, matching
    python-dotenv's default ``load_dotenv`` behavior.
    """
    path = Path(dotenv_path) if dotenv_path is not None else Path(__file__).resolve().parent / ".env"
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    except OSError as exc:
        print(f"[Env] Could not read .env ({type(exc).__name__}); using existing environment.")
        return 0

    pieces: list[str] = []
    rejected_lines: list[int] = []
    for binding in parse_stream(io.StringIO(raw_text)):
        original = binding.original.string
        if not binding.error:
            pieces.append(original)
            continue

        rejected_lines.append(binding.original.line)
        # Keep line count stable for diagnostics; do not expose the original
        # contents because a malformed line could accidentally contain a key.
        for line in original.splitlines(keepends=True):
            if line.strip():
                ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else "\r" if line.endswith("\r") else ""
                pieces.append("# Ignored malformed dotenv section line" + ending)
            else:
                pieces.append(line)

    parsed = dotenv_values(stream=io.StringIO("".join(pieces)))
    for key, value in parsed.items():
        if not key or value is None:
            continue
        if override or key not in os.environ:
            os.environ[key] = value

    if rejected_lines:
        signature = (str(path.resolve()), len(raw_text), hash(raw_text))
        if signature not in _REPORTED_SIGNATURES:
            _REPORTED_SIGNATURES.add(signature)
            where = ", ".join(str(line) for line in rejected_lines[:8])
            suffix = "…" if len(rejected_lines) > 8 else ""
            print(
                f"[Env] Ignored {len(rejected_lines)} malformed .env section/divider statement(s) "
                f"at line(s) {where}{suffix}; valid settings were still loaded. "
                "The .env file was not modified."
            )
    return len(rejected_lines)

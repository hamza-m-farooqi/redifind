from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from rich.text import Text

from .query import parse_query


HIGHLIGHT_STYLE = "bold yellow"
DEFAULT_MAX_LINES = 3
DEFAULT_CONTEXT_CHARS = 80


def _query_terms(query: str) -> list[str]:
    parsed = parse_query(query)
    terms = [t for t in (parsed.terms + parsed.required) if t]
    cleaned = [t.lower() for t in terms if ":" not in t]
    return list(dict.fromkeys(cleaned))


def _context_window(line: str, terms: Iterable[str], width: int) -> str:
    lower = line.lower()
    for term in terms:
        if not term:
            continue
        idx = lower.find(term)
        if idx >= 0:
            start = max(0, idx - width // 2)
            end = min(len(line), start + width)
            return line[start:end].strip()
    return line[:width].strip()


def _highlight_text(text: str, terms: Iterable[str]) -> Text:
    rich_text = Text(text)
    for term in terms:
        if not term:
            continue
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
            rich_text.stylize(HIGHLIGHT_STYLE, match.start(), match.end())
    return rich_text


def snippet_for(
    path: Path,
    query: str,
    max_lines: int = DEFAULT_MAX_LINES,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> Text:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return Text("")

    terms = _query_terms(query)
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(term in lower for term in terms if term):
            start = max(0, idx - 1)
            end = min(len(lines), idx + max_lines)
            windowed = [_context_window(l, terms, context_chars) for l in lines[start:end]]
            return _highlight_text("\n".join(windowed).strip(), terms)
    windowed = [_context_window(l, terms, context_chars) for l in lines[:max_lines]]
    return _highlight_text("\n".join(windowed).strip(), terms)

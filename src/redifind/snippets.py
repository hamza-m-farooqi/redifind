from __future__ import annotations

from pathlib import Path


def snippet_for(path: Path, query: str, max_lines: int = 3) -> str:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return ""

    terms = [t.lower().lstrip("+") for t in query.split() if not t.startswith("-")]
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(term in lower for term in terms if term):
            start = max(0, idx - 1)
            end = min(len(lines), idx + max_lines)
            return "\n".join(lines[start:end]).strip()
    return "\n".join(lines[:max_lines]).strip()

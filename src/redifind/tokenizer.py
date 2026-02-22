from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Sequence

WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def tokenize_text(text: str) -> Counter[str]:
    tokens = [t.lower() for t in WORD_RE.findall(text)]
    return Counter(tokens)


def doc_filter_tokens(path: Path) -> Sequence[str]:
    tokens: list[str] = []
    suffix = path.suffix.lower().lstrip(".")
    if suffix:
        tokens.append(f"ext:{suffix}")
    name = path.name.lower()
    tokens.append(f"name:{name}")

    parts = [p for p in path.parts if p not in (".", "")]
    if parts:
        accum: list[str] = []
        for part in parts:
            if part == "/":
                continue
            accum.append(part)
            tokens.append(f"path:{'/'.join(accum)}")
    return tokens

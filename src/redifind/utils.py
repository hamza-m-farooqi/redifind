from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterable, Iterator, Sequence


def normalize_prefix(prefix: str) -> str:
    if not prefix:
        return "rsearch:"
    return prefix if prefix.endswith(":") else f"{prefix}:"


def is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def should_include(path: Path, include: Sequence[str], exclude: Sequence[str]) -> bool:
    rel = path.as_posix()
    if include and not matches_any(rel, include):
        return False
    if exclude and matches_any(rel, exclude):
        return False
    return True


def iter_files(paths: Sequence[Path]) -> Iterator[Path]:
    for root in paths:
        if root.is_file():
            yield root
            continue
        if root.is_dir():
            for dirpath, _, filenames in os.walk(root):
                base = Path(dirpath)
                for name in filenames:
                    yield base / name


def human_bytes(num_bytes: int) -> str:
    step = 1024.0
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < step:
            return f"{size:.1f}{unit}"
        size /= step
    return f"{size:.1f}PB"

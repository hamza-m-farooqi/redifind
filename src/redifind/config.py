from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class IndexConfig:
    include: Sequence[str]
    exclude: Sequence[str]
    max_bytes: int
    redis_url: str
    prefix: str
    drop: bool


@dataclass(frozen=True)
class QueryConfig:
    redis_url: str
    prefix: str
    top: int
    offset: int
    json_output: bool
    with_scores: bool


@dataclass(frozen=True)
class WatchConfig:
    include: Sequence[str]
    exclude: Sequence[str]
    max_bytes: int
    redis_url: str
    prefix: str

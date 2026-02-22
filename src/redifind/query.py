from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

from redis import Redis

from .utils import normalize_prefix


@dataclass(frozen=True)
class Query:
    raw: str
    required: list[str]
    excluded: list[str]
    terms: list[str]


def _split_raw(raw: str) -> list[str]:
    tokens: list[str] = []
    buf: list[str] = []
    in_quote = False
    quote_char = ""
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch in ("\"", "'"):
            if in_quote and ch == quote_char:
                in_quote = False
                quote_char = ""
            elif not in_quote:
                in_quote = True
                quote_char = ch
            else:
                buf.append(ch)
        elif ch.isspace() and not in_quote:
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def _extract_terms(text: str) -> list[str]:
    word = []
    terms: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in "_:/.-":
            word.append(ch)
        else:
            if word:
                terms.append("".join(word).lower())
                word = []
    if word:
        terms.append("".join(word).lower())
    return [t for t in terms if t]


def parse_query(raw: str) -> Query:
    required: list[str] = []
    excluded: list[str] = []
    terms: list[str] = []
    for token in _split_raw(raw):
        if not token:
            continue
        if token.startswith("+") and len(token) > 1:
            required.extend(_extract_terms(token[1:]))
        elif token.startswith("-") and len(token) > 1:
            excluded.extend(_extract_terms(token[1:]))
        else:
            terms.extend(_extract_terms(token))
    return Query(raw=raw, required=required, excluded=excluded, terms=terms)


def _term_key(prefix: str, token: str) -> str:
    return f"{prefix}term:{token.lower()}"


def _indexed_key(prefix: str) -> str:
    return f"{prefix}indexed"


def _idf(total_docs: int, df: int) -> float:
    if total_docs <= 0 or df <= 0:
        return 0.0
    return max(math.log2(total_docs / df), 0.0)


def run_query(
    client: Redis,
    raw: str,
    top: int,
    offset: int,
    prefix: str,
) -> list[tuple[str, float]]:
    prefix = normalize_prefix(prefix)
    parsed = parse_query(raw)
    terms = [t.lower() for t in parsed.terms + parsed.required]
    terms = [t for t in terms if t]
    if not terms:
        return []

    total_docs = client.scard(_indexed_key(prefix))
    term_keys = [_term_key(prefix, t) for t in terms]
    weights = []
    for t in terms:
        df = client.zcard(_term_key(prefix, t))
        weights.append(_idf(total_docs, df))

    temp_key = f"{prefix}tmp:query:{int(time.time() * 1000)}"
    if len(term_keys) == 1:
        client.zunionstore(temp_key, term_keys, weights=weights)
    else:
        client.zunionstore(temp_key, term_keys, weights=weights)

    candidates = client.zrevrange(temp_key, offset, offset + top + 50, withscores=True)
    client.delete(temp_key)

    results: list[tuple[str, float]] = []
    for doc_id, score in candidates:
        if parsed.required:
            missing = False
            for t in parsed.required:
                if client.zscore(_term_key(prefix, t.lower()), doc_id) is None:
                    missing = True
                    break
            if missing:
                continue
        if parsed.excluded:
            blocked = False
            for t in parsed.excluded:
                if client.zscore(_term_key(prefix, t.lower()), doc_id) is not None:
                    blocked = True
                    break
            if blocked:
                continue
        results.append((doc_id, float(score)))
        if len(results) >= top:
            break
    return results

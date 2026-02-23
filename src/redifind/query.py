from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Sequence

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


def _collect_terms(parsed: Query) -> list[str]:
    terms = [t.lower() for t in parsed.terms + parsed.required]
    return [t for t in terms if t]


def _build_term_stats(client: Redis, prefix: str, terms: list[str], total_docs: int) -> dict[str, dict[str, float | int]]:
    stats: dict[str, dict[str, float | int]] = {}
    for term in terms:
        if term in stats:
            stats[term]["count"] = int(stats[term]["count"]) + 1
            continue
        df = int(client.zcard(_term_key(prefix, term)))
        stats[term] = {
            "df": df,
            "idf": _idf(total_docs, df),
            "count": 1,
        }
    return stats


def _rank_candidates(
    client: Redis,
    prefix: str,
    terms: list[str],
    term_stats: dict[str, dict[str, float | int]],
    top: int,
    offset: int,
) -> list[tuple[str, float]]:
    term_keys = [_term_key(prefix, t) for t in terms]
    weights = [float(term_stats[t]["idf"]) for t in terms]

    temp_key = f"{prefix}tmp:query:{int(time.time() * 1000)}"
    client.zunionstore(temp_key, term_keys, weights=weights)
    candidates = client.zrevrange(temp_key, offset, offset + top + 50, withscores=True)
    client.delete(temp_key)
    return [(doc_id, float(score)) for doc_id, score in candidates]


def _passes_filters(client: Redis, prefix: str, parsed: Query, doc_id: str) -> bool:
    if parsed.required:
        for term in parsed.required:
            if client.zscore(_term_key(prefix, term.lower()), doc_id) is None:
                return False
    if parsed.excluded:
        for term in parsed.excluded:
            if client.zscore(_term_key(prefix, term.lower()), doc_id) is not None:
                return False
    return True


def run_query(
    client: Redis,
    raw: str,
    top: int,
    offset: int,
    prefix: str,
) -> list[tuple[str, float]]:
    explained = run_query_explain(client, raw, top, offset, prefix)
    return [(item["doc_id"], float(item["score"])) for item in explained["results"]]


def run_query_explain(
    client: Redis,
    raw: str,
    top: int,
    offset: int,
    prefix: str,
) -> dict[str, Any]:
    prefix = normalize_prefix(prefix)
    parsed = parse_query(raw)
    terms = _collect_terms(parsed)
    if not terms:
        return {
            "parsed": {
                "required": parsed.required,
                "excluded": parsed.excluded,
                "terms": parsed.terms,
            },
            "total_docs": 0,
            "term_weights": [],
            "results": [],
        }

    total_docs = int(client.scard(_indexed_key(prefix)))
    term_stats = _build_term_stats(client, prefix, terms, total_docs)
    candidates = _rank_candidates(client, prefix, terms, term_stats, top, offset)

    results: list[dict[str, Any]] = []
    for doc_id, score in candidates:
        if not _passes_filters(client, prefix, parsed, doc_id):
            continue
        contributions: list[dict[str, float | str | int]] = []
        for term, stats in term_stats.items():
            tf = float(client.zscore(_term_key(prefix, term), doc_id) or 0.0)
            idf = float(stats["idf"])
            count = int(stats["count"])
            value = tf * idf * count
            contributions.append(
                {
                    "term": term,
                    "count": count,
                    "tf": tf,
                    "idf": idf,
                    "value": value,
                }
            )
        contributions.sort(key=lambda item: float(item["value"]), reverse=True)
        results.append(
            {
                "doc_id": doc_id,
                "score": float(score),
                "contributions": contributions,
            }
        )
        if len(results) >= top:
            break
    return {
        "parsed": {
            "required": parsed.required,
            "excluded": parsed.excluded,
            "terms": parsed.terms,
        },
        "total_docs": total_docs,
        "term_weights": [
            {
                "term": term,
                "df": int(stats["df"]),
                "idf": float(stats["idf"]),
                "count": int(stats["count"]),
            }
            for term, stats in term_stats.items()
        ],
        "results": results,
    }

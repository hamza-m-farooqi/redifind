from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from redis import Redis

from .tokenizer import doc_filter_tokens, tokenize_text
from .utils import iter_files, normalize_prefix, should_include

_BINARY_SAMPLE_BYTES = 8192
_TEXT_BYTE_WHITELIST = set(b"\n\r\t\f\b")


@dataclass(frozen=True)
class IndexedDoc:
    doc_id: str
    path: str
    size: int
    mtime: int


def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _doc_terms_key(prefix: str, doc_id: str) -> str:
    return f"{prefix}doc_terms:{doc_id}"


def _doc_key(prefix: str, doc_id: str) -> str:
    return f"{prefix}doc:{doc_id}"


def _term_key(prefix: str, token: str) -> str:
    return f"{prefix}term:{token}"


def _indexed_key(prefix: str) -> str:
    return f"{prefix}indexed"


def _looks_binary(data: bytes, sample_size: int = _BINARY_SAMPLE_BYTES) -> bool:
    sample = data[:sample_size]
    if not sample:
        return False
    if b"\x00" in sample:
        return True

    non_text = 0
    for byte in sample:
        if byte in _TEXT_BYTE_WHITELIST:
            continue
        if 32 <= byte <= 126:
            continue
        if 128 <= byte <= 255:
            continue
        non_text += 1
    return (non_text / len(sample)) > 0.30


def drop_namespace(client: Redis, prefix: str) -> int:
    prefix = normalize_prefix(prefix)
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=500)
        if keys:
            deleted += client.delete(*keys)
        if cursor == 0:
            break
    return deleted


def index_paths(
    client: Redis,
    paths: Sequence[Path],
    include: Sequence[str],
    exclude: Sequence[str],
    max_bytes: int,
    prefix: str,
) -> int:
    prefix = normalize_prefix(prefix)
    indexed = 0
    roots = [p.resolve() for p in paths if p.exists()]
    for path in iter_files(paths):
        if not should_include(path, include, exclude):
            continue
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if _looks_binary(data):
            continue

        text = None
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

        resolved = path.resolve()
        doc_id = str(resolved)
        mtime = int(path.stat().st_mtime)
        sha1 = _sha1_bytes(data)

        tokens = tokenize_text(text)
        rel_path = None
        for root in roots:
            if root.is_dir():
                try:
                    rel_path = resolved.relative_to(root)
                    break
                except ValueError:
                    continue
        filter_tokens = doc_filter_tokens(rel_path or resolved)

        total_terms = sum(tokens.values())
        if total_terms == 0:
            continue

        pipe = client.pipeline()
        doc_key = _doc_key(prefix, doc_id)
        pipe.hset(
            doc_key,
            mapping={
                "path": doc_id,
                "mtime": mtime,
                "size": size,
                "sha1": sha1,
            },
        )
        pipe.sadd(_indexed_key(prefix), doc_id)

        doc_terms_key = _doc_terms_key(prefix, doc_id)
        pipe.delete(doc_terms_key)

        for token, count in tokens.items():
            tf = count / total_terms
            term_key = _term_key(prefix, token)
            pipe.zadd(term_key, {doc_id: tf})
            pipe.sadd(doc_terms_key, token)

        for token in filter_tokens:
            term_key = _term_key(prefix, token)
            pipe.zadd(term_key, {doc_id: 1.0})
            pipe.sadd(doc_terms_key, token)

        pipe.execute()
        indexed += 1
    return indexed


def remove_docs(client: Redis, paths: Sequence[Path], prefix: str) -> int:
    prefix = normalize_prefix(prefix)
    removed = 0
    for path in paths:
        doc_id = str(path.resolve())
        doc_terms_key = _doc_terms_key(prefix, doc_id)
        tokens = client.smembers(doc_terms_key)
        if not tokens:
            continue
        pipe = client.pipeline()
        for token in tokens:
            pipe.zrem(_term_key(prefix, token), doc_id)
        pipe.delete(doc_terms_key)
        pipe.delete(_doc_key(prefix, doc_id))
        pipe.srem(_indexed_key(prefix), doc_id)
        pipe.execute()
        removed += 1
    return removed


def prune_missing(client: Redis, root: Path, prefix: str) -> int:
    prefix = normalize_prefix(prefix)
    indexed_key = _indexed_key(prefix)
    doc_ids = client.smembers(indexed_key)
    missing: list[Path] = []
    for doc_id in doc_ids:
        if not doc_id.startswith(str(root.resolve())):
            continue
        if not Path(doc_id).exists():
            missing.append(Path(doc_id))
    if not missing:
        return 0
    return remove_docs(client, missing, prefix)


def _count_term_keys(client: Redis, prefix: str) -> int:
    cursor = 0
    total = 0
    pattern = f"{prefix}term:*"
    while True:
        cursor, keys = client.scan(cursor=cursor, match=pattern, count=500)
        total += len(keys)
        if cursor == 0:
            break
    return total


def _approx_indexed_size_bytes(client: Redis, prefix: str) -> int:
    doc_ids = client.smembers(_indexed_key(prefix))
    if not doc_ids:
        return 0
    pipe = client.pipeline()
    for doc_id in doc_ids:
        pipe.hget(_doc_key(prefix, doc_id), "size")
    sizes = pipe.execute()
    total = 0
    for size in sizes:
        try:
            total += int(size or 0)
        except (TypeError, ValueError):
            continue
    return total


def _redis_memory_info(client: Redis) -> dict[str, Any]:
    try:
        info = client.info("memory")
    except Exception:
        return {"redis_memory_used_bytes": None, "redis_memory_used_human": None}
    return {
        "redis_memory_used_bytes": info.get("used_memory"),
        "redis_memory_used_human": info.get("used_memory_human"),
    }


def index_stats(client: Redis, prefix: str) -> dict[str, Any]:
    prefix = normalize_prefix(prefix)
    indexed_count = client.scard(_indexed_key(prefix))
    stats = {
        "docs": int(indexed_count),
        "total_terms": int(_count_term_keys(client, prefix)),
        "indexed_size_bytes_approx": int(_approx_indexed_size_bytes(client, prefix)),
    }
    stats.update(_redis_memory_info(client))
    return stats

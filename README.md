# redifind — Redis-backed Ranked Search for Your Workspace (CLI + Python)

A fast, hackable, **TF/IDF-ranked** search index for local workspaces (code, docs, notes) built on **Redis** and `redis-py`.

Think: **ripgrep + persistence + ranking + filters** — with a simple schema you can extend (boosts, tags, metadata, negative filters, recency, etc.).

> Scope note: `redifind` is intentionally aimed at **small → medium corpora** (developer workspaces, docs exports, internal knowledge bases). Redis keeps the index in memory, so size grows with the index.

---

## Why Redis for Search?

Redis gives us:
- **Incremental updates** (reindex only changed files)
- **Fast set/zset math** (union/intersection + weighted scoring)
- **Low operational complexity** (single redis instance; optional persistence/replication)
- **Flexibility** (custom tokens, custom boosts, custom filters)

Core trick:
- For each term we store a ZSET: `term -> {doc_id: TF}`
- On query, compute IDF per term, then do `ZUNIONSTORE` with weights = IDF
- Optionally combine with metadata / boosts (filename, headings, recency)

---

## Features (MVP)

- Index a directory of files (code + docs)
- Ranked search (TF/IDF-ish) with Redis ZSET unions
- Filters and facets using special tokens (`ext:py`, `path:src/`)
- Required (`+term`) and excluded (`-term`) terms
- Snippet previews (basic)
- JSON output for integrations
- Namespace isolation via `--prefix` so you can run multiple indexes in one Redis

---

## Non-Goals (for the first release)

- Exact phrase search with positional indexes (possible later)
- Fuzzy phonetic matching / stemming (easy add-on later)
- Billion-doc scale (Redis memory + merge latency will bite)

---

## Installation (Linux Only)

redifind currently supports **Linux only**. On first run, redifind will:
- verify you are on Linux
- check whether Redis is reachable
- if Redis is missing, ask if you want redifind to install it for you

### 1) Clone and install

```bash
git clone <your-repo-url>
cd redifind
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2) Redis (automatic or manual)

When you run a command (e.g. `redifind index`), redifind will check Redis.
If Redis is not found, it will ask to install via your system package manager.
You can also install manually, for example:

```bash
sudo apt-get update
sudo apt-get install -y redis-server
sudo systemctl enable --now redis-server
```

---

## Quick Start

Index your workspace:

```bash
redifind index ~/work/myrepo \
  --include "**/*.py" "**/*.ts" "**/*.md" \
  --exclude ".git/**" "node_modules/**" \
  --redis "redis://localhost:6379/0" \
  --prefix "myrepo:"
```

Query:

```bash
redifind query "redis pipeline +zunionstore -lua ext:py" --top 15 --prefix "myrepo:"
```

Watch for changes (incremental):

```bash
redifind watch ~/work/myrepo --include "**/*.py" "**/*.md" --prefix "myrepo:"
```

Inspect a document:

```bash
redifind show "/abs/path/to/file.py" --prefix "myrepo:"
```

---

## Development (uv)

Install dev tools and run tests using `uv`:

```bash
uv add --dev pytest
cd /tmp
UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=/home/redifind/src uv --project /home/redifind run pytest /home/redifind
```

---

## CLI Command Reference

### `redifind index <PATH...>`

Index one or more paths (directories or files).

Options:
- `--include <glob...>`: include patterns (repeatable)
- `--exclude <glob...>`: exclude patterns (repeatable)
- `--max-bytes <n>`: skip very large files (default: 2_000_000)
- `--redis <url>`: Redis URL (default: redis://localhost:6379/0)
- `--prefix <ns>`: namespace prefix for all keys (default: rsearch:)
- `--drop`: drop existing index namespace before indexing

Examples:

```bash
redifind index . --include "**/*.py" "**/*.md"
redifind index ~/notes --include "**/*.md" --prefix "notes:"
```

---

### `redifind query <QUERY>`

Query language:
- plain terms: `redis zunionstore`
- required terms: `+pipeline`
- excluded terms: `-lua`
- filters: `ext:py`, `path:src/`, `name:README`
- quoted strings are treated as multiple tokens in MVP (phrase search later)

Options:
- `--top <n>`: number of results (default 10)
- `--offset <n>`: pagination offset (default 0)
- `--json`: output JSON
- `--with-scores`: show numeric scores

Examples:

```bash
redifind query "rate limit +redis -memcached ext:md" --top 20
redifind query "deployment path:infra/ ext:yml"
```

---

### `redifind show <DOC_ID>`

Print document metadata + a snippet preview.

`DOC_ID` is the canonical file path (for workspace indexing).

In other ingestion modes you could use UUIDs; MVP uses full path.

---

### `redifind remove <PATH...>`

Remove documents from the index (by file path).

---

### `redifind prune <ROOT>`

Remove indexed docs that no longer exist on disk under ROOT.

---

### `redifind stats`

Show index stats (doc count).

---

### `redifind doctor`

Run environment checks (Linux + Redis reachability).

---

### `redifind watch <PATH>`

Watch a directory and auto-update the index on file changes.

Notes:
- Uses filesystem events
- Debounces rapid saves (future enhancement)

---

## Output Examples

### Human output

```
1) src/search/indexer.py  score=2.884
   ... use a non-transactional pipeline to reduce round-trips ...

2) docs/redis-notes.md    score=2.102
   ... zunionstore combines TF scores and applies IDF weights ...
```

### JSON output (`--json`)

```json
{
  "query": "redis pipeline ext:py",
  "offset": 0,
  "count": 10,
  "results": [
    {"doc_id": "/abs/path/src/app.py", "score": 2.884, "path": "/abs/path/src/app.py"},
    {"doc_id": "/abs/path/src/cache.py", "score": 2.102, "path": "/abs/path/src/cache.py"}
  ]
}
```

---

## Redis Data Model (MVP)

All keys are prefixed, e.g. `rsearch:` or `myrepo:`.

Core keys:

- `prefix:indexed` (SET)
  All indexed doc_ids

- `prefix:term:<token>` (ZSET)
  Members: doc_id
  Score: TF (term frequency normalized), or 1 for boolean index mode

- `prefix:doc:<doc_id>` (HASH)
  Metadata:
  - `path`
  - `mtime`
  - `size`
  - `sha1` (optional)

- `prefix:doc_terms:<doc_id>` (SET)
  All tokens indexed for that doc, so removal is O(#tokens)

Filter tokens (stored same as terms):
- `ext:py`
- `path:src/` (can be hierarchical tokens: `path:src`, `path:src/search`)
- `name:readme`

So filters are just “terms” you can include/require.

---

## Ranking

MVP ranking:

- TF = normalized term frequency per doc (count / total_terms_in_doc)
- IDF = max(log2(total_docs / df), 0)
- Score(doc) for query terms = Σ (TF(term, doc) * IDF(term))

Implementation uses:
- `ZCARD prefix:term:<token>` to get document frequencies (df)
- `ZUNIONSTORE tmp weights={termkey: idf}` to compute weighted union

Exclusion (`-term`) can be implemented by:
- retrieving results then filtering client-side (MVP), or
- using Redis set/zset diff patterns (later optimization)

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
- Snippet previews with query-term highlighting and fixed-width context windows
- Structured JSON output across all primary commands (`index`, `query`, `show`, `remove`, `prune`, `stats`, `doctor`, `watch`)
- Query explain mode (`query --explain`) with DF/IDF term weights and per-result score contributions
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
- binary files are auto-skipped via byte sampling (NUL/control-byte heuristic)
- `--redis <url>`: Redis URL (default: redis://localhost:6379/0)
- `--prefix <ns>`: namespace prefix for all keys (default: rsearch:)
- `--drop`: drop existing index namespace before indexing
- `--json`: output structured JSON

Notes:
- human output now shows a Rich progress bar while indexing
- when `--drop` is set, drop progress is shown before indexing starts

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
- `--explain`: show term DF/IDF weights and per-result score breakdown
- `--with-scores`: show numeric scores

Examples:

```bash
redifind query "rate limit +redis -memcached ext:md" --top 20
redifind query "deployment path:infra/ ext:yml"
redifind query "redis pipeline ext:py" --explain --with-scores
redifind query "redis pipeline ext:py" --json --explain
```

---

### `redifind show <DOC_ID>`

Print document metadata + a snippet preview.

`DOC_ID` is the canonical file path (for workspace indexing).

In other ingestion modes you could use UUIDs; MVP uses full path.

Options:
- `--query <text>`: optional query for snippet context
- `--json`: output structured JSON

Notes:
- With `--query`, snippet output highlights matched query terms in the terminal.

---

### `redifind remove <PATH...>`

Remove documents from the index (by file path).

Options:
- `--dry-run`: preview which missing docs would be removed without deleting
- `--json`: output structured JSON
- `--size-unit <auto|bytes|kb|mb|gb>`: choose size display units for indexed/Redis memory values

---

### `redifind prune <ROOT>`

Remove indexed docs that no longer exist on disk under ROOT.

Options:
- `--json`: output structured JSON

---

### `redifind stats`

Show index stats:
- `docs`
- `total_terms` (unique indexed term keys, including filter tokens)
- `indexed_size_bytes_approx` and humanized size
- Redis memory usage (`used_memory`, `used_memory_human`) when available

Options:
- `--json`: output structured JSON

---

### `redifind doctor`

Run environment checks (Linux + Redis reachability).

Options:
- `--json`: output structured JSON

---

### `redifind watch <PATH>`

Watch a directory and auto-update the index on file changes.

Notes:
- Uses filesystem events
- Debounces rapid saves (future enhancement)

Options:
- `--json`: output structured JSON startup payload

---

## Output Examples

### Human output

```
1) src/search/indexer.py  score=2.884
   ... use a non-transactional pipeline to reduce round-trips ...

2) docs/redis-notes.md    score=2.102
   ... zunionstore combines TF scores and applies IDF weights ...
```

### Human explain output (`query --explain`)

```
┏━━━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━━┓
┃ Term     ┃ Count ┃ DF ┃ IDF   ┃
┡━━━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━━┩
│ redis    │ 1     │ 42 │ 0.251 │
│ pipeline │ 1     │ 13 │ 1.943 │
└──────────┴───────┴────┴───────┘

Explain: /abs/path/src/app.py
pipeline: value=0.583 (tf=0.300, idf=1.943, count=1)
redis: value=0.126 (tf=0.500, idf=0.251, count=1)
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

### JSON explain output (`query --json --explain`)

```json
{
  "query": "redis pipeline ext:py",
  "offset": 0,
  "count": 10,
  "results": [
    {
      "doc_id": "/abs/path/src/app.py",
      "score": 0.709,
      "path": "/abs/path/src/app.py"
    }
  ],
  "explain": {
    "total_docs": 250,
    "term_weights": [
      {"term": "redis", "df": 42, "idf": 0.251, "count": 1},
      {"term": "pipeline", "df": 13, "idf": 1.943, "count": 1}
    ],
    "results": [
      {
        "doc_id": "/abs/path/src/app.py",
        "score": 0.709,
        "contributions": [
          {"term": "pipeline", "count": 1, "tf": 0.3, "idf": 1.943, "value": 0.583},
          {"term": "redis", "count": 1, "tf": 0.5, "idf": 0.251, "value": 0.126}
        ]
      }
    ]
  }
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

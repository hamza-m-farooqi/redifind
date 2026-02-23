from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import IndexConfig, QueryConfig, WatchConfig
from .indexer import drop_namespace, index_paths, index_stats, prune_missing, remove_docs
from .preflight import ensure_redis_ready, get_preflight_status
from .query import run_query
from .redis_client import get_client
from .snippets import snippet_for
from .utils import human_bytes, normalize_prefix
from .watch import watch

app = typer.Typer(add_completion=False, help="Redis-backed ranked search for your workspace.")
console = Console()


def _print_json(payload: dict) -> None:
    console.print(json.dumps(payload, indent=2))


@app.callback()
def _main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(None, "--version", help="Show version and exit."),
):
    if version:
        from . import __version__

        console.print(__version__)
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        console.print(
            Panel(
                "[bold]redifind[/bold] — Redis-backed ranked search\n"
                "Use [bold]index[/bold], [bold]query[/bold], [bold]show[/bold], [bold]watch[/bold]",
                box=box.ROUNDED,
                expand=False,
            )
        )


@app.command()
def index(
    paths: List[Path] = typer.Argument(..., help="Paths to index (files or directories)."),
    include: List[str] = typer.Option([], "--include", help="Glob patterns to include."),
    exclude: List[str] = typer.Option([], "--exclude", help="Glob patterns to exclude."),
    max_bytes: int = typer.Option(2_000_000, "--max-bytes", help="Skip files larger than this."),
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
    drop: bool = typer.Option(False, "--drop", help="Drop namespace before indexing."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    cfg = IndexConfig(include=include, exclude=exclude, max_bytes=max_bytes, redis_url=redis_url, prefix=prefix, drop=drop)
    ensure_redis_ready(cfg.redis_url)
    client = get_client(cfg.redis_url)
    deleted = 0
    if cfg.drop:
        deleted = drop_namespace(client, cfg.prefix)
        if not json_output:
            console.print(f"Dropped {deleted} keys under {normalize_prefix(cfg.prefix)}")

    indexed = index_paths(client, paths, cfg.include, cfg.exclude, cfg.max_bytes, cfg.prefix)
    if json_output:
        _print_json(
            {
                "command": "index",
                "paths": [str(p) for p in paths],
                "prefix": normalize_prefix(cfg.prefix),
                "dropped_keys": deleted,
                "indexed_docs": indexed,
            }
        )
        raise typer.Exit()

    console.print(f"Indexed {indexed} documents.")


@app.command()
def query(
    query_text: str = typer.Argument(..., help="Query string."),
    top: int = typer.Option(10, "--top", help="Number of results."),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
    with_scores: bool = typer.Option(False, "--with-scores", help="Include scores in output."),
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
):
    cfg = QueryConfig(
        redis_url=redis_url,
        prefix=prefix,
        top=top,
        offset=offset,
        json_output=json_output,
        with_scores=with_scores,
    )
    ensure_redis_ready(cfg.redis_url)
    client = get_client(cfg.redis_url)
    results = run_query(client, query_text, cfg.top, cfg.offset, cfg.prefix)

    if cfg.json_output:
        payload = {
            "query": query_text,
            "offset": cfg.offset,
            "count": cfg.top,
            "results": [
                {"doc_id": doc_id, "score": score, "path": doc_id}
                for doc_id, score in results
            ],
        }
        console.print(json.dumps(payload, indent=2))
        raise typer.Exit()

    if not results:
        console.print("No results.")
        raise typer.Exit()

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("#", style="bold")
    table.add_column("Path")
    if cfg.with_scores:
        table.add_column("Score", justify="right")

    for i, (doc_id, score) in enumerate(results, 1):
        if cfg.with_scores:
            table.add_row(str(i), doc_id, f"{score:.3f}")
        else:
            table.add_row(str(i), doc_id)
    console.print(table)


@app.command()
def show(
    doc_id: Path = typer.Argument(..., help="Document path."),
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
    query_text: Optional[str] = typer.Option(None, "--query", help="Optional query for snippet context."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    ensure_redis_ready(redis_url)
    client = get_client(redis_url)
    doc_key = f"{normalize_prefix(prefix)}doc:{str(doc_id.resolve())}"
    meta = client.hgetall(doc_key)
    if not meta:
        if json_output:
            _print_json({"command": "show", "doc_id": str(doc_id), "found": False})
            raise typer.Exit(code=1)
        console.print("Document not found in index.")
        raise typer.Exit(code=1)

    size = int(meta.get("size", 0))
    mtime = meta.get("mtime", "")
    snippet_plain: Optional[str] = None
    snippet_rich = None
    if query_text:
        snippet = snippet_for(Path(meta.get("path")), query_text)
        if snippet.plain:
            snippet_plain = snippet.plain
            snippet_rich = snippet

    if json_output:
        _print_json(
            {
                "command": "show",
                "doc_id": str(doc_id),
                "found": True,
                "meta": {
                    "path": meta.get("path"),
                    "size": size,
                    "mtime": mtime,
                    "sha1": meta.get("sha1"),
                },
                "snippet": snippet_plain,
            }
        )
        raise typer.Exit()

    panel = Panel(
        f"[bold]{meta.get('path')}[/bold]\n"
        f"size: {human_bytes(size)}\n"
        f"mtime: {mtime}",
        title="Document",
        box=box.ROUNDED,
    )
    console.print(panel)

    if snippet_rich is not None:
        console.print(Panel(snippet_rich, title="Snippet", box=box.SIMPLE))


@app.command()
def remove(
    paths: List[Path] = typer.Argument(..., help="Paths to remove from index."),
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    ensure_redis_ready(redis_url)
    client = get_client(redis_url)
    removed = remove_docs(client, paths, prefix)
    if json_output:
        _print_json(
            {
                "command": "remove",
                "paths": [str(p) for p in paths],
                "removed_docs": removed,
            }
        )
        raise typer.Exit()
    console.print(f"Removed {removed} documents.")


@app.command()
def prune(
    root: Path = typer.Argument(..., help="Root to prune missing docs under."),
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    ensure_redis_ready(redis_url)
    client = get_client(redis_url)
    removed = prune_missing(client, root, prefix)
    if json_output:
        _print_json(
            {
                "command": "prune",
                "root": str(root),
                "removed_docs": removed,
            }
        )
        raise typer.Exit()
    console.print(f"Pruned {removed} documents.")


@app.command()
def stats(
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    ensure_redis_ready(redis_url)
    client = get_client(redis_url)
    data = index_stats(client, prefix)
    if json_output:
        _print_json({"command": "stats", "prefix": normalize_prefix(prefix), "stats": data})
        raise typer.Exit()

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("docs", str(data.get("docs", 0)))
    console.print(table)


@app.command()
def doctor(
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    status = get_preflight_status(redis_url)
    if json_output:
        ok = bool(status.is_linux and status.redis_reachable)
        _print_json(
            {
                "command": "doctor",
                "ok": ok,
                "checks": {
                    "is_linux": status.is_linux,
                    "redis_reachable": status.redis_reachable,
                    "installer": status.installer,
                },
                "redis_url": redis_url,
            }
        )
        if not ok:
            raise typer.Exit(code=1)
        raise typer.Exit()

    table = Table(title="redifind doctor", box=box.SIMPLE_HEAVY)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_row("OS Linux", "yes" if status.is_linux else "no")
    table.add_row("Redis reachable", "yes" if status.redis_reachable else "no")
    table.add_row("Installer", status.installer or "not detected")
    table.add_row("Redis URL", redis_url)
    console.print(table)

    if not status.is_linux or not status.redis_reachable:
        raise typer.Exit(code=1)


@app.command("watch")
def watch_cmd(
    root: Path = typer.Argument(..., help="Root path to watch."),
    include: List[str] = typer.Option([], "--include", help="Glob patterns to include."),
    exclude: List[str] = typer.Option([], "--exclude", help="Glob patterns to exclude."),
    max_bytes: int = typer.Option(2_000_000, "--max-bytes", help="Skip files larger than this."),
    redis_url: str = typer.Option("redis://localhost:6379/0", "--redis", help="Redis URL."),
    prefix: str = typer.Option("rsearch:", "--prefix", help="Namespace prefix for keys."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
):
    ensure_redis_ready(redis_url)
    client = get_client(redis_url)
    if json_output:
        _print_json(
            {
                "command": "watch",
                "root": str(root),
                "include": include,
                "exclude": exclude,
                "max_bytes": max_bytes,
                "prefix": normalize_prefix(prefix),
                "status": "watching",
            }
        )
    else:
        console.print(f"Watching {root}...")
    watch(client, root, include, exclude, max_bytes, prefix)


if __name__ == "__main__":
    app()

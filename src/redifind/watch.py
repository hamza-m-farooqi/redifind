from __future__ import annotations

import time
from pathlib import Path
from typing import Sequence

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from redis import Redis

from .indexer import index_paths, remove_docs
from .utils import should_include


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        client: Redis,
        root: Path,
        include: Sequence[str],
        exclude: Sequence[str],
        max_bytes: int,
        prefix: str,
    ) -> None:
        self.client = client
        self.root = root
        self.include = include
        self.exclude = exclude
        self.max_bytes = max_bytes
        self.prefix = prefix

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not should_include(path, self.include, self.exclude):
            return
        index_paths(self.client, [path], self.include, self.exclude, self.max_bytes, self.prefix)

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not should_include(path, self.include, self.exclude):
            return
        index_paths(self.client, [path], self.include, self.exclude, self.max_bytes, self.prefix)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        remove_docs(self.client, [path], self.prefix)


def watch(
    client: Redis,
    root: Path,
    include: Sequence[str],
    exclude: Sequence[str],
    max_bytes: int,
    prefix: str,
) -> None:
    handler = _Handler(client, root, include, exclude, max_bytes, prefix)
    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

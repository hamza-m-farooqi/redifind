import os
import time
from pathlib import Path

from redifind.indexer import _looks_binary, index_paths


class _Pipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def hset(self, key, mapping):
        self.ops.append(("hset", key, mapping))
        return self

    def sadd(self, key, *members):
        self.ops.append(("sadd", key, members))
        return self

    def delete(self, key):
        self.ops.append(("delete", key))
        return self

    def zadd(self, key, mapping):
        self.ops.append(("zadd", key, mapping))
        return self

    def execute(self):
        for op in self.ops:
            if op[0] == "hset":
                _, key, mapping = op
                self.client.hashes[key] = {k: str(v) for k, v in mapping.items()}
            elif op[0] == "sadd":
                _, key, members = op
                self.client.sets.setdefault(key, set()).update(str(m) for m in members)
            elif op[0] == "delete":
                _, key = op
                self.client.hashes.pop(key, None)
                self.client.sets.pop(key, None)
                self.client.zsets.pop(key, None)
            elif op[0] == "zadd":
                _, key, mapping = op
                zset = self.client.zsets.setdefault(key, {})
                for member, score in mapping.items():
                    zset[str(member)] = float(score)
        return True


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.zsets = {}

    def pipeline(self):
        return _Pipeline(self)

    def hmget(self, key, fields):
        data = self.hashes.get(key, {})
        return [data.get(field) for field in fields]


def test_looks_binary_detects_nul_bytes():
    assert _looks_binary(b"abc\x00def")
    assert not _looks_binary(b"hello world\nprint('x')\n")


def test_index_paths_skips_binary_files(tmp_path: Path):
    text_file = tmp_path / "ok.py"
    text_file.write_text("class GlobalContext:\n    pass\n")
    binary_file = tmp_path / "bin.dat"
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00")

    client = FakeRedis()
    indexed = index_paths(client, [tmp_path], ["**/*"], [], 2_000_000, "rsearch:")

    assert indexed == 1
    indexed_docs = client.sets["rsearch:indexed"]
    assert str(text_file.resolve()) in indexed_docs
    assert str(binary_file.resolve()) not in indexed_docs


def test_index_paths_skips_unchanged_files(tmp_path: Path):
    file_path = tmp_path / "same.py"
    file_path.write_text("def keep():\n    return 1\n")
    client = FakeRedis()

    first = index_paths(client, [tmp_path], ["**/*"], [], 2_000_000, "rsearch:")
    second = index_paths(client, [tmp_path], ["**/*"], [], 2_000_000, "rsearch:")

    assert first == 1
    assert second == 0


def test_index_paths_skips_when_only_mtime_changes(tmp_path: Path):
    file_path = tmp_path / "touch.py"
    file_path.write_text("def stable():\n    return 7\n")
    client = FakeRedis()

    first = index_paths(client, [tmp_path], ["**/*"], [], 2_000_000, "rsearch:")

    later = int(time.time()) + 2
    os.utime(file_path, (later, later))
    second = index_paths(client, [tmp_path], ["**/*"], [], 2_000_000, "rsearch:")

    assert first == 1
    assert second == 0

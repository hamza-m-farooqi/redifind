from redifind.indexer import index_stats


class _Pipeline:
    def __init__(self, client):
        self.client = client
        self.commands = []

    def hget(self, key, field):
        self.commands.append((key, field))
        return self

    def execute(self):
        out = []
        for key, field in self.commands:
            out.append(self.client.hget(key, field))
        return out


class FakeRedis:
    def __init__(self):
        self.sets = {
            "rsearch:indexed": {"/a.py", "/b.py"},
        }
        self.hashes = {
            "rsearch:doc:/a.py": {"size": "100"},
            "rsearch:doc:/b.py": {"size": "250"},
        }
        self.scan_keys = [
            "rsearch:term:redis",
            "rsearch:term:pipeline",
            "rsearch:term:ext:py",
        ]

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def smembers(self, key):
        return self.sets.get(key, set())

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def pipeline(self):
        return _Pipeline(self)

    def scan(self, cursor=0, match=None, count=500):
        if match == "rsearch:term:*" and cursor == 0:
            return 0, self.scan_keys
        return 0, []

    def info(self, section):
        assert section == "memory"
        return {"used_memory": 4096, "used_memory_human": "4.00K"}


class FakeRedisNoInfo(FakeRedis):
    def info(self, section):
        raise RuntimeError("no memory info")


def test_index_stats_includes_term_size_and_memory():
    stats = index_stats(FakeRedis(), "rsearch:")
    assert stats["docs"] == 2
    assert stats["total_terms"] == 3
    assert stats["indexed_size_bytes_approx"] == 350
    assert stats["redis_memory_used_bytes"] == 4096
    assert stats["redis_memory_used_human"] == "4.00K"


def test_index_stats_handles_memory_info_failure():
    stats = index_stats(FakeRedisNoInfo(), "rsearch:")
    assert stats["redis_memory_used_bytes"] is None
    assert stats["redis_memory_used_human"] is None

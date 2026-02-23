import math

from redifind.query import run_query_explain


class FakeRedis:
    def __init__(self):
        self.sets = {"rsearch:indexed": {"/a.py", "/b.py"}}
        self.zsets = {
            "rsearch:term:redis": {"/a.py": 0.5, "/b.py": 0.2},
            "rsearch:term:pipeline": {"/a.py": 0.3},
            "rsearch:term:lua": {"/b.py": 0.4},
        }

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def zunionstore(self, dest, keys, weights):
        out = {}
        for key, weight in zip(keys, weights):
            for member, score in self.zsets.get(key, {}).items():
                out[member] = out.get(member, 0.0) + float(score) * float(weight)
        self.zsets[dest] = out

    def zrevrange(self, key, start, stop, withscores=False):
        items = sorted(self.zsets.get(key, {}).items(), key=lambda x: x[1], reverse=True)
        sliced = items[start : stop + 1]
        if withscores:
            return sliced
        return [member for member, _ in sliced]

    def delete(self, key):
        self.zsets.pop(key, None)

    def zscore(self, key, member):
        score = self.zsets.get(key, {}).get(member)
        if score is None:
            return None
        return float(score)


def test_run_query_explain_weights_and_contributions():
    client = FakeRedis()

    explained = run_query_explain(client, "redis pipeline -lua", top=10, offset=0, prefix="rsearch:")

    assert explained["total_docs"] == 2
    weights = {item["term"]: item for item in explained["term_weights"]}
    assert math.isclose(weights["redis"]["idf"], 0.0)
    assert math.isclose(weights["pipeline"]["idf"], 1.0)

    assert len(explained["results"]) == 1
    assert explained["results"][0]["doc_id"] == "/a.py"

    contrib = {item["term"]: item for item in explained["results"][0]["contributions"]}
    assert math.isclose(contrib["pipeline"]["value"], 0.3)
    assert math.isclose(contrib["redis"]["value"], 0.0)

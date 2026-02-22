from redifind.query import parse_query


def test_parse_query_basic():
    q = parse_query("redis pipeline +zunionstore -lua ext:py path:src/")
    assert q.required == ["zunionstore"]
    assert q.excluded == ["lua"]
    assert q.terms == ["redis", "pipeline", "ext:py", "path:src/"]


def test_parse_query_quotes_required_excluded():
    q = parse_query('"redis pipeline" +"fast search" -"bad term" name:README')
    assert q.required == ["fast", "search"]
    assert q.excluded == ["bad", "term"]
    assert q.terms == ["redis", "pipeline", "name:readme"]


def test_parse_query_single_quotes():
    q = parse_query("foo 'bar baz' -'zip zap'")
    assert q.terms == ["foo", "bar", "baz"]
    assert q.excluded == ["zip", "zap"]

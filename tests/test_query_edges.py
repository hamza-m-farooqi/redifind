from redifind.query import parse_query


def test_parse_query_filters_preserved():
    q = parse_query("ext:py path:src/ name:README")
    assert q.terms == ["ext:py", "path:src/", "name:readme"]


def test_parse_query_mixed_prefixes():
    q = parse_query("+ext:py -path:node_modules/ redis")
    assert q.required == ["ext:py"]
    assert q.excluded == ["path:node_modules/"]
    assert q.terms == ["redis"]


def test_parse_query_unbalanced_quote():
    q = parse_query('"redis pipeline +zunionstore')
    assert q.terms == ["redis", "pipeline", "zunionstore"]

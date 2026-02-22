from pathlib import Path

from redifind.tokenizer import doc_filter_tokens, tokenize_text


def test_tokenize_text_basic():
    tokens = tokenize_text("Redis ZUNIONSTORE zset zset")
    assert tokens["redis"] == 1
    assert tokens["zunionstore"] == 1
    assert tokens["zset"] == 2


def test_tokenize_text_min_len():
    tokens = tokenize_text("a an the x y z redis")
    assert "a" not in tokens
    assert "x" not in tokens
    assert tokens["an"] == 1
    assert tokens["the"] == 1
    assert tokens["redis"] == 1


def test_doc_filter_tokens():
    path = Path("/home/user/src/app/main.py")
    tokens = doc_filter_tokens(path)
    assert "ext:py" in tokens
    assert "name:main.py" in tokens
    assert "path:home" in tokens
    assert "path:home/user/src" in tokens

from pathlib import Path

from redifind.utils import matches_any, should_include


def test_matches_any():
    assert matches_any("src/app/main.py", ["**/*.py"])
    assert not matches_any("src/app/main.py", ["**/*.md"])


def test_should_include_include_only():
    path = Path("src/app/main.py")
    assert should_include(path, ["**/*.py"], [])
    assert not should_include(path, ["**/*.md"], [])


def test_should_include_exclude():
    path = Path("src/app/main.py")
    assert not should_include(path, ["**/*.py"], ["src/**"])

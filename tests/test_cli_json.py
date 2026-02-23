import json
from pathlib import Path

from typer.testing import CliRunner

from redifind.cli import app
from redifind.preflight import PreflightStatus
from rich.text import Text


runner = CliRunner()


def test_stats_json(monkeypatch):
    monkeypatch.setattr("redifind.cli.ensure_redis_ready", lambda redis_url: None)
    monkeypatch.setattr("redifind.cli.get_client", lambda redis_url: object())
    monkeypatch.setattr("redifind.cli.index_stats", lambda client, prefix: {"docs": 7})

    result = runner.invoke(app, ["stats", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "stats"
    assert payload["stats"]["docs"] == 7


def test_show_json(monkeypatch, tmp_path: Path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello redis world")

    class FakeClient:
        def hgetall(self, _key):
            return {
                "path": str(file_path),
                "size": "17",
                "mtime": "123",
                "sha1": "abc",
            }

    monkeypatch.setattr("redifind.cli.ensure_redis_ready", lambda redis_url: None)
    monkeypatch.setattr("redifind.cli.get_client", lambda redis_url: FakeClient())
    monkeypatch.setattr("redifind.cli.snippet_for", lambda path, query: Text("redis context"))

    result = runner.invoke(app, ["show", str(file_path), "--query", "redis", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "show"
    assert payload["found"] is True
    assert payload["meta"]["path"] == str(file_path)
    assert payload["snippet"] == "redis context"


def test_doctor_json_failure_exit(monkeypatch):
    monkeypatch.setattr(
        "redifind.cli.get_preflight_status",
        lambda redis_url: PreflightStatus(is_linux=True, redis_reachable=False, installer="apt"),
    )

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["command"] == "doctor"
    assert payload["ok"] is False
    assert payload["checks"]["redis_reachable"] is False


def test_query_json_explain(monkeypatch):
    monkeypatch.setattr("redifind.cli.ensure_redis_ready", lambda redis_url: None)
    monkeypatch.setattr("redifind.cli.get_client", lambda redis_url: object())
    monkeypatch.setattr(
        "redifind.cli.run_query_explain",
        lambda client, query_text, top, offset, prefix: {
            "total_docs": 3,
            "term_weights": [{"term": "redis", "df": 2, "idf": 0.585, "count": 1}],
            "results": [
                {
                    "doc_id": "/tmp/a.py",
                    "score": 0.41,
                    "contributions": [
                        {"term": "redis", "count": 1, "tf": 0.7, "idf": 0.585, "value": 0.4095}
                    ],
                }
            ],
        },
    )

    result = runner.invoke(app, ["query", "redis", "--json", "--explain"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["results"][0]["doc_id"] == "/tmp/a.py"
    assert payload["explain"]["total_docs"] == 3
    assert payload["explain"]["term_weights"][0]["term"] == "redis"

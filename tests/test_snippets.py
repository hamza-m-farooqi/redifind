from pathlib import Path

from redifind.snippets import DEFAULT_CONTEXT_CHARS, HIGHLIGHT_STYLE, snippet_for


def test_snippet_for_highlights_and_windows(tmp_path: Path) -> None:
    content = "alpha beta gamma delta epsilon zeta eta theta iota kappa\n"
    content += "this line has Redis pipelines and more words to test context window\n"
    content += "tail line\n"
    path = tmp_path / "sample.txt"
    path.write_text(content)

    snippet = snippet_for(path, "redis pipeline")

    assert "redis" in snippet.plain.lower()
    assert len(snippet.plain) <= (DEFAULT_CONTEXT_CHARS * 3 + 2)
    assert any(span.style == HIGHLIGHT_STYLE for span in snippet.spans)

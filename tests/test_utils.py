from redifind.utils import normalize_prefix


def test_normalize_prefix_default():
    assert normalize_prefix("") == "rsearch:"


def test_normalize_prefix_adds_colon():
    assert normalize_prefix("myrepo") == "myrepo:"


def test_normalize_prefix_keeps_colon():
    assert normalize_prefix("myrepo:") == "myrepo:"

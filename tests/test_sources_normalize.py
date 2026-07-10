"""Tests for the source-URL normalizer.

We deliberately disable ``probe_feed`` for most tests — RSS detection
requires a network call and is tested separately.
"""
from unittest.mock import patch

import pytest

from backend.tools.sources import (
    NormalizedSource,
    normalize_source_url,
    outlet_name_from_title,
)


def test_article_url_reduces_to_root():
    n = normalize_source_url("https://sifted.eu/articles/europe-founder-renaissance-real", probe_feed=False)
    assert n.url == "https://sifted.eu"
    assert n.root_url == "https://sifted.eu"
    assert n.kind == "web"
    assert n.host == "sifted.eu"
    assert n.is_outlet is True


def test_deep_path_reduces_to_root():
    n = normalize_source_url("https://babyvc.substack.com/p/building-the-next-wave-of-european", probe_feed=False)
    assert n.url == "https://babyvc.substack.com"
    assert n.host == "babyvc.substack.com"


def test_www_prefix_stripped_from_host():
    n = normalize_source_url("https://www.example.com/blog/post-1", probe_feed=False)
    assert n.host == "example.com"


def test_instagram_marked_not_outlet():
    n = normalize_source_url("https://www.instagram.com/reel/DWB9bJlCOsX", probe_feed=False)
    assert n.is_outlet is False


def test_youtube_marked_not_outlet():
    n = normalize_source_url("https://www.youtube.com/watch?v=xyz", probe_feed=False)
    assert n.is_outlet is False


def test_feed_shaped_path_kept_as_rss():
    n = normalize_source_url("https://blog.example.com/feed", probe_feed=False)
    assert n.kind == "rss"
    assert n.url == "https://blog.example.com/feed"


def test_atom_xml_recognized_as_rss():
    n = normalize_source_url("https://blog.example.com/atom.xml", probe_feed=False)
    assert n.kind == "rss"


def test_probe_feed_returns_feed_when_detected():
    with patch(
        "backend.tools.sources.detect_feed_url",
        return_value="https://example.com/feed.xml",
    ):
        n = normalize_source_url("https://example.com/some/article", probe_feed=True)
    assert n.kind == "rss"
    assert n.url == "https://example.com/feed.xml"
    assert n.root_url == "https://example.com"


def test_probe_feed_returns_root_when_no_feed():
    with patch("backend.tools.sources.detect_feed_url", return_value=None):
        n = normalize_source_url("https://example.com/some/article", probe_feed=True)
    assert n.kind == "web"
    assert n.url == "https://example.com"


def test_garbage_url_gracefully_marked_not_outlet():
    n = normalize_source_url("not-a-url", probe_feed=False)
    assert n.is_outlet is False


@pytest.mark.parametrize("title,expected", [
    ("Is the European founders' renaissance real? | Sifted", "Sifted"),
    ("How to X — Substack Post - Baby VC", "Baby VC"),
    ("Just a bare title", "Example"),  # falls back to host
])
def test_outlet_name_from_title(title, expected):
    assert outlet_name_from_title(title, "example.com") == expected

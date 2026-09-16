"""Testes do modulo Web Intelligence."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from core.web_intel import (
    web_search, web_fetch, deep_research, quick_answer,
    _DDGParser, _HTMLTextExtractor,
)


class TestDDGParser(unittest.TestCase):
    def test_parse_empty(self):
        parser = _DDGParser()
        parser.feed("")
        self.assertEqual(parser.results, [])

    def test_parse_result(self):
        html = '<a class="result__a" href="https://example.com">Title</a>'
        html += '<a class="result__snippet">Snippet text</a>'
        parser = _DDGParser()
        parser.feed(html)
        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0]["title"], "Title")
        self.assertEqual(parser.results[0]["snippet"], "Snippet text")
        self.assertEqual(parser.results[0]["url"], "https://example.com")


class TestHTMLTextExtractor(unittest.TestCase):
    def test_extract_text(self):
        html = "<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        text = ext.get_text()
        self.assertIn("Title", text)
        self.assertIn("Paragraph text.", text)

    def test_skip_script(self):
        html = "<p>Visible</p><script>var x = 1;</script><p>Also visible</p>"
        ext = _HTMLTextExtractor()
        ext.feed(html)
        text = ext.get_text()
        self.assertIn("Visible", text)
        self.assertNotIn("var x", text)


class TestWebSearch(unittest.TestCase):
    @patch("core.web_intel.urllib.request.urlopen")
    def test_search_returns_results(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'<a class="result__a" href="https://x.com">T</a><a class="result__snippet">S</a>'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = web_search("test query")
        self.assertTrue(result["ok"])
        self.assertEqual(result["query"], "test query")

    def test_search_empty_query(self):
        result = web_search("")
        self.assertFalse(result["ok"])


class TestWebFetch(unittest.TestCase):
    @patch("core.web_intel.urllib.request.urlopen")
    def test_fetch_html(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><body>Hello World</body></html>"
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = web_fetch("https://example.com")
        self.assertTrue(result["ok"])
        self.assertIn("Hello World", result["text"])

    def test_fetch_empty_url(self):
        result = web_fetch("")
        self.assertFalse(result["ok"])


class TestDeepResearch(unittest.TestCase):
    def test_research_empty_query(self):
        result = deep_research("")
        self.assertFalse(result["ok"])

    @patch("core.web_intel.web_fetch")
    @patch("core.web_intel.web_search")
    def test_research_basic(self, mock_search, mock_fetch):
        mock_search.return_value = {
            "ok": True,
            "results": [
                {"title": "T1", "url": "https://a.com", "snippet": "S1"},
                {"title": "T2", "url": "https://b.com", "snippet": "S2"},
            ],
        }
        mock_fetch.return_value = {
            "ok": True,
            "text": "This is a test fact about Python programming. " * 5,
        }
        result = deep_research("python programming", depth=1)
        self.assertTrue(result["ok"])
        self.assertIn("facts", result)


class TestQuickAnswer(unittest.TestCase):
    def test_quick_answer_empty(self):
        result = quick_answer("")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

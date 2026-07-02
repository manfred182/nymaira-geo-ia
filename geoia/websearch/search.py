"""Búsqueda en internet con múltiples proveedores."""

import json
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx


class WebSearch:
    def __init__(self):
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._cache_ttl = 300  # 5 min
        self._cache_path = Path(__file__).parent.parent.parent / "data" / "search_cache.json"
        self._load_cache()

    def _load_cache(self):
        try:
            if self._cache_path.exists():
                raw = self._cache_path.read_text("utf-8")
                for k, (t, v) in json.loads(raw).items():
                    self._cache[k] = (t, v)
        except Exception:
            pass

    def _save_cache(self):
        try:
            raw = {k: v for k, v in self._cache.items() if time.time() - v[0] < self._cache_ttl * 2}
            self._cache_path.write_text(json.dumps(raw, default=str), "utf-8")
        except Exception:
            pass

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        cache_key = f"{query}_{num_results}"

        if cache_key in self._cache:
            ts, results = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return results

        results = await self._search_duckduckgo(query, num_results)
        if not results:
            results = await self._search_searxng(query, num_results)

        if results:
            self._cache[cache_key] = (time.time(), results)
            self._save_cache()

        return results

    async def _search_duckduckgo(self, query: str, num: int) -> list[dict]:
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            }
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    return self._parse_ddg_html(r.text, num)
        except Exception:
            pass
        return []

    def _parse_ddg_html(self, html: str, num: int) -> list[dict]:
        from html.parser import HTMLParser

        results = []
        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self._capture = False
                self._link = ""
                self._snippet = ""
                self._in_result = False
                self._in_snippet = False

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "a" and "result__a" in attrs.get("class", ""):
                    self._in_result = True
                    self._link = attrs.get("href", "")
                if tag == "a" and self._in_result:
                    self._capture = True
                if tag == "span" and "result__snippet" in attrs.get("class", ""):
                    self._in_snippet = True

            def handle_data(self, data):
                if self._capture and self._in_result:
                    self._link = data.strip()
                    self._capture = False
                if self._in_snippet:
                    self._snippet += data

            def handle_endtag(self, tag):
                if tag == "a" and self._in_result:
                    self._capture = False
                if tag == "span" and self._in_snippet:
                    results.append({"title": self._link, "snippet": self._snippet.strip(), "url": ""})
                    self._link = ""
                    self._snippet = ""
                    self._in_result = False
                    self._in_snippet = False

        Parser().feed(html)
        return results[:num]

    async def _search_searxng(self, query: str, num: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"http://localhost:4000/search",
                    params={"q": query, "format": "json", "language": "es"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return [
                        {"title": r.get("title", ""), "url": r.get("url", ""),
                         "snippet": r.get("content", "")}
                        for r in data.get("results", [])[:num]
                    ]
        except Exception:
            pass
        return []

    async def health(self) -> dict:
        ddg_ok = False
        searxng_ok = False
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get("https://html.duckduckgo.com/html/?q=test")
                ddg_ok = r.status_code == 200
        except Exception:
            pass
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get("http://localhost:4000/health")
                searxng_ok = r.status_code == 200
        except Exception:
            pass
        return {
            "duckduckgo": ddg_ok,
            "searxng": searxng_ok,
            "cache_size": len(self._cache),
        }

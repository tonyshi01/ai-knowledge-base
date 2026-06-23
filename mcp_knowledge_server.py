#!/usr/bin/env python3
"""MCP (Model Context Protocol) server for local knowledge base search.

Provides 3 tools that let any MCP-compatible AI client search and browse
articles stored in ``knowledge/articles/``.

Usage:
    python3 mcp_knowledge_server.py          # start server (stdio)
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \\
        python3 mcp_knowledge_server.py      # one-shot query

Protocol: JSON-RPC 2.0 over newline-delimited stdio.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


class KnowledgeBase:
    """Read-only index over all ``knowledge/articles/*.json`` files.

    Articles are loaded once at construction time.  Each article is expected
    to be a flat JSON dict with at least an ``id`` field.  Files that cannot
    be parsed or are not dicts are skipped with a warning on stderr.

    Args:
        articles_dir: Path literal relative to ``cwd``.
    """

    def __init__(self, articles_dir: str = "knowledge/articles") -> None:
        self._root = Path.cwd() / articles_dir
        self._articles: list[dict[str, Any]] = []
        self._index: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._root.is_dir():
            print(f"[mcp] articles dir not found: {self._root}", file=sys.stderr)
            return

        for fpath in sorted(self._root.iterdir()):
            if fpath.suffix != ".json":
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[mcp] skip {fpath.name}: {exc}", file=sys.stderr)
                continue

            articles = data if isinstance(data, list) else [data]
            for article in articles:
                if not isinstance(article, dict):
                    continue
                aid: str = str(article.get("id", ""))
                if aid:
                    self._index[aid] = article
                self._articles.append(article)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def article_count(self) -> int:
        return len(self._articles)

    def search(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return articles whose title / summary / tags match *keyword*.

        Matching is case-insensitive substring.  Results are sorted by
        descending ``score``.
        """
        kw = keyword.lower()
        matched: list[dict[str, Any]] = []

        for article in self._articles:
            haystack = " ".join(
                str(v)
                for v in [
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("translated_summary", ""),
                    article.get("source_url", ""),
                ]
            ).lower()
            tags = article.get("tags", [])
            haystack += " " + " ".join(str(t).lower() for t in tags)

            if kw in haystack:
                matched.append(article)

        matched.sort(key=lambda a: float(a.get("score", 0) or 0), reverse=True)
        return matched[:limit]

    def get(self, article_id: str) -> dict[str, Any] | None:
        """Look up a single article by its ``id`` field."""
        return self._index.get(article_id)

    def stats(self) -> dict[str, Any]:
        """Aggregate statistics about the article corpus."""
        total = len(self._articles)

        source_counter: Counter[str] = Counter()
        category_counter: Counter[str] = Counter()
        tag_counter: Counter[str] = Counter()

        for article in self._articles:
            source_counter[str(article.get("source", "unknown"))] += 1
            category_counter[str(article.get("category", "uncategorized"))] += 1
            for t in article.get("tags", []):
                if isinstance(t, str):
                    tag_counter[t.lower()] += 1

        avg_score = 0.0
        if total:
            scores = [float(a.get("score", 0) or 0) for a in self._articles]
            avg_score = sum(scores) / total

        return {
            "total_articles": total,
            "source_distribution": dict(source_counter.most_common()),
            "category_distribution": dict(category_counter.most_common()),
            "popular_tags": dict(tag_counter.most_common(20)),
            "average_score": round(avg_score, 3),
        }


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

# Schema of the tools advertised to the MCP client.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_articles",
        "description": "Search knowledge base articles by keyword in title, summary, and tags",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 5,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "Get the full content of a single article by its ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "Article ID (e.g. '20260623-027')",
                },
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "Get aggregate statistics about the article corpus",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class MCPServer:
    """JSON-RPC 2.0 over stdio server for the MCP protocol.

    Args:
        kb: A :class:`KnowledgeBase` instance to query.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb

    # ------------------------------------------------------------------
    # Request dispatch
    # ------------------------------------------------------------------

    def handle(self, raw: str) -> str | None:
        """Parse a single JSON-RPC message and return the response.

        Returns ``None`` for notifications (no ``id`` field).
        """
        try:
            msg: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._error(None, -32700, f"Parse error: {exc}")

        req_id: Any = msg.get("id")
        method: str = msg.get("method", "")
        params: dict[str, Any] = msg.get("params") or {}

        # JSON-RPC notification → no response
        if req_id is None:
            return None

        try:
            return self._dispatch(req_id, method, params)
        except Exception as exc:
            return self._error(req_id, -32603, f"Internal error: {exc}")

    def _dispatch(self, req_id: Any, method: str, params: dict[str, Any]) -> str:
        if method == "initialize":
            return self._initialize(req_id, params)
        if method == "tools/list":
            return self._list_tools(req_id)
        if method == "tools/call":
            return self._call_tool(req_id, params)
        return self._error(req_id, -32601, f"Method not found: {method}")

    # ------------------------------------------------------------------
    # MCP methods
    # ------------------------------------------------------------------

    def _initialize(self, req_id: Any, params: dict[str, Any]) -> str:
        proto = params.get("protocolVersion", "2024-11-05")
        result: dict[str, Any] = {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "knowledge-server", "version": "1.0.0"},
        }
        return self._response(req_id, result)

    def _list_tools(self, req_id: Any) -> str:
        return self._response(req_id, {"tools": TOOL_DEFINITIONS})

    def _call_tool(self, req_id: Any, params: dict[str, Any]) -> str:
        name: str = params.get("name", "")
        args: dict[str, Any] = params.get("arguments") or {}

        if name == "search_articles":
            return self._search(req_id, args)
        if name == "get_article":
            return self._get(req_id, args)
        if name == "knowledge_stats":
            return self._stats(req_id)

        return self._error(req_id, -32601, f"Unknown tool: {name}")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _search(self, req_id: Any, args: dict[str, Any]) -> str:
        keyword: str | None = args.get("keyword")
        if not keyword or not keyword.strip():
            return self._error(req_id, -32602, "Missing 'keyword' argument")
        limit: int = int(args.get("limit", 5))
        results = self._kb.search(keyword.strip(), limit=limit)

        text = json.dumps(
            {"count": len(results), "results": results},
            ensure_ascii=False,
            indent=2,
        )
        return self._response(req_id, {"content": [{"type": "text", "text": text}]})

    def _get(self, req_id: Any, args: dict[str, Any]) -> str:
        article_id: str | None = args.get("article_id")
        if not article_id or not article_id.strip():
            return self._error(req_id, -32602, "Missing 'article_id' argument")
        article = self._kb.get(article_id.strip())
        if article is None:
            return self._response(
                req_id,
                {"content": [{"type": "text", "text": json.dumps({"error": f"Article not found: {article_id}"}, ensure_ascii=False)}]},
            )
        return self._response(
            req_id,
            {"content": [{"type": "text", "text": json.dumps(article, ensure_ascii=False, indent=2)}]},
        )

    def _stats(self, req_id: Any) -> str:
        stats = self._kb.stats()
        return self._response(
            req_id,
            {"content": [{"type": "text", "text": json.dumps(stats, ensure_ascii=False, indent=2)}]},
        )

    # ------------------------------------------------------------------
    # JSON-RPC helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _response(req_id: Any, result: Any) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, ensure_ascii=False)

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> str:
        return json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Read JSON-RPC requests from stdin and write responses to stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle(line)
            if response is not None:
                sys.stdout.write(response + "\n")
                sys.stdout.flush()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    kb = KnowledgeBase()
    server = MCPServer(kb)
    server.run()


if __name__ == "__main__":
    main()

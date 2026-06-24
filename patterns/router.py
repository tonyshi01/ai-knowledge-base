"""Two-layer intent router with keyword pre-filter and LLM fallback.

Intents:
    - github_search  — search GitHub repos via public API
    - knowledge_query — query local knowledge base (JSON articles)
    - general_chat   — free-form LLM conversation

Usage:
    >>> from patterns.router import route
    >>> print(route("show me AI repos on github"))
"""

from __future__ import annotations

import json
import logging
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import chat  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"

GITHUB_API = "https://api.github.com/search/repositories"

Intent = Literal["github_search", "knowledge_query", "general_chat"]

# First-layer keyword patterns — zero-cost, no LLM call
_GITHUB_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"github",
        r"repo(sitory)?",
        r"仓库",
        r"开源项目",
        r"trending",
        r"star\b",
    ]
]

_KNOWLEDGE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"知识",
        r"文章",
        r"article",
        r"知识库",
        r"之前.*(?:文章|内容)",
        r"我们.*(?:写过|发过|讨论)",
    ]
]

_LLM_CLASSIFY_PROMPT = """Classify the user query into exactly one of these three intents:

- github_search: User wants to find/search GitHub repositories, open-source projects, trending repos
- knowledge_query: User is asking about previously collected/saved knowledge, articles, or internal content
- general_chat: Everything else — casual conversation, general questions, anything not covered above

Respond with ONLY the intent keyword, no explanation.

Query: {query}"""

# ---------------------------------------------------------------------------
# In-memory article index (built once at import time)
# ---------------------------------------------------------------------------

_article_index: list[dict[str, Any]] = []


def _build_index() -> list[dict[str, Any]]:
    """Scan ``knowledge/articles/`` for JSON article files and load them."""
    if not ARTICLES_DIR.is_dir():
        logger.warning("Articles directory not found: %s", ARTICLES_DIR)
        return []

    entries: list[dict[str, Any]] = []
    for fpath in sorted(ARTICLES_DIR.iterdir()):
        if fpath.suffix != ".json":
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            entries.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Skipping %s: %s", fpath.name, e)

    logger.info("Loaded %d articles into index", len(entries))
    return entries


_article_index = _build_index()


# ---------------------------------------------------------------------------
# Step 1 — Keyword-based intent classification (zero cost)
# ---------------------------------------------------------------------------


def _classify_by_keywords(query: str) -> Intent | None:
    """Return intent if keyword patterns match, else ``None``."""
    for pat in _GITHUB_PATTERNS:
        if pat.search(query):
            return "github_search"
    for pat in _KNOWLEDGE_PATTERNS:
        if pat.search(query):
            return "knowledge_query"
    return None


# ---------------------------------------------------------------------------
# Step 2 — LLM-based intent classification (fallback)
# ---------------------------------------------------------------------------


def _classify_by_llm(query: str) -> Intent:
    """Use LLM to classify ambiguous queries."""
    prompt = _LLM_CLASSIFY_PROMPT.format(query=query)
    try:
        resp = chat(prompt, temperature=0.1, max_tokens=20)
        raw = resp.content.strip().lower()
        if raw in ("github_search", "knowledge_query", "general_chat"):
            return raw  # type: ignore[return-value]
    except Exception as e:
        logger.warning("LLM classify failed, falling back to general_chat: %s", e)

    return "general_chat"


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------


def _handle_github_search(query: str) -> str:
    """Search GitHub repositories via the public Search API.

    Args:
        query: User query (e.g. "AI agent framework").

    Returns:
        Formatted search results string.
    """
    encoded = urllib.parse.quote(f"{query} in:readme,topic")
    url = f"{GITHUB_API}?q={encoded}&sort=stars&order=desc&per_page=5"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-knowledge-base-router",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode())

        items = data.get("items", [])
        if not items:
            return "GitHub 未找到匹配的仓库。"

        lines: list[str] = [f"找到 {len(items)} 个相关仓库：\n"]
        for repo in items:
            name: str = repo.get("full_name", "unknown")
            desc: str = repo.get("description") or "无描述"
            stars: int = repo.get("stargazers_count", 0)
            url_: str = repo.get("html_url", "")
            lang: str = repo.get("language") or "N/A"
            lines.append(f"  ⭐ {name} ({stars} stars, {lang})")
            lines.append(f"     {desc}")
            lines.append(f"     {url_}")
            lines.append("")

        return "\n".join(lines)

    except urllib.error.HTTPError as e:
        logger.error("GitHub API HTTP error: %s", e)
        return f"GitHub API 请求失败 (HTTP {e.code})。请稍后重试。"
    except urllib.error.URLError as e:
        logger.error("GitHub API network error: %s", e)
        return "GitHub API 网络请求失败，请检查网络连接。"
    except json.JSONDecodeError as e:
        logger.error("GitHub API JSON parse error: %s", e)
        return "GitHub API 返回了异常数据。"


def _handle_knowledge_query(query: str) -> str:
    """Search the local article index by keyword matching.

    Args:
        query: User query to search for in articles.

    Returns:
        Matching article summaries.
    """
    if not _article_index:
        return "知识库为空，暂无文章。"

    q_lower = query.lower()
    ascii_words = re.findall(r"[a-z][a-z0-9\-]+", q_lower)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", q_lower)
    cjk_bigrams = [f"{cjk_chars[i]}{cjk_chars[i+1]}" for i in range(len(cjk_chars) - 1)]
    keywords = [w for w in ascii_words + cjk_bigrams if len(w) > 1]

    if not keywords:
        return "请输入更具体的搜索关键词。"

    scored: list[tuple[float, dict[str, Any]]] = []
    for article in _article_index:
        title: str = (article.get("title") or "").lower()
        summary: str = (article.get("summary") or "").lower()
        tags: list[str] = [t.lower() for t in article.get("tags", [])]
        haystack = f"{title} {summary} {' '.join(tags)}"

        score = sum(2.0 if kw in title else 1.0 if kw in haystack else 0.0 for kw in keywords)
        if score > 0:
            scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:5]

    if not top:
        return f"知识库中未找到与「{query}」相关的内容。"

    lines: list[str] = [f"找到 {len(top)} 篇相关文章：\n"]
    for score, article in top:
        title_: str = article.get("title", "无标题")
        summary_: str = article.get("summary", "无摘要")
        category: str = article.get("category", "unknown")
        lines.append(f"  [{category}] {title_}  (匹配度: {score:.0f})")
        lines.append(f"    {summary_}")
        lines.append("")

    return "\n".join(lines)


def _handle_general_chat(query: str) -> str:
    """Handle general conversation via LLM.

    Args:
        query: User message.

    Returns:
        LLM response text.
    """
    try:
        resp = chat(query, temperature=0.7, max_tokens=1024)
        return resp.content
    except Exception as e:
        logger.error("General chat LLM error: %s", e)
        return "抱歉，我暂时无法回答这个问题，请稍后重试。"


_HANDLERS: dict[Intent, Any] = {
    "github_search": _handle_github_search,
    "knowledge_query": _handle_knowledge_query,
    "general_chat": _handle_general_chat,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(query: str) -> Intent:
    """Two-layer intent classification.

    Layer 1: keyword matching (zero cost).
    Layer 2: LLM fallback for ambiguous queries.

    Args:
        query: Raw user input.

    Returns:
        One of ``github_search``, ``knowledge_query``, ``general_chat``.
    """
    result = _classify_by_keywords(query)
    if result is not None:
        logger.debug("Classified by keyword: %s", result)
        return result

    result = _classify_by_llm(query)
    logger.debug("Classified by LLM: %s", result)
    return result


def route(query: str) -> str:
    """Unified entry point: classify intent and dispatch to the right handler.

    Args:
        query: Raw user input.

    Returns:
        Response string from the appropriate handler.
    """
    query = query.strip()
    if not query:
        return "请输入有效内容。"

    intent = classify(query)
    logger.info("Routing to intent: %s", intent)

    handler = _HANDLERS[intent]
    return handler(query)


# ---------------------------------------------------------------------------
# CLI test entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 52)
    print("  Router 交互测试 — 输入 query 查看路由结果")
    print("  输入 /quit 退出")
    print("=" * 52)

    test_cases = [
        "find AI agent repos on github",
        "show me trending LLM projects",
        "star超过1000的RAG框架",
        "我们之前讨论过MCP的文章",
        "知识库里关于OpenAI的文章",
        "what is the meaning of life",
        "用Python写一个快速排序",
        "github上有什么好的Agent框架",
        "之前那篇关于langchain的文章",
    ]

    print("\n预置测试用例：")
    for i, case in enumerate(test_cases, 1):
        print(f"\n  [{i}] {case}")
        print(f"  -> Intent: {classify(case)}")
    print("")

    while True:
        try:
            raw = input(">> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        q = raw.strip()
        if not q:
            continue
        if q == "/quit":
            break

        print(f"\n  Intent: {classify(q)}")
        print(f"  Response:\n{route(q)}\n")

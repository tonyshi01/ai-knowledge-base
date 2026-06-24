"""Four-step knowledge base automation pipeline.

Steps:
    1. **Collect** — fetch items from GitHub Search API and/or RSS feeds
    2. **Analyze** — LLM-powered summarization, tagging, scoring
    3. **Organize** — deduplicate by URL, normalize fields, validate
    4. **Save** — write individual JSON articles to ``knowledge/articles/``

Usage:
    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10 --dry-run
    python pipeline/pipeline.py --verbose
    python pipeline/pipeline.py --step 1                  # collect raw only
    python pipeline/pipeline.py --step 2 --step 3 --step 4  # analyze + save
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx

try:
    from model_client import chat_with_retry, create_provider, get_tracker
except ImportError:
    from pipeline.model_client import chat_with_retry, create_provider, get_tracker

logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CST = timezone(timedelta(hours=8))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"
VALIDATE_SCRIPT = PROJECT_ROOT / "hooks" / "validate_json.py"

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_API_BASE = "https://api.github.com"

RSS_FEEDS: list[str] = [
    "https://hnrss.org/frontpage",
    "https://hnrss.org/newest?q=AI+LLM+agent+langchain",
]

GITHUB_SEARCH_QUERY = "ai+llm+agent in:readme,topic"
GITHUB_BACKUP_QUERIES = [
    "topic:ai sort:stars",
    "topic:llm sort:stars",
    "topic:agent sort:stars",
]

CATEGORIES = {"model_release", "research", "tool", "opinion"}

ANALYSIS_PROMPT = """You are an AI/LLM/Agent industry analyst. Analyze the following item and return ONLY a JSON object (no markdown wrapping).

Required JSON structure:
{{
  "summary": "Chinese summary, 20-100 characters, one factual sentence",
  "translated_summary": "If original is English translate to Chinese, otherwise keep original, 80-120 characters",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "one of: model_release, research, tool, opinion",
  "language": "en or zh or ja",
  "score": float between 0.0 and 1.0 (0.9+ only for breakthrough significance)
}}

Title: {title}
URL: {url}
Description: {description}"""

# ---------------------------------------------------------------------------
# Step 1 — Collect
# ---------------------------------------------------------------------------


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def collect_github(limit: int) -> list[dict]:
    """Fetch AI/LLM/Agent related repositories from GitHub Search API.

    Args:
        limit: Maximum number of repos to return.

    Returns:
        List of raw item dicts with keys:
        ``title``, ``url``, ``description``, ``source``, ``metadata``,
        ``collected_at``.
    """
    items: list[dict] = []
    now = datetime.now(CST).isoformat()
    headers = _github_headers()

    def search_repos(query: str, per_page: int) -> list[dict]:
        params: dict[str, str | int] = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(per_page, 100),
        }
        try:
            resp = httpx.get(
                GITHUB_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", [])
        except httpx.HTTPStatusError as e:
            logger.warning("GitHub search error (%s): %s", query[:40], e)
            return []
        except httpx.RequestError as e:
            logger.warning("GitHub search network error: %s", e)
            return []

    repos: list[dict] = search_repos(GITHUB_SEARCH_QUERY, limit)
    if not repos:
        logger.info("Main query returned 0 items, trying backup topic queries")
        seen_names: set[str] = set()
        for bq in GITHUB_BACKUP_QUERIES:
            if len(repos) >= limit:
                break
            batch = search_repos(bq, limit - len(repos))
            for r in batch:
                name: str = r.get("full_name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    repos.append(r)

    for repo in repos[:limit]:
        full_name: str = repo.get("full_name", "")
        html_url: str = repo.get("html_url", "")
        desc: str = repo.get("description") or ""
        items.append({
            "title": full_name,
            "url": html_url,
            "description": desc,
            "source": "github_trending",
            "metadata": {
                "stars": repo.get("stargazers_count", 0),
                "forks": repo.get("forks_count", 0),
                "language": repo.get("language"),
                "topics": repo.get("topics", []),
            },
            "collected_at": now,
        })
        logger.debug("Collected GitHub repo: %s", full_name)

    return items


def _parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 XML with regex to extract item fields."""
    items: list[dict[str, str]] = []
    pattern = re.compile(r"<item>(.*?)</item>", re.DOTALL)
    title_re = re.compile(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", re.DOTALL)
    link_re = re.compile(r"<link>(.*?)</link>", re.DOTALL)
    desc_re = re.compile(r"<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>", re.DOTALL)
    date_re = re.compile(r"<pubDate>(.*?)</pubDate>", re.DOTALL)

    for match in pattern.finditer(xml_text):
        block = match.group(1)
        title_m = title_re.search(block)
        link_m = link_re.search(block)
        desc_m = desc_re.search(block)
        date_m = date_re.search(block)

        title = (title_m.group(1) or title_m.group(2) or "").strip() if title_m else ""
        link = link_m.group(1).strip() if link_m else ""
        desc = (desc_m.group(1) or desc_m.group(2) or "").strip() if desc_m else ""
        pub_date = date_m.group(1).strip() if date_m else ""

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "pub_date": pub_date,
            })

    return items


def collect_rss(limit: int) -> list[dict]:
    """Fetch items from predefined RSS feeds.

    Args:
        limit: Maximum total items across all feeds.

    Returns:
        List of raw item dicts.
    """
    items: list[dict] = []
    now = datetime.now(CST).isoformat()

    for feed_url in RSS_FEEDS:
        if len(items) >= limit:
            break

        try:
            resp = httpx.get(feed_url, timeout=30)
            resp.raise_for_status()
            parsed = _parse_rss_items(resp.text)

            for entry in parsed[: limit - len(items)]:
                items.append({
                    "title": entry["title"],
                    "url": entry["link"],
                    "description": entry["description"],
                    "source": "hacker_news",
                    "metadata": {
                        "published": entry.get("pub_date", ""),
                    },
                    "collected_at": now,
                })

            logger.info("Fetched %d items from %s", min(len(parsed), limit - len(items) + len(parsed)), feed_url)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.warning("RSS feed error (%s): %s", feed_url, e)

    return items


# ---------------------------------------------------------------------------
# Step 2 — Analyze
# ---------------------------------------------------------------------------


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from LLM output, tolerating markdown fences."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def analyze_items(items: list[dict]) -> list[dict]:
    """Run LLM analysis on each raw item.

    Args:
        items: Raw items from the collect step.

    Returns:
        Items augmented with ``summary``, ``tags``, ``category``,
        ``language``, ``score``.
    """
    provider = create_provider()
    analyzed: list[dict] = []

    for idx, item in enumerate(items):
        title: str = item.get("title", "")
        url: str = item.get("url", "")
        desc: str = item.get("description", "")
        logger.info("Analyzing [%d/%d]: %s", idx + 1, len(items), title)

        prompt = ANALYSIS_PROMPT.format(title=title, url=url, description=desc)

        try:
            resp = chat_with_retry(
                [{"role": "user", "content": prompt}],
                provider=provider,
                temperature=0.3,
                max_tokens=512,
            )
            parsed = _parse_llm_json(resp.content)

            if parsed and isinstance(parsed, dict):
                item["summary"] = parsed.get("summary", desc)
                item["translated_summary"] = parsed.get("translated_summary", "")
                item["tags"] = [t for t in parsed.get("tags", []) if isinstance(t, str)]
                item["category"] = parsed.get("category", "tool") if parsed.get("category") in CATEGORIES else "tool"
                item["language"] = parsed.get("language", "en") if parsed.get("language") in {"en", "zh", "ja"} else "en"
                raw_score = parsed.get("score", 0.5)
                item["score"] = float(raw_score) if isinstance(raw_score, int | float) else 0.5
                logger.info("  → score=%.2f category=%s tags=%s", item["score"], item["category"], item["tags"])
            else:
                logger.warning("  → LLM returned invalid JSON, using fallback")
                item["summary"] = desc
                item["translated_summary"] = ""
                item["tags"] = ["AI"]
                item["category"] = "tool"
                item["language"] = "en"
                item["score"] = 0.5

        except Exception as e:
            logger.error("  → LLM analysis failed: %s", e)
            item["summary"] = desc
            item["translated_summary"] = ""
            item["tags"] = ["AI"]
            item["category"] = "tool"
            item["language"] = "en"
            item["score"] = 0.5

        analyzed.append(item)

    return analyzed


# ---------------------------------------------------------------------------
# Step 3 — Organize
# ---------------------------------------------------------------------------


def _article_slug(title: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", title.lower())
    cleaned = re.sub(r"[\s/]+", "-", cleaned)
    return cleaned.strip("-")[:50]


def organize_items(items: list[dict]) -> list[dict]:
    """Deduplicate, normalize, and validate analyzed items.

    Args:
        items: Analyzed items.

    Returns:
        Deduplicated and normalized items.
    """
    now = datetime.now(CST)
    date_str = now.strftime("%Y%m%d")

    seen_urls: set[str] = set()
    existing_ids: set[str] = set()

    if ARTICLES_DIR.is_dir():
        for fpath in ARTICLES_DIR.iterdir():
            if fpath.suffix == ".json":
                m = re.match(r"(\d{8}-\d{3})", fpath.stem)
                if m:
                    existing_ids.add(m.group(1))

    next_index = 1
    while f"{date_str}-{next_index:03d}" in existing_ids:
        next_index += 1

    organized: list[dict] = []
    for item in items:
        url: str = item.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        entry_id = f"{date_str}-{next_index:03d}"
        slug = _article_slug(item.get("title", "untitled"))
        collected_at: str = item.get("collected_at", now.isoformat())

        article: dict[str, Any] = {
            "id": entry_id,
            "title": item.get("title", "untitled"),
            "source": item.get("source", "unknown"),
            "source_url": url,
            "summary": item.get("summary", ""),
            "translated_summary": item.get("translated_summary", ""),
            "tags": item.get("tags", []),
            "category": item.get("category", "tool"),
            "language": item.get("language", "en"),
            "collected_at": collected_at,
            "status": "pending",
            "score": item.get("score", 0.5),
        }

        item["_filename"] = f"{date_str}-{slug}.json"
        item["_article"] = article
        organized.append(item)
        next_index += 1

    return organized


# ---------------------------------------------------------------------------
# Step 4 — Save
# ---------------------------------------------------------------------------


def save_items(items: list[dict], dry_run: bool = False) -> list[Path]:
    """Write each item as an individual JSON article file.

    Args:
        items: Organized items with ``_article`` key.
        dry_run: When ``True``, log what would be written without writing.

    Returns:
        List of paths to saved files.
    """
    saved: list[Path] = []
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    for item in items:
        article: dict[str, Any] = item["_article"]
        filename: str = item["_filename"]
        filepath = ARTICLES_DIR / filename

        if not dry_run:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

        logger.info("%s %s", "[DRY-RUN]" if dry_run else "  Wrote", filename)
        saved.append(filepath)

    if not dry_run:
        _run_validation()

    return saved


def _run_validation() -> None:
    if not VALIDATE_SCRIPT.is_file():
        logger.warning("validate_json.py not found, skipping validation")
        return

    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), f"{ARTICLES_DIR}/*.json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Validation issues:\n%s", result.stdout)
        else:
            logger.info("All articles passed validation")
    except subprocess.TimeoutExpired:
        logger.warning("Validation timed out")


# ---------------------------------------------------------------------------
# Raw data persistence
# ---------------------------------------------------------------------------


def _save_raw(items: list[dict]) -> Path:
    """Persist raw items to ``knowledge/raw/``."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(CST)
    filepath = RAW_DIR / f"pipeline-raw-{now.strftime('%Y-%m-%d-%H%M%S')}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "source": "pipeline",
            "collected_at": now.isoformat(),
            "item_count": len(items),
            "items": items,
        }, f, ensure_ascii=False, indent=2)

    return filepath


# ---------------------------------------------------------------------------
# Step runners
# ---------------------------------------------------------------------------


def _load_latest_raw() -> list[dict]:
    """Load items from the most recent raw data file."""
    if not RAW_DIR.is_dir():
        logger.error("Raw directory not found: %s", RAW_DIR)
        return []

    raw_files = sorted(RAW_DIR.glob("pipeline-raw-*.json"), reverse=True)
    if not raw_files:
        logger.error("No raw data files found in %s", RAW_DIR)
        return []

    latest = raw_files[0]
    logger.info("Loading raw data from %s", latest)
    try:
        with open(latest) as f:
            data = json.load(f)
        items: list[dict] = data.get("items", [])
        logger.info("  Loaded %d items", len(items))
        return items
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load raw data: %s", e)
        return []


SOURCE_HANDLERS: dict[str, Any] = {
    "github": collect_github,
    "rss": collect_rss,
}


def run_pipeline(
    sources: list[str],
    limit: int,
    dry_run: bool = False,
    steps: set[int] | None = None,
) -> int:
    """Execute pipeline steps: collect → analyze → organize → save.

    Args:
        sources: Source names to enable (``github``, ``rss``).
        limit: Maximum items per source.
        dry_run: Skip file writes when ``True``.
        steps: Subset of steps to run. ``None`` means all 4 steps.

    Returns:
        Number of articles produced.
    """
    if steps is None:
        steps = {1, 2, 3, 4}

    logger.info("=" * 50)
    step_list = sorted(steps)
    logger.info("Pipeline start  steps=%s sources=%s limit=%d dry_run=%s",
                step_list, ",".join(sources), limit, dry_run)
    logger.info("=" * 50)

    data: list[dict] = []

    # Step 1 — Collect
    if 1 in steps:
        logger.info("")
        logger.info("─" * 40)
        logger.info("Step 1/4: Collect")
        logger.info("─" * 40)

        for name in sources:
            handler = SOURCE_HANDLERS.get(name)
            if handler is None:
                logger.warning("Unknown source: %s (skip)", name)
                continue
            logger.info("Collecting from: %s", name)
            items = handler(limit)
            logger.info("  Collected %d items from %s", len(items), name)
            data.extend(items)

        if not data:
            logger.warning("No items collected, aborting")
            return 0

        raw_path = _save_raw(data)
        logger.info("Raw data saved to %s", raw_path)
    elif 2 in steps:
        data = _load_latest_raw()
        if not data:
            return 0

    # Step 2 — Analyze
    if 2 in steps:
        logger.info("")
        logger.info("─" * 40)
        logger.info("Step 2/4: Analyze (%d items)", len(data))
        logger.info("─" * 40)

        data = analyze_items(data)

    # Step 3 — Organize
    if 3 in steps:
        logger.info("")
        logger.info("─" * 40)
        logger.info("Step 3/4: Organize (%d items → dedup)", len(data))
        logger.info("─" * 40)

        data = organize_items(data)
        logger.info("  %d unique items after dedup", len(data))

        if not data:
            logger.warning("No items after dedup, aborting")
            return 0

    # Step 4 — Save
    if 4 in steps:
        logger.info("")
        logger.info("─" * 40)
        logger.info("Step 4/4: Save (%d articles)", len(data))
        logger.info("─" * 40)

        saved = save_items(data, dry_run=dry_run)
        logger.info("  %d files %s", len(saved), "(dry-run, not written)" if dry_run else "written")

    logger.info("")
    logger.info("=" * 50)
    logger.info("Pipeline complete  steps=%s articles=%d", step_list, len(data))
    logger.info("=" * 50)

    return len(data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Base — 4-step automation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sources",
        default="github,rss",
        help="Comma-separated source list (github, rss). Default: github,rss",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum items per source. Default: 10",
    )
    parser.add_argument(
        "--step",
        type=int,
        action="append",
        choices=[1, 2, 3, 4],
        help="Step(s) to run (1=collect, 2=analyze, 3=organize, 4=save). Can be repeated. Default: all 4 steps",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate pipeline without writing files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    source_list = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not source_list:
        logger.error("No sources specified")
        sys.exit(1)

    steps = set(args.step) if args.step else None

    try:
        tracker = get_tracker()
    except ImportError:
        tracker = None

    count = run_pipeline(
        sources=source_list,
        limit=args.limit,
        dry_run=args.dry_run,
        steps=steps,
    )

    if tracker:
        tracker.report()

    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()

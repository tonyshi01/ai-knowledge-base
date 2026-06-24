"""GitHub API 工具模块 - 获取仓库基本信息."""

import logging
import os

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def get_repo_info(owner: str, repo: str) -> dict:
    """获取指定 GitHub 仓库的基本信息（Star 数、Fork 数、描述）.

    Args:
        owner: 仓库所有者.
        repo: 仓库名称.

    Returns:
        包含 stars, forks, description 等信息的字典.

    Raises:
        requests.RequestException: API 请求失败时抛出.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    logger.info("Fetching repo info: %s/%s", owner, repo)
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    return {
        "owner": owner,
        "repo": repo,
        "full_name": data["full_name"],
        "description": data.get("description"),
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
    }

"""Supervisor pattern with Worker → Supervisor quality loop.

Worker produces a JSON analysis report for a given task.
Supervisor scores it on accuracy, depth, and format (each 1-10).
If total score < 7, Worker redoes with feedback (max 3 rounds).

Usage:
    >>> from patterns.supervisor import supervisor
    >>> result = supervisor("Analyze the impact of MCP protocol on AI agents")
    >>> print(result["output"])
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import quick_chat  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

WORKER_SYSTEM = """你是 AI 技术分析师。请按要求完成分析任务。
输出 JSON 格式，包含以下字段：
- summary: 一句话摘要（中文，20-100 字）
- key_points: 3-5 个关键要点（列表）
- recommendation: 建议或结论（中文，30-100 字）

只输出 JSON，不要其他内容。"""

SUPERVISOR_SYSTEM = """你是质量审核专家。请审核以下分析报告。

评分维度（每维度 1-10）：
1. 准确性：信息是否准确无误，逻辑是否严谨
2. 深度：分析是否有洞察力，是否深入本质
3. 格式：是否符合 JSON 规范，结构是否清晰

计算方式：总分 = 准确性 + 深度 + 格式，除以 3 后四舍五入取整。
通过标准：总分 >= 7。

输出严格 JSON 格式：
{"passed": true/false, "score": 1-10, "feedback": "具体改进建议（中文）"}
只输出 JSON，不要其他内容。"""


def _parse_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from LLM output, tolerating markdown fences."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """Run the Worker → Supervisor quality loop.

    Args:
        task: Analysis task description.
        max_retries: Maximum revision rounds (default 3).

    Returns:
        Dict with keys:
        - ``output``: Final analysis report text.
        - ``attempts``: Number of rounds completed.
        - ``final_score``: Final score (1-10).
        - ``warning``: Warning string if retries exhausted (optional).
    """
    logger.info("Supervisor start  task=%.60s  max_retries=%d", task, max_retries)

    worker_output: str = ""
    feedback: str = ""
    final_score: int = 0

    for attempt in range(1, max_retries + 1):
        logger.info("Attempt %d/%d", attempt, max_retries)

        # --- Worker: produce analysis ---
        if attempt == 1:
            resp = quick_chat(task, system=WORKER_SYSTEM, temperature=0.5, max_tokens=1024)
        else:
            revision_prompt = (
                f"原始任务: {task}\n\n"
                f"上次产出:\n{worker_output}\n\n"
                f"审核反馈:\n{feedback}\n\n"
                f"请根据以上反馈改进分析报告，保持 JSON 格式。"
            )
            resp = quick_chat(revision_prompt, system=WORKER_SYSTEM, temperature=0.5, max_tokens=1024)

        worker_output = resp.content

        # --- Supervisor: review & score ---
        review_prompt = f"请审核以下分析报告：\n\n{worker_output}"
        review_resp = quick_chat(review_prompt, system=SUPERVISOR_SYSTEM, temperature=0.2, max_tokens=512)
        review = _parse_json(review_resp.content)

        if review is None:
            review = {"passed": False, "score": 0, "feedback": "审核输出格式错误，使用默认最低分"}

        final_score = review.get("score", 0)
        feedback = review.get("feedback", "请改进分析质量")

        logger.info(
            "  Review: passed=%s  score=%d  feedback=%.50s",
            review.get("passed", False),
            final_score,
            feedback,
        )

        # --- Decide ---
        if review.get("passed", False) or final_score >= 7:
            logger.info("Passed on attempt %d (score=%d)", attempt, final_score)
            return {
                "output": worker_output,
                "attempts": attempt,
                "final_score": final_score,
            }

    # Exhausted retries
    warning = f"超过 {max_retries} 轮审核未通过（最终得分 {final_score}），强制返回结果。"
    logger.warning(warning)
    return {
        "output": worker_output,
        "attempts": max_retries,
        "final_score": final_score,
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# CLI test entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    test_tasks = [
        "请分析 LangGraph 框架的优缺点和适用场景",
        "Compare RAG and fine-tuning for domain-specific LLM applications",
    ]

    for task in test_tasks:
        print(f"\n{'=' * 60}")
        print(f"  Task: {task}")
        print(f"{'=' * 60}")

        result = supervisor(task, max_retries=3)

        print(f"\n  Attempts: {result['attempts']}")
        print(f"  Final Score: {result['final_score']}/10")
        if "warning" in result:
            print(f"  ⚠  Warning: {result['warning']}")
        preview = result["output"][:300]
        print(f"  Output:\n{preview}...")

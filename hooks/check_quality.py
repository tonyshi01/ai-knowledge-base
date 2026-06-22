"""5-dimension quality scoring for knowledge article JSON files.

Usage:
    python hooks/check_quality.py <file_or_glob> [file_or_glob2 ...]

Examples:
    python hooks/check_quality.py knowledge/articles/20260622-github-headroom.json
    python hooks/check_quality.py knowledge/articles/*.json
"""

import glob
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    detail: str = ""

    @property
    def percentage(self) -> float:
        return (self.score / self.max_score * 100) if self.max_score else 0.0


@dataclass
class QualityReport:
    file: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    error: str = ""

    @property
    def total(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def total_max(self) -> int:
        return 100

    @property
    def grade(self) -> str:
        if self.total >= 80:
            return "A"
        if self.total >= 60:
            return "B"
        return "C"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUMMARY = 25
MAX_DEPTH = 25
MAX_FORMAT = 20
MAX_TAGS = 15
MAX_NOISE = 15

STANDARD_TAGS = {
    "agent", "llm", "rag", "mcp", "gpt", "claude", "openai", "anthropic",
    "embedding", "vector", "nlp", "fine-tuning", "prompt-engineering",
    "code-generation", "tool-use", "multimodal", "inference", "caching",
    "knowledge-graph", "token-optimization", "time-series", "forecasting",
    "security", "framework", "sandbox", "automation", "workflow",
    "typeScript", "python", "go", "rust", "shell",
    "open-source", "mit", "apache",
}

NOISE_WORDS_CN = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的", "革命性的",
]

NOISE_WORDS_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "state-of-the-art", "world-class", "best-in-class", "bleeding-edge",
    "paradigm-shift", "disruptive",
]

NOISE_PATTERNS: list[re.Pattern] = (
    [re.compile(w) for w in NOISE_WORDS_CN]
    + [re.compile(w, re.IGNORECASE) for w in NOISE_WORDS_EN]
)

# Score field mapping: 1-10 -> 0-25
DEPTH_MAP = {
    1: 0, 2: 3, 3: 5, 4: 8, 5: 10,
    6: 13, 7: 16, 8: 19, 9: 22, 10: 25,
}


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def score_summary(data: dict) -> DimensionScore:
    text = data.get("summary", "")
    if not isinstance(text, str):
        return DimensionScore("摘要质量", 0, MAX_SUMMARY, "summary 非字符串")

    score = 0.0
    detail_parts: list[str] = []

    if len(text) >= 50:
        score = MAX_SUMMARY
        detail_parts.append(f"{len(text)} 字满分")
    elif len(text) >= 40:
        score = 18
        detail_parts.append(f"{len(text)} 字 18 分")
    elif len(text) >= 30:
        score = 12
        detail_parts.append(f"{len(text)} 字 12 分")
    elif len(text) >= 20:
        score = 6
        detail_parts.append(f"{len(text)} 字基本分")
    else:
        detail_parts.append(f"仅 {len(text)} 字 < 20 基本线")

    tech_keywords = {
        "llm", "agent", "模型", "框架", "工具", "gpt", "claude",
        "mcp", "rag", "推理", "训练", "部署", "开源", "token",
    }
    found = [kw for kw in tech_keywords if kw in text.lower()]
    bonus = min(len(found) * 3, MAX_SUMMARY - score)
    if bonus > 0:
        score += bonus
        detail_parts.append(f"含 {len(found)} 个技术关键词 +{bonus:.0f}")

    return DimensionScore("摘要质量", min(score, MAX_SUMMARY), MAX_SUMMARY, "; ".join(detail_parts))


def score_depth(data: dict) -> DimensionScore:
    raw = data.get("score")
    if not isinstance(raw, int):
        return DimensionScore("技术深度", 0, MAX_DEPTH, "缺少 score 字段")

    mapped = DEPTH_MAP.get(raw, 0)
    detail = f"score={raw} → {mapped} 分"
    return DimensionScore("技术深度", float(mapped), MAX_DEPTH, detail)


def score_format(data: dict) -> DimensionScore:
    checks = {
        "id": ("id", str),
        "title": ("title", str),
        "source_url": ("source_url", str),
        "status": ("status", str),
        "collected_at": ("collected_at", str),
    }

    passed = 0
    details: list[str] = []
    for label, (field, tp) in checks.items():
        val = data.get(field)
        if isinstance(val, tp) and len(str(val)) > 0:
            passed += 1
        else:
            details.append(f"缺 {field}")

    score = passed * 4  # 5 fields × 4 = 20 max
    detail = f"5 项中通过 {passed} 项 → {score} 分"
    if details:
        detail += " (" + ", ".join(details) + ")"
    return DimensionScore("格式规范", float(score), MAX_FORMAT, detail)


def score_tags(data: dict) -> DimensionScore:
    tags = data.get("tags")
    if not isinstance(tags, list):
        return DimensionScore("标签精度", 0, MAX_TAGS, "tags 非列表")

    count = len(tags)
    if count == 0:
        return DimensionScore("标签精度", 0, MAX_TAGS, "无标签")

    detail_parts: list[str] = []

    if 1 <= count <= 3:
        tag_score = 10.0
        detail_parts.append(f"{count} 个标签 10 分")
    elif 4 <= count <= 5:
        tag_score = 7.0
        detail_parts.append(f"{count} 个标签 7 分（建议 ≤3）")
    else:
        tag_score = 4.0
        detail_parts.append(f"{count} 个标签 4 分（建议 ≤3）")

    non_standard = [t for t in tags if t.lower() not in STANDARD_TAGS]
    if non_standard:
        penalty = min(len(non_standard) * 3, 10.0)
        tag_score = max(tag_score - penalty, 0)
        detail_parts.append(f"{len(non_standard)} 个非标准标签 -{penalty:.0f}")
    else:
        bonus = 5.0 if count <= 3 else 3.0
        tag_score = min(tag_score + bonus, MAX_TAGS)
        detail_parts.append(f"全标准标签 +{bonus:.0f}")

    return DimensionScore("标签精度", min(tag_score, MAX_TAGS), MAX_TAGS, "; ".join(detail_parts))


def score_noise(data: dict) -> DimensionScore:
    text_fields = [
        str(data.get(k, "")) for k in ("title", "summary", "highlights")
    ]
    haystack = " ".join(text_fields)

    hits: list[str] = []
    for pattern in NOISE_PATTERNS:
        if pattern.search(haystack):
            hits.append(pattern.pattern)

    if not hits:
        return DimensionScore("空洞词检测", MAX_NOISE, MAX_NOISE, "未发现空洞词")

    penalty = min(len(hits) * 5, MAX_NOISE)
    score = MAX_NOISE - penalty
    detail = f"发现 {len(hits)} 个空洞词 -{penalty} 分: {', '.join(hits[:5])}"
    return DimensionScore("空洞词检测", float(score), MAX_NOISE, detail)


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

BAR_LEN = 20


def _bar(ratio: float) -> str:
    filled = int(ratio * BAR_LEN)
    return "█" * filled + "░" * (BAR_LEN - filled)


def _grade_color(grade: str) -> str:
    return {"A": "\033[92m", "B": "\033[93m", "C": "\033[91m"}.get(grade, "")


RESET = "\033[0m"


def print_report(report: QualityReport) -> None:
    print(f"\n{'=' * 52}")
    print(f"  文件: {report.file}")
    if report.error:
        print(f"  ⚠  {report.error}")
        print(f"{'=' * 52}")
        return

    for d in report.dimensions:
        pct = d.percentage / 100
        bar = _bar(pct)
        print(f"  {d.name:　<6} {bar} {d.score:5.1f}/{d.max_score:<3}  {d.detail}")

    print(f"  {'─' * 50}")
    grade = report.grade
    color = _grade_color(grade)
    print(f"  {'总分':　<6} {_bar(report.total / report.total_max)} "
          f"{report.total:5.1f}/{report.total_max}  "
          f"{color}等级 {grade}{RESET}")
    print(f"{'=' * 52}")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def evaluate(data: object, file_path: str) -> QualityReport:
    report = QualityReport(file=file_path)

    if not isinstance(data, dict):
        report.error = f"顶层结构应为 dict, 实际 {type(data).__name__}"
        return report

    report.dimensions = [
        score_summary(data),
        score_depth(data),
        score_format(data),
        score_tags(data),
        score_noise(data),
    ]
    return report


def process_file(file_path: Path) -> QualityReport:
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return QualityReport(file=str(file_path), error=f"无法读取: {e}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return QualityReport(file=str(file_path), error=f"JSON 解析失败: {e}")

    return evaluate(data, str(file_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_paths(raw_args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in raw_args:
        p = Path(arg)
        if p.is_absolute() or not glob.has_magic(arg):
            if p.exists():
                paths.append(p.resolve())
            continue
        for match in Path().glob(arg):
            paths.append(match.resolve())
        if not any(Path().glob(arg)):
            paths.append(p)
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return sorted(unique)


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python hooks/check_quality.py <json_file> [json_file2 ...]")
        sys.exit(1)

    targets = resolve_paths(sys.argv[1:])
    if not targets:
        print("未找到匹配的文件")
        sys.exit(1)

    reports: list[QualityReport] = []
    total = len([t for t in targets if t.suffix == ".json"])
    processed = 0

    for file_path in targets:
        if file_path.suffix != ".json":
            continue
        processed += 1
        print(f"\r  进度: {processed}/{total}", end="")
        reports.append(process_file(file_path))

    print()
    for r in reports:
        print_report(r)

    grade_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for r in reports:
        if not r.error:
            grade_counts[r.grade] = grade_counts.get(r.grade, 0) + 1

    print(f"\n  汇总: A={grade_counts.get('A', 0)}  B={grade_counts.get('B', 0)}  "
          f"C={grade_counts.get('C', 0)}  共 {len(reports)} 文件")

    has_c = any(r.grade == "C" and not r.error for r in reports)
    sys.exit(1 if has_c else 0)


if __name__ == "__main__":
    main()

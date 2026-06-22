"""Validate knowledge article JSON files.

Usage:
    python hooks/validate_json.py <file_or_glob> [file_or_glob2 ...]

Examples:
    python hooks/validate_json.py knowledge/articles/20260622-github-headroom.json
    python hooks/validate_json.py knowledge/articles/*.json
"""

import glob
import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

ID_PATTERN = re.compile(r"^[a-z]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://")
VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}


def check_required_fields(
    data: object, path: str, errors: list[str],
) -> None:
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"  [{path}] 缺少必填字段: {field}")
            continue
        value = data[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"  [{path}] 字段类型错误: {field}="
                f"期望 {expected_type.__name__}, 实际 {type(value).__name__}"
            )


def check_id_format(data: object, path: str, errors: list[str]) -> None:
    value = data.get("id", "")
    if not isinstance(value, str):
        return
    if not ID_PATTERN.match(value):
        errors.append(
            f"  [{path}] ID 格式错误: {value!r} "
            f"(期望模式: {{source}}-{{YYYYMMDD}}-{{NNN}}, 例如 github-20260317-001)"
        )


def check_status(data: object, path: str, errors: list[str]) -> None:
    value = data.get("status", "")
    if not isinstance(value, str):
        return
    if value not in VALID_STATUSES:
        valid = ", ".join(sorted(VALID_STATUSES))
        errors.append(
            f"  [{path}] status 无效: {value!r} (有效值: {valid})"
        )


def check_url(data: object, path: str, errors: list[str]) -> None:
    value = data.get("source_url", "")
    if not isinstance(value, str):
        return
    if not URL_PATTERN.match(value):
        errors.append(f"  [{path}] URL 格式无效: {value!r} (需以 http:// 或 https:// 开头)")


def check_summary(data: object, path: str, errors: list[str]) -> None:
    value = data.get("summary", "")
    if not isinstance(value, str):
        return
    if len(value) < 20:
        errors.append(
            f"  [{path}] 摘要太短: {len(value)} 字 (最少 20 字)"
        )


def check_tags(data: object, path: str, errors: list[str]) -> None:
    value = data.get("tags")
    if not isinstance(value, list):
        return
    if len(value) < 1:
        errors.append(f"  [{path}] 标签至少 1 个")


def check_score(data: object, path: str, errors: list[str]) -> None:
    value = data.get("score")
    if value is None:
        return
    if not isinstance(value, int):
        errors.append(
            f"  [{path}] score 类型错误: 期望 int, 实际 {type(value).__name__}"
        )
        return
    if value < 1 or value > 10:
        errors.append(f"  [{path}] score 超出范围: {value} (有效范围: 1-10)")


def check_audience(data: object, path: str, errors: list[str]) -> None:
    value = data.get("audience")
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(
            f"  [{path}] audience 类型错误: 期望 str, 实际 {type(value).__name__}"
        )
        return
    if value not in VALID_AUDIENCES:
        valid = ", ".join(sorted(VALID_AUDIENCES))
        errors.append(
            f"  [{path}] audience 无效: {value!r} (有效值: {valid})"
        )


def validate_file(file_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(f"  [{file_path}] 无法读取文件: {e}")
        return errors

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        errors.append(f"  [{file_path}] JSON 解析失败: {e}")
        return errors

    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        errors.append(f"  [{file_path}] 顶层结构应为 dict 或 list, 实际 {type(data).__name__}")
        return errors

    for idx, item in enumerate(items):
        prefix = f"{file_path}[{idx}]"
        check_required_fields(item, prefix, errors)
        check_id_format(item, prefix, errors)
        check_status(item, prefix, errors)
        check_url(item, prefix, errors)
        check_summary(item, prefix, errors)
        check_tags(item, prefix, errors)
        check_score(item, prefix, errors)
        check_audience(item, prefix, errors)

    return errors


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
        print("用法: python hooks/validate_json.py <json_file> [json_file2 ...]")
        sys.exit(1)

    targets = resolve_paths(sys.argv[1:])
    if not targets:
        print("未找到匹配的文件")
        sys.exit(1)

    all_errors: dict[str, list[str]] = {}
    total_files = 0
    total_items = 0
    failed_files = 0

    for file_path in targets:
        if file_path.suffix != ".json":
            continue
        total_files += 1
        errors = validate_file(file_path)
        if errors:
            all_errors[str(file_path)] = errors
            failed_files += 1
        else:
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else [data]
                total_items += len(items)
            except Exception:
                total_items += 0

    print("=" * 50)
    print("  知识条目 JSON 校验报告")
    print("=" * 50)

    if all_errors:
        for file_path, errors in all_errors.items():
            print(f"\n❌ {file_path}")
            for err in errors:
                print(err)
    else:
        print("\n✅ 全部校验通过")

    print()
    print("-" * 50)
    print(f"  文件数:   {total_files}")
    print(f"  条目数:   {total_items}")
    print(f"  通过:     {total_files - failed_files}")
    print(f"  失败:     {failed_files}")
    print("-" * 50)

    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()

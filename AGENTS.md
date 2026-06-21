# AI Knowledge Base — Agent 协作指南

## 项目概述

AI Knowledge Base 是一个自动化知识管理助手，每日从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的高质量技术动态，通过 AI 分析、摘要、分类后结构化为 JSON 知识条目，并支持多渠道（Telegram / 飞书）分发推送，帮助团队持续跟踪前沿技术趋势。

## 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.12 |
| Agent 框架 | OpenCode + 国产大模型（DeepSeek / Qwen / GLM） |
| 工作流编排 | LangGraph |
| 爬虫框架 | OpenClaw |
| 数据存储 | JSON 文件系统 |
| 消息分发 | Telegram Bot API / 飞书自定义机器人 |

## 编码规范

- **代码风格**：遵循 PEP 8，使用 `snake_case` 命名
- **文档注释**：强制使用 Google 风格 docstring
- **类型标注**：所有函数参数和返回值必须标注类型
- **日志**：使用 `logging` 模块，禁止裸 `print()` 输出
- **错误处理**：异常需捕获并记录，禁止吞异常或 pass 留空
- **导入顺序**：标准库 → 第三方库 → 本地模块，每类之间空一行

**Google 风格 docstring 示例**：

```python
def fetch_trending(top_n: int) -> list[dict]:
    """从 GitHub Trending 获取热门仓库列表.

    Args:
        top_n: 返回的仓库数量上限.

    Returns:
        每个元素包含 repo 名称、描述、star 数等信息的字典列表.

    Raises:
        ConnectionError: 当请求 GitHub 超时时抛出.
    """
```

## 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/          # Agent 定义文件（采集/分析/整理）
│   ├── skills/          # Agent 技能（爬虫技能、分析技能等）
│   ├── package.json
│   └── skills.json
├── knowledge/
│   ├── raw/             # 原始采集结果（未加工的 HTML/MD）
│   └── articles/        # 结构化 JSON 知识条目（分析后的最终产物）
├── AGENTS.md            # 本文件
└── README.md
```

## 知识条目 JSON 格式

```json
{
  "id": "20260621-001",
  "title": "OpenAI 发布 GPT-5",
  "source": "github_trending",
  "source_url": "https://github.com/example/repo",
  "summary": "OpenAI 发布了 GPT-5 模型，在推理和代码生成方面有显著提升……",
  "translated_summary": "OpenAI 发布了 GPT-5 模型……",
  "tags": ["LLM", "OpenAI", "GPT-5"],
  "category": "model_release",
  "language": "en",
  "collected_at": "2026-06-21T08:00:00+08:00",
  "status": "pending",
  "score": 0.92
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 唯一标识 `YYYYMMDD-NNN` |
| `title` | string | 原始标题 |
| `source` | string | 来源（`github_trending` / `hacker_news`） |
| `source_url` | string | 原文链接 |
| `summary` | string | AI 生成的摘要 |
| `tags` | array[string] | 标签列表 |
| `category` | string | 分类（`model_release` / `research` / `tool` / `opinion`） |
| `language` | string | 原文语种（`en` / `zh` / `ja`） |
| `collected_at` | string | ISO 8601 采集时间 |
| `status` | string | `pending` / `reviewed` / `published` / `archived` |
| `score` | float | AI 相关性评分 0–1 |

## Agent 角色概览

| 角色 | 职责 | 输入 | 输出 | 技能文件 |
|------|------|------|------|---------|
| **采集器** | 定时爬取 GitHub Trending 和 Hacker News | 空（定时触发） | 原始 HTML / Markdown 写入 `knowledge/raw/` | `crawler_skill.json` |
| **分析器** | AI 解析原始内容，生成摘要、标签、分类、评分 | `knowledge/raw/` 中的原始文件 | 结构化 JSON 写入 `knowledge/articles/` | `analyzer_skill.json` |
| **整理器** | 状态管理、去重、质量过滤、多渠道分发 | `knowledge/articles/` 中的 JSON | 推送到 Telegram / 飞书，更新状态 | `distributor_skill.json` |

三条 Agent 通过 LangGraph 编排为有向无环图（DAG）：**采集器 → 分析器 → 整理器**。

## 红线（绝对禁止）

1. **禁止将 API Key / Token / Secret 硬编码在代码中**，必须通过环境变量或 `.env` 注入
2. **禁止在知识条目中存储原始 HTML**，仅保留结构化摘要
3. **禁止修改已发布的 JSON 条目状态**（`status: published` 为终态，只读）
4. **禁止采集非公开/需登录的内容**，仅爬取公开页面
5. **禁止删除 `knowledge/articles/` 中的任何文件**，仅允许通过状态变更标记归档

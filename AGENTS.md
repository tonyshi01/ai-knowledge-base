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

### 要做什么

- **格式化**
  - Python: Black
  - TypeScript: Prettier（`semi: true`, `singleQuote: true`）
- **Python 类型标注**（PEP 484）
  - 语法：Python 3.12 新语法（`list[X]`、`dict[str, X]`、`X | Y`、`X | None`），禁止旧写法
  - 范围：所有函数签名（参数 + 返回值）全部标注，不区分公开/私有
  - 变量：非显而易见时才标注
  - 检查器：mypy（与 CI 联动）
- **TypeScript 严格模式**
  - `tsconfig.json` 开启 `strict: true` + `noUncheckedIndexedAccess`
  - 禁止 `any`（ESLint `@typescript-eslint/no-explicit-any: error`），第三方类型缺失用 `.d.ts` 补齐
- **文档注释**
  - 所有公开导出函数必须有文档
  - Python: Google 风格 docstring（`Args:` / `Returns:` / `Raises:` 必写）
  - TypeScript: JSDoc（`@param` / `@returns` / `@throws` 必写）
  - CI 强制：ruff（`pydocstyle`）+ `eslint-plugin-jsdoc`，缺则 fail
  - 非导出内部函数（`_` 前缀或模块私有）不强制
- **日志规范**
  - Python: `logging` 模块，禁止 `print()`；级别：`info`（日常）/ `debug`（开发）/ `warning`（非中断异常）/ `error`（中断）
  - TypeScript: `console.log` 即可，不引入第三方 logger
  - 格式：`2026-06-22T10:00:00 INFO [模块名] 消息`
- **错误处理**
  - Python: 每个 `try` 必须捕获具体异常类型，禁止 `except:` 留空；LangGraph node 内捕获异常返回 `{"error": ...}` 状态，不抛到图层面
  - TypeScript: `async/await` + try/catch，禁止裸 `.then()` / `.catch()` 链
- **命名规范**
  - Python: `snake_case`（函数/变量）、`PascalCase`（类）、`UPPER_SNAKE_CASE`（常量）
  - TypeScript: `camelCase`（变量/函数）、`PascalCase`（类型/接口/类）、`UPPER_SNAKE_CASE`（常量）
- **导入顺序**
  - Python: 标准库 → 第三方库 → 本地模块，每类之间空一行
  - TypeScript: 外部库 → 内部模块 → 相对路径引入，每类之间空一行
- **异步**
  - Python: 使用 `asyncio` / `async def`
  - TypeScript: 优先使用 `async/await`，避免裸 `.then()` / `.catch()`

### 不做什么

- **不用魔法字符串**：同一字面量在业务逻辑中出现 ≥2 次即视作魔法字符串
  - Python 用 `StrEnum`（3.11+），TypeScript 用 `const enum` 或 `as const`
  - 落地：Code Review + 类型约束（传枚举而非裸 `str`）
- **不允许 TODO / FIXME / HACK / XXX 提交到 main**
  - pre-commit 钩子拦截（lefthook），仅阻止推往 `main`
  - 例外出：`TODO(ISSUE-123): ...`（带 issue 编号的计划内事项允许）

### 边界 & 验收

- 单测框架：pytest（Python）+ vitest（TypeScript）
- 要求：分支覆盖率（branch coverage）> 80%
- 粒度：全局平均 > 80%，单模块最低 ≥ 60%
- 不计入：`__init__.py`、脚手架/配置文件、`*.d.ts`、测试文件本身

### 怎么验证

- CI 平台：GitHub Actions
- PR 触发（push 到 main 额外触发一次）
- Python:
  - `ruff check .`（fail on error）
  - `mypy .`
  - `pytest --cov --cov-branch --cov-fail-under=81`
- TypeScript:
  - `eslint src/`
  - `tsc --noEmit`
  - `vitest run --coverage`
- 额外：`pre-commit run --all-files`（确保本地 pre-commit 配置与 CI 一致）

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

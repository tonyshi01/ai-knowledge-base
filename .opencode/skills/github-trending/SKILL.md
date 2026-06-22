---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

采集 GitHub Trending 上的热门开源项目，提取关键信息并输出结构化 JSON。

## 使用场景

- 每日采集 GitHub Trending 热门项目
- 筛选 AI/LLM/Agent 领域相关项目
- 生成结构化知识条目供后续分析

## 执行步骤

### 1. 搜索热门仓库

通过 GitHub API 获取 Trending 仓库列表：

```
GET https://api.github.com/search/repositories?q=...&sort=stars&order=desc
```

优先使用 GitHub 官方 API（需配置 `GITHUB_TOKEN`），备选方案为 WebFetch 抓取 `https://github.com/trending` 页面。

### 2. 提取信息

从搜索结果中提取以下字段：

| 字段 | 说明 |
|------|------|
| `name` | 仓库全名（`owner/repo`） |
| `url` | 仓库地址 |
| `stars` | Star 总数 |
| `language` | 主要编程语言 |
| `topics` | 仓库标签列表 |
| `description` | 英文描述 |

### 3. 过滤

**纳入条件**（满足任一即可）：
- 项目描述或 topics 包含 `AI`、`LLM`、`Agent`、`GPT`、`Claude`、`RAG`、`MCP`、`embedding`、`vector`、`machine learning`、`deep learning`、`NLP`、`langchain`、`Copilot` 等关键词
- 项目明显属于 AI 工具/框架/模型/应用
- 项目作者或组织为知名 AI 团队（OpenAI、Anthropic、Google DeepMind、Meta AI、Hugging Face 等）

**排除条件**（满足任一即跳过）：
- Awesome 列表（`awesome-*` 仓库）
- 与 AI/LLM/Agent 完全无关的项目
- 非技术类项目

### 4. 去重

与 `knowledge/articles/` 中已有条目比对，按 URL 去重，已存在则跳过。

### 5. 撰写中文摘要

每条摘要遵循固定公式：

```
{项目名} 是一个{项目类型}，{做什么}。{为什么值得关注}。
```

示例：
> headroom 是一个 LLM 上下文压缩工具，在工具输出到达大模型前进行智能压缩。可减少 60-95% 的 token 消耗，提供 Library/Proxy/MCP 三种集成方式。

### 6. 排序

按 Star 总数从高到低排序，取 Top 15。

### 7. 输出 JSON

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`。

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-06-22T08:00:00+08:00",
  "items": [
    {
      "name": "chopratejas/headroom",
      "url": "https://github.com/chopratejas/headroom",
      "summary": "headroom 是一个 LLM 上下文压缩工具，在工具输出到达大模型前进行智能压缩。可减少 60-95% 的 token 消耗，提供 Library/Proxy/MCP 三种集成方式。",
      "stars": 44800,
      "language": "Python",
      "topics": ["llm", "compression", "mcp", "agent"]
    }
  ]
}
```

## 注意事项

- 优先使用 GitHub API 以获得结构化数据，API 限流时降级为页面抓取
- `GITHUB_TOKEN` 从环境变量读取，禁止硬编码
- 摘要必须真实反映项目功能，不编造数据
- 过滤时宁可多收录后由分析环节筛除，不可遗漏相关项目
- 写入文件前确保 `knowledge/raw/` 目录存在
- YYYY-MM-DD 使用采集当日的 UTC+8 日期

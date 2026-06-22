---
name: github-trending
description: >
  当用户说「这周 GitHub 上有什么好项目」「帮我扫一下 trending」「看看最近什么开源项目火」
  「找 AI/LLM/Agent 相关的热门仓库」「采集 GitHub 趋势」「爬取热门开源项目」「推荐本周值得关注的项目」
  「Top 50 trending repos」时使用此技能。
  也供其他 skill 需要获取 GitHub 热门项目列表时调用。
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# github-trending · 趋势采集

抓 `github.com/trending` 全文解析，过 topics 筛子，吐出结构化 JSON。

## 步骤

### 1. 抓取

WebFetch 爬 `https://github.com/trending?since=weekly`。

失败时返回空数组 `[]`，不抛。

### 2. 解析

从 HTML 提取全部仓库行，每条产出：

- `name` — `owner/repo`
- `url` — `https://github.com/{name}`
- `stars` — 整数，剔除逗号
- `topics` — 页面标签列表
- `description` — 英文描述

### 3. 过筛

保留 `topics` 与以下任一词匹配的行：

```
ai, llm, agent, ml, deep-learning, nlp, llm, gpt, claude,
rag, mcp, embedding, vector, langchain, copilot
```

**完成标准**: 全部 50 行逐一检查过，无遗漏。

### 4. 输出

stdout 打印 JSON 数组。字段顺序稳定：`name, url, stars, topics, description`。

```json
[
  {
    "name": "chopratejas/headroom",
    "url": "https://github.com/chopratejas/headroom",
    "stars": 45122,
    "topics": ["llm", "compression", "mcp", "agent"],
    "description": "Compress tool outputs, logs, files, and RAG chunks before they reach the LLM."
  }
]
```

## 边界

- 不调 GitHub API（rate limit 紧），只走 HTML
- 不落盘、不入库，只 stdout
- 不做去重——caller 负责
- 单次执行 < 10s；超时则返回 `[]`
- 输出必须通过 jsonschema 校验（见 [`schema.json`](#file-schemajson)）

## 参考

### 筛词表

```
ai, llm, agent, ml, deep-learning, nlp, gpt, claude,
rag, mcp, embedding, vector, langchain, copilot
```

### schema.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["name", "url", "stars", "topics", "description"],
    "properties": {
      "name":        {"type": "string", "pattern": "^[^/]+/[^/]+$"},
      "url":         {"type": "string", "format": "uri"},
      "stars":       {"type": "integer", "minimum": 0},
      "topics":      {"type": "array", "items": {"type": "string"}},
      "description": {"type": "string"}
    },
    "additionalProperties": false
  }
}
```

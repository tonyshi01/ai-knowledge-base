---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# 技术内容深度分析技能

对采集到的技术项目进行逐条深度分析，挖掘技术亮点，发现趋势，输出结构化分析结果。

## 使用场景

- 对 `knowledge/raw/` 中的采集数据进行深度分析
- 为每条项目生成摘要、亮点、评分、标签
- 发现本期采集的共同主题和新兴概念

## 执行步骤

### 1. 读取最新采集文件

扫描 `knowledge/raw/` 目录，找到日期最新的 `github-trending-YYYY-MM-DD.json` 或 `hacker-news-YYYY-MM-DD.json` 文件并读取。

### 2. 逐条深度分析

对每条项目执行以下分析：

**摘要**（≤ 50 字）
- 一句话概括核心功能，简洁有力
- 以项目名开头，不加引号

**技术亮点**（2–3 个）
- 用事实和数据说话，禁止空泛表述
- 优先引用：性能指标、Star 数、技术栈、团队背景、创新点
- 示例：❌ "有重要意义" → ✅ "支持 158 种语言，Linux 内核 3 分钟全索引"

**评分**（1–10 整数）

| 分值 | 含义 | 说明 |
|------|------|------|
| 9–10 | **改变格局** | 重大技术突破、新模型发布、行业标准变更 |
| 7–8 | **直接有帮助** | 新工具/库/实践能用在日常工作流中 |
| 5–6 | **值得了解** | 有意思的进展或观点，背景知识范畴 |
| 1–4 | **可略过** | 与 AI/LLM/Agent 关系不大 |

**评分理由**
- 一句话说明为什么给这个分数，指向具体标准

**标签建议**
- 2–5 个标签，具体不重复
- 禁止 `AI`、`tech` 等大而泛的标签

### 3. 趋势发现

分析完毕后，总结本期发现的：

- **共同主题**：本期项目集中在哪些方向（如 Agent 安全、上下文优化、代码智能）
- **新兴概念**：值得关注的新的技术方向或概念
- **值得特别关注**：评分 ≥ 7 的项目为什么值得深入跟进

### 4. 输出分析结果 JSON

将完整分析结果写入 `knowledge/raw/analysis-YYYY-MM-DD.json`。

## 评分约束

- 每 15 个项目中，9–10 分不得超过 **2 个**（让最高分真正代表改变格局的项目）
- 7–8 分不设上限，按实际质量评定
- 1–4 分用于与 AI/LLM/Agent 弱相关的条目

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "tech-summary",
  "analyzed_at": "2026-06-22T08:00:00+08:00",
  "items": [
    {
      "name": "chopratejas/headroom",
      "url": "https://github.com/chopratejas/headroom",
      "summary": "AI Agent 上下文压缩层，减少 60-95% token 消耗，无损回答质量。",
      "highlights": [
        "6 种压缩算法 + 可逆 CCR 缓存，支持 Library/Proxy/MCP 四种集成模式",
        "经基准测试压缩率 47-92% 且准确率无损，总星数 44.8k"
      ],
      "score": 8,
      "score_reason": "对 Agent 日常使用直接有帮助，显著降低 token 成本，集成方式灵活",
      "tags": ["token-optimization", "LLM", "MCP", "cost-reduction"]
    }
  ],
  "trends": {
    "common_themes": ["Agent 上下文优化", "MCP 生态工具", "AI 安全"],
    "emerging_concepts": ["可逆压缩（CCR）", "Agent 技能安全扫描"],
    "notable_projects": ["headroom（8分，压缩技术成熟度高）"]
  }
}
```

## 注意事项

- 摘要 ≤ 50 字，超出则精简
- 亮点必须有事实和数据支撑，禁止套话（"具有重要意义""值得关注"等）
- 评分严格遵循约束，9–10 分宁缺毋滥
- `knowledge/raw/` 为空时提前退出并提示
- 写入文件前确保 `knowledge/raw/` 目录存在

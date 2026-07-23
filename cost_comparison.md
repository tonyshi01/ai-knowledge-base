# 模型成本对比

## 测试条件

| 项目 | 值 |
|------|-----|
| **测试日期** | `{{DATE}}` |
| **输入数据** | `{{INPUT_DESC}}`（如：GitHub Trending 5 条 + Hacker News 5 条，共 10 条） |
| **任务类型** | AI 摘要生成 + 标签分类 + 相关性评分 |
| **模型参数** | temperature=0.3, max_tokens=512 |
| **重试策略** | 最多 3 次，指数退避 |

## DeepSeek Chat

| 指标 | 值 |
|------|-----|
| 模型 | `deepseek-chat` |
| API 调用次数 | `{{CALLS}}` |
| Prompt Tokens | `{{PROMPT_TOKENS}}` |
| Completion Tokens | `{{COMPLETION_TOKENS}}` |
| 总 Tokens | `{{TOTAL_TOKENS}}` |
| 预估成本 | ¥`{{COST_RMB}}` |
| 每百万 token 输入价格 | ¥1.0 |
| 每百万 token 输出价格 | ¥2.0 |

## Qwen Plus

| 指标 | 值 |
|------|-----|
| 模型 | `qwen-plus` |
| API 调用次数 | `{{QWEN_CALLS}}` |
| Prompt Tokens | `{{QWEN_PROMPT_TOKENS}}` |
| Completion Tokens | `{{QWEN_COMPLETION_TOKENS}}` |
| 总 Tokens | `{{QWEN_TOTAL_TOKENS}}` |
| 预估成本 | ¥`{{QWEN_COST_RMB}}` |
| 每百万 token 输入价格 | ¥4.0 |
| 每百万 token 输出价格 | ¥12.0 |

## 结论

| 维度 | DeepSeek Chat | Qwen Plus |
|------|--------------|-----------|
| 总成本 | ¥`{{COST_RMB}}` | ¥`{{QWEN_COST_RMB}}` |
| 单次调用均价 | ¥`{{AVG_COST}}` | ¥`{{QWEN_AVG_COST}}` |
| 性价比 | `{{WINNER}}` | — |

> **结论**：{{CONCLUSION}}

# AI 代码生成对比：有 Memory vs 无 Memory

以本项目的编码规范为例，对比开启 Memory（已学习 `AGENTS.md` 中的约定）与未开启 Memory 两种情况下 AI 生成的代码差异。

## 对比表格

| 维度 | 无 Memory | 有 Memory（遵循 AGENTS.md） |
|------|-----------|---------------------------|
| **命名风格** | 混合风格，如 `fetchTrending()`、`getRepoList()`、`FetchData` 类名 | 统一 `snake_case`：`fetch_trending()`、`get_repo_list()`、`fetch_data` |
| **docstring** | 简略注释或无注释，如 `# Fetch trending repos` | Google 风格完整 docstring，含 Args / Returns / Raises |
| **日志方式** | `print(f"Fetched {len(data)} repos")` | `logging.info("Fetched %d repos", len(data))` |
| **错误处理** | `try: ... except: pass` 或 `except Exception as e: print(e)` | 精确捕获预期异常，`logging.error()` 记录，不吞异常 |
| **文件位置** | 随意生成在根目录或按通用习惯命名 | 遵循项目结构，采集器代码置于 `.opencode/skills/`，数据写入 `knowledge/raw/` |

## 代码示例对比

### 无 Memory

```python
class DataFetcher:
    def fetchTrending(self):
        # Fetch trending repos
        res = requests.get("https://api.github.com/trending")
        if res.status_code != 200:
            print("Failed to fetch")
            return []
        return res.json()
```

### 有 Memory

```python
import logging

logger = logging.getLogger(__name__)

def fetch_trending(top_n: int) -> list[dict]:
    """从 GitHub 获取 trending 仓库列表.

    Args:
        top_n: 返回的仓库数量上限.

    Returns:
        每个元素包含 repo 名称、描述、star 数等信息的字典列表.

    Raises:
        ConnectionError: 当请求 GitHub 超时时抛出.
    """
    try:
        res = requests.get("https://api.github.com/trending", timeout=10)
        res.raise_for_status()
    except requests.Timeout as e:
        logger.error("请求 GitHub Trending 超时: %s", e)
        raise ConnectionError("GitHub 请求超时") from e
    except requests.RequestException as e:
        logger.error("请求失败: %s", e)
        raise

    data = res.json()
    logger.info("成功获取 %d 个 trending 仓库", len(data))
    return data[:top_n]
```

## 结论

开启 Memory 后，AI 生成代码的核心变化在于：

1. **风格统一** — 所有代码遵循项目既有的命名、类型标注、导入顺序等约定，无需人工 review 后返工。
2. **质量内建** — docstring、日志、错误处理等"非功能性"代码不再被遗漏，因为这些规范已被 Memory 固化。
3. **上下文感知** — 代码自动放置到正确的目录结构下，而非根据模型通用知识猜测。

总的来说，Memory 让 AI 从一个"懂编程的通用助手"转变为"懂你项目的协作者"，大幅减少代码审查成本与重复纠错次数。

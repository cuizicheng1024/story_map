# CLI 边界说明

`cli/` 放的是“面向单次执行”的命令行入口，不承载运行时服务。

## 当前建议

### 主流程 CLI

- `generate_pure_story_map.py`
  - 当前仍在主流程内
  - 用于单人物渲染、批量重渲染、补齐缺失人物页
  - `tools/build/build_all.py` 会通过旧入口 `tools/build_all.py` 调用它

## 维护原则

- 新的运行时能力不要继续加到 `cli/`
- 新的批量校验、批量构建逻辑优先放 `tools/`
- 新的“单次渲染 / 单次导出 / 人工执行入口”才放到 `cli/`

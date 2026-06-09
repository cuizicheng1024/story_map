# CLI 边界说明

`cli/` 放的是“面向单次执行”的命令行入口，不承载运行时服务。

## 当前建议

### 主流程 CLI

- `generate_pure_story_map.py`
  - 当前仍在主流程内
  - 用于单人物渲染、批量重渲染、补齐缺失人物页
  - `tools/build_all.py` 也会调用它

### 历史 / 实验脚本

- `auto_generate.py`
  - 偏早期的一键生成人物 Markdown + HTML 脚本
  - 依赖自己的 LLM 请求实现
  - 当前不建议继续扩展新能力
- `batch_run_mimo_autogen_v2.py`
  - 偏批量生成与批处理实验
  - 逻辑较重，适合后续继续拆分或迁移到专门的 batch 目录

## 维护原则

- 新的运行时能力不要继续加到 `cli/`
- 新的批量校验、批量构建逻辑优先放 `tools/`
- 新的“单次渲染 / 单次导出 / 人工执行入口”才放到 `cli/`

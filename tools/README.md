# Tools 边界说明

`tools/` 放的是“构建、校验、索引生成、数据整理”脚本。

## 当前分层

### 主流程工具

- `build_all.py`
  - 统一构建入口
  - 负责首页数据、人物索引、人物页增量重渲染
- `run_storymap_checks.py`
  - 统一本地自检入口
- `validate_story_markdown.py`
  - 人物 Markdown 结构校验

### 数据构建工具

- `build_people_master.py`
- `build_people_knowledge_graph_pep.py`
- `build_pep_people_spotlight.py`
- `build_pep_people_time_index.py`
- `enrich_pep_people_time_index.py`
- `write_people_union_snapshot.py`

### 数据质量与报告

- `report_low_coverage_places.py`
- `validate_people_info.py`
- `run_two_phase_validation.py`

### 数据同步 / 批处理辅助

- `sync_storymap_examples_from_batch_runs.py`
- `batch_generate_pep_people.py`

## 维护原则

- 会被日常开发频繁执行的入口，应优先保持在少数几个脚本里
- 新的统一流程优先合并到 `build_all.py` 或 `run_storymap_checks.py`
- 一次性的迁移、补数、同步脚本应避免继续膨胀，必要时单独说明输入输出

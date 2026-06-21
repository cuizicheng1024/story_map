# `tools/` 边界说明

`tools/` 放的是"构建、校验、索引生成、数据整理"脚本。

> 重组路线见 [`../docs/reorg_plan.md`](../docs/reorg_plan.md) Step 2。
> 在 Step 2 落地前请**不要重命名以下 hot path 脚本**，它们被 CI / 部署脚本 hardcode。

## 一、Hot Path（不可重命名）

| 文件 | 被谁调 |
| --- | --- |
| `build_all.py` | `scripts/deploy_storymap_release.sh`、`scripts/test_storymap.sh`、本地构建 |
| `build_stellar_homepage.py` | `.github/workflows/deploy-pages.yml`、`build_all.py` |
| `validate_story_markdown.py` | `.github/workflows/deploy-pages.yml`、`build_all.py` |
| `run_storymap_checks.py` | `scripts/test_storymap.sh` |
| `check_pages_deploy.py` | `tests/test_check_pages_deploy.py` |
| `build_work_summary_index.py` | `build_all.py`、`tests/test_build_work_summary_index.py` |

## 二、当前分层（保持原 README 结构 + 补 Step 2 归类）

### 主流程工具（**Step 2 -> `tools/build/`**）

- `build_all.py` — 统一构建入口
- `build_stellar_homepage.py` — 首页构建
- `run_storymap_checks.py` — 本地自检入口 _(Step 2 -> `tools/reports/`)_
- `validate_story_markdown.py` — Markdown 校验 _(Step 2 -> `tools/reports/`)_

### 数据构建工具（**Step 2 -> `tools/build/`**）

- `homepage_search.py` — 首页搜索索引
- `build_people_master.py`
- `build_people_knowledge_graph_pep.py`
- `build_people_summary_index.py`
- `build_pep_people_time_index.py`
- `enrich_pep_people_time_index.py`
- `write_people_union_snapshot.py`
- `build_work_summary_index.py`
- `build_pep_people_spotlight.py`
- `build_neo4j_graph.py`

### 数据质量与报告（**Step 2 -> `tools/reports/`**）

- `report_low_coverage_places.py`
- `validate_people_info.py`
- `run_two_phase_validation.py`
- `check_pages_deploy.py`

### 健康检查与维修（**Step 2 -> `tools/debug/`**）

- `check_llm_health.py`
- `test_random_basemaps.py`
- `review_hard_places.py`
- `repair_profile_artifacts.py`

### 一次性 inspect / repro 脚本 ✅ 已搬到 [`oneshot/`](./oneshot/README.md)

> 这些是某次线上问题排查时留下的复现脚本。已统一归入 `tools/oneshot/`，
> 不会被 CI / 部署 / 测试引用。新增类似脚本请直接放 `oneshot/`。

- `oneshot/inspect_lichun_3d_state.py`
- `oneshot/inspect_lichun_firstload.py`
- `oneshot/inspect_lichun_markers.py`
- `oneshot/repro_lichun_amap_fallback.py`
- `oneshot/repro_lichun_console.py`
- `oneshot/repro_lichun_geovis_requests.py`
- `oneshot/repro_lichun_localhost.py`
- `oneshot/repro_lichun_map.py`
- `oneshot/fix_story_markdown_corpus.py`

### 数据同步 / 批处理辅助（**Step 2 -> `tools/extras/`**）

- `sync_storymap_examples_from_batch_runs.py`
- `batch_generate_pep_people.py`
- `run_offline_agent_eval.py`

## 三、维护原则

- 会被日常开发频繁执行的入口，应优先保持在少数几个脚本里
- 新的统一流程优先合并到 `build_all.py` 或 `run_storymap_checks.py`
- 一次性的迁移、补数、同步脚本应避免继续膨胀，必要时单独说明输入输出
- **新增脚本时**：判断属于哪一类（build / reports / debug / oneshot / extras），写在文件顶部 docstring
- **要复现某个线上 issue**：脚本写到 `oneshot/`（Step 2 之后），并在文件名里带 issue/日期

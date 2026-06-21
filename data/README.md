# `data/` 目录说明

`data/` 同时承载三种性质完全不同的文件。

当前的 Step 3 状态：
- `data/corpus/` 已承载长期入仓的索引/语料真实文件
- `data/reports/` 与 `data/runtime/` 已建立目录
- 旧 `data/*.json` / `data/*.md` 路径先保留兼容软链，避免现有脚本、CI、tests 与人工排障命令立即失效
- 面向仓库真实路径的 `scripts/`、`tests/`、workflow 默认入口已切到新分层目录
- 这意味着 Step 3 的主路径切换已完成，但兼容层清理与读路径收敛还未收尾

拆分计划见 [`../docs/reorg_plan.md`](../docs/reorg_plan.md) Step 3。

## 一、文件分类与生命周期

### A. 长期入仓的语料 / 索引（committed）
代码运行前提，必须随版本走。

| 文件 | 写出者 | 读取者 |
| --- | --- | --- |
| `historical_places_index.jsonl` | 人工 / 离线脚本 | `geocode_service.py`、Agent 地名兜底 |
| `place_aliases.json` | 人工维护 | `geocode_service.py`、`map_client.py` |
| `people_master.json` | `tools/build_people_master.py` | 人物登记、`build_stellar_homepage` |
| `people_master_pep.json` | `tools/build_people_master.py` | 同上 |
| `people_summary_index.json` | `tools/build_people_summary_index.py` | 首页搜索、统计 |
| `work_summary_index.json` | `tools/build_work_summary_index.py` | 人物页作品 Tooltip |
| `people_knowledge_graph.json` | `tools/build_people_knowledge_graph_pep.py` | 图谱 / Neo4j 同步 |
| `people_birth_coords_wgs84.json` | `tools/build_people_master.py` 等 | 首页星座坐标 |
| `pep_*.json`、`pep_*_by_book.json` | PEP 人物时间线/章节抽取 | 首页教材关联 |

### B. 生成产物 / 报告（**.gitignore 已排除，Step 3 后真实位置 = `data/reports/`**）
每次构建都会被覆盖，不要 commit。

| 文件 | 写出者 |
| --- | --- |
| `markdown_smoke_report.json` | `tools/validate_story_markdown.py`（CI 调用） |
| `markdown_full_validation.json` | `tools/validate_story_markdown.py --full` |
| `html_audit_summary.json` | `tools/build_all.py` |
| `low_coverage_story_report.{json,md}` | `tools/report_low_coverage_places.py` |
| `offline_agent_eval_report.json` | `tools/run_offline_agent_eval.py` |
| `performance_baseline.json` | 首页构建写出 |
| `validation_reports/*.json` | 两阶段校验 |

### C. 运行时持续读写（**.gitignore 已排除，Step 3 后真实位置 = `data/runtime/`**）
服务运行过程中由代码持续追加，**不要手动改**。

| 文件 | 写出者 |
| --- | --- |
| `hard_place_review_queue.json` | `story_geocode_api._enqueue_hard_place_review` |
| `hard_place_review_queue.md` | 同上 |

## 二、添加新数据文件的判断流

```
新文件是手工维护或离线一次性生成的？
├── Yes → 类别 A，入仓
└── No  → 是否每次构建都会被覆盖？
    ├── Yes → 类别 B，加 .gitignore
    └── No  → 是运行时队列/缓存？→ 类别 C，加 .gitignore
```

## 三、Step 3 之后的目标布局

```
data/
├── corpus/   ← A 类
├── reports/  ← B 类（.gitignore）
└── runtime/  ← C 类（.gitignore）
```

## 四、兼容策略

- 旧路径如 `data/people_master.json`、`data/markdown_smoke_report.json`、`data/hard_place_review_queue.json`、`data/people_union_snapshot.json` 先保留兼容软链
- 新代码应优先写入：
  - `data/corpus/`
  - `data/reports/`
  - `data/runtime/`
- 当前根目录兼容层已覆盖三类典型入口：
  - corpus：`people_master.json`、`people_summary_index.json`、`work_summary_index.json` 等
  - reports：`markdown_smoke_report.json`、`performance_baseline.json`、`people_union_snapshot.json` 等
  - runtime：`hard_place_review_queue.{json,md}`
- 等 CI、部署脚本和 tests 全部切换完成后，再考虑移除旧路径兼容层

## 五、搬动时仍需联动

**搬动时需要联动**：

- 所有读这些文件的代码（`grep -rn "data/" --include="*.py"`）
- CI 工作流里的 hardcode 路径（`.github/workflows/deploy-pages.yml` 第 68 行）
- 部署脚本里的 `PRESERVE_RUNTIME_DIR` 行为

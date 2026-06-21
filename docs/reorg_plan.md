# 目录重组路线图

> 本文档记录"为什么没一口气改"的判断，以及后续每一步该怎么落地。
> 主版本：2026-06-20。每完成一步请把 status 改成 ✅ 并补 PR 链接。
>
> **Step 1 详细执行手册**：见 [`docs/refactor_step1_playbook.md`](./refactor_step1_playbook.md)。
> 阶段 1.1（`core/`）已落地，剩余 1.2~1.7 的逐文件清单、`__file__.parents[N]` 校对表、转发层模板、验证命令均在该手册里。

## 一、为什么不一口气全做？

仓库当前有 **两条历史包袱** 让大规模 reorg 必须分阶段：

1. **47 处 `sys.path.insert`**：`storymap/script/*.py` 之间互相用裸 `import xxx` 调用（不带包前缀），因此每个入口脚本（`tools/*.py`、`tests/*.py`、`cli/*.py`）都得手动 patch `sys.path` 才能 import 成功。
2. **裸 import 蔓延 48 个文件**：一旦把 `storymap/script/` 拆子包，所有 `import xxx` 都要改成 `from .yyy import xxx`，影响面是其它步骤总和的 5 倍以上。

两条历史包袱让 Step 1 必须**独立分支 + 全测试 + 重新发布**，不适合和其它步骤混在一个 PR 里。

## 二、五步路线图

| Step | 内容 | 状态 | 预估改动量 | 风险 |
| --- | --- | --- | --- | --- |
| Step 1 | 拆 `storymap/script/` 子包 + 清理 `sys.path` patch | ✅ 已完成：真实实现已下沉到 `core/profile/map/agent/api/runtime/cli`，旧根入口保留 shim 兼容，`storymap/script/` 内已无 `sys.path` patch | ~240 处 import + 47 处 sys.path | 高 |
| Step 2 | 拆 `tools/` 到 `build/reports/debug/oneshot/` | ✅ 已完成：真实实现已分层，旧顶层入口保留 shim 兼容 | 30+ 文件移动 + 文档 + 测试 | 中 |
| Step 3 | 拆 `data/` 到 `corpus/reports/runtime/` | ✅ 已完成：真实读写入口已切到新分层，旧根路径仅保留软链兼容与文档说明 | 写出路径 + .gitignore + CI | 中 |
| Step 4 | 拆 `tests/` 到 `unit/integration/data/` | ✅ 已完成：目录拆分、pytest collect、smoke 路径、CI 分层与文档入口均已对齐 | pytest collect + 路径 | 低 |
| Step 5 | 根目录清理 + `docs/` 统一文档 | ✅ 已完成 | 本会话已交付 docs/README、docs/architecture、docs/reorg_plan、.gitignore 扩充 | 极低 |

## 三、Step 1 详细执行清单（已完成）

### 3.1 目标布局
```
storymap/script/
├── __init__.py                    # 新增；空文件或仅 re-export
├── _legacy_path.py                # 可选：保留兼容 sys.path 注入逻辑供未迁移调用方
│
├── core/                          # 基础：parsers, models, person_registry, project_paths
├── profile/                       # profile_builder, map_html_renderer, person_tooltip_js, templates/
├── map/                           # map_client, geocode_service
├── agent/                         # 已存在；把所有 story_agent_*.py 合并进来
├── api/                           # api.py, app_factory.py, *_api.py, proxy.py, static.py
├── runtime/                       # runtime_support, env_utils, story_runtime_*
└── cli/                           # story_cli, story_tooling, story_map.py 的 CLI 部分
```

### 3.2 执行顺序

> 进度更新（2026-06-21）：
> - `core/`、`profile/`、`map/`、`agent/`、`api/`、`runtime/`、`cli/` 子包已建好并开始承接真实实现
> - `models.py`、`parsers.py`、`person_registry.py`、`project_paths.py`、`env_utils.py`、`profile_builder.py`、`map_html_renderer.py`、`person_tooltip_js.py`、`map_client.py`、`geocode_service.py`、`story_geocode_api.py`、`story_agent_*`、`story_runtime_*`、`story_*_api`、`story_cli.py` 等旧根入口已 shim 化
> - 本轮新增完成：`storymap/script/artifacts.py` 已迁入 `storymap/script/core/artifacts.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/story_agents.py` 已迁入 `storymap/script/agent/registry.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/story_tooling.py` 已迁入 `storymap/script/cli/tooling.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/story_generation_tools.py` 已迁入 `storymap/script/agent/generation_tools.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/export_builders.py` 已迁入 `storymap/script/core/export_builders.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/story_task_debug.py` 已迁入 `storymap/script/runtime/task_debug.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/history_qa_agent.py` 已迁入 `storymap/script/runtime/local_history_qa.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/story_task_schema.py` 已迁入 `storymap/script/runtime/task_schema.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/graph_service.py` 已迁入 `storymap/script/profile/graph_service.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/generation_service.py` 已迁入 `storymap/script/agent/generation_service.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/task.py` 已迁入 `storymap/script/runtime/task_service.py`，旧根入口改为转发 shim
> - 本轮继续完成：`storymap/script/offline_eval.py` 已迁入 `storymap/script/agent/offline_eval.py`，旧根入口改为转发 shim
> - 相关回归通过：`79 passed`、`92 passed`、`43 passed`、`122 passed`、`82 passed`、`61 passed`、`45 passed`、`136 passed`、`46 passed`、`45 passed`、`5 passed`

1. **新建子包目录 + `__init__.py`**（空）
2. **逐个文件 `git mv` + 在原位置保留转发 shim**：
   ```python
   # storymap/script/parsers.py (旧位置, 转发 shim)
   from storymap.script.core.parsers import *  # noqa: F401,F403
   from storymap.script.core.parsers import (  # 显式列出常用符号
       parse_story_document, parse_locations, ...
   )
   ```
3. **批量替换 `import xxx` → `from .xxx import yyy`**（脚本辅助）
4. **删除 47 处 `sys.path.insert`**（用 ripgrep 一一定位）
5. **跑全量 `pytest -q` + `tools/build_all.py` + 部署 staging**
6. **观察 24h 无问题后删除转发 shim**

### 3.3 文件映射表（建议）

| 旧位置 | 新位置 | 备注 |
| --- | --- | --- |
| `storymap/script/parsers.py` | `core/parsers.py` | 解析 Markdown |
| `storymap/script/models.py` | `core/models.py` | |
| `storymap/script/person_registry.py` | `core/person_registry.py` | |
| `storymap/script/project_paths.py` | `core/project_paths.py` | |
| `storymap/script/artifacts.py` | `core/artifacts.py` | |
| `storymap/script/env_utils.py` | `core/env_utils.py` | |
| `storymap/script/profile_builder.py` | `profile/builder.py` | |
| `storymap/script/map_html_renderer.py` | `profile/renderer.py` | |
| `storymap/script/person_tooltip_js.py` | `profile/tooltip_js.py` | |
| `storymap/script/templates/` | `profile/templates/` | |
| `storymap/script/map_client.py` | `map/client.py` | |
| `storymap/script/geocode_service.py` | `map/geocode.py` | |
| `storymap/script/story_geocode_api.py` | `map/queue_api.py` 或保留旧名转发 | |
| `storymap/script/story_agent_*.py × 9` | `agent/{name}.py`（去掉 `story_agent_` 前缀） | |
| `storymap/script/story_agents.py` | `agent/registry.py` | |
| `storymap/script/api.py` | `api/__init__.py` 或 `api/root.py` | |
| `storymap/script/app_factory.py` | `api/factory.py` | |
| `storymap/script/story_*_api.py × 4` | `api/{name}.py` | |
| `storymap/script/proxy.py` | `api/proxy.py` | |
| `storymap/script/static.py` | `api/static.py` | |
| `storymap/script/runtime_support.py` | `runtime/support.py` | |
| `storymap/script/story_runtime_*.py` | `runtime/*.py` | |
| `storymap/script/story_cli.py` | `cli/main.py` | |
| `storymap/script/story_tooling.py` | `cli/tooling.py` | |
| `storymap/script/story_map.py` | **不动**（systemd 入口） | 内部 import 改成新路径即可 |

### 3.4 不能动的入口

- `storymap/script/story_map.py`（systemd）
- `cli/generate_pure_story_map.py`（GitHub Actions）
- `tools/build_all.py` / `build_stellar_homepage.py` / `validate_story_markdown.py` / `run_storymap_checks.py`（CI、部署脚本）
- `scripts/*.sh` 全部
- `data/*.json` / `data/*.md` 旧根路径兼容层仍需保留，尤其是 `people_master.json`、`people_summary_index.json`、`work_summary_index.json`、`markdown_smoke_report.json`、`hard_place_review_queue.{json,md}` 这些已被脚本、CI、人工排障路径长期引用的文件

## 四、Step 2 执行清单（已完成）

> 进度更新（2026-06-20）：
> - 已完成 `tools/build/` 第一批迁移：`build_all.py`、`build_people_master.py`、`build_people_summary_index.py`、`build_work_summary_index.py`、`build_stellar_homepage.py`
> - 已完成 `tools/build/` 收尾迁移：`homepage_search.py`、`build_people_knowledge_graph_pep.py`、`build_pep_people_time_index.py`、`enrich_pep_people_time_index.py`、`write_people_union_snapshot.py`、`build_neo4j_graph.py`
> - 已完成 `tools/reports/` 迁移：`run_storymap_checks.py`、`validate_story_markdown.py`、`report_low_coverage_places.py`、`check_pages_deploy.py`、`validate_people_info.py`、`run_two_phase_validation.py`
> - 已完成 `tools/debug/` 第一批迁移：`check_llm_health.py`、`test_random_basemaps.py`、`review_hard_places.py`、`repair_profile_artifacts.py`
> - 已完成 `tools/extras/` 第一批迁移：`batch_generate_pep_people.py`、`sync_storymap_examples_from_batch_runs.py`、`run_offline_agent_eval.py`
> - 根目录旧入口仍保留 shim，继续兼容 tests / scripts / 旧命令路径
> - `test_random_basemaps.py` 因现有测试会直接读取旧文件源码，暂保留旧路径真实实现副本；其余顶层入口均已 shim 化
> - Step 2 现已完成，后续进入 Step 3 `data/` 与 Step 4 `tests/` 的目录拆分

### 4.1 目标布局
```
tools/
├── README.md
├── build/
│   ├── build_all.py             ← 转发 shim 留 tools/build_all.py
│   ├── build_stellar_homepage.py
│   ├── build_work_summary_index.py
│   ├── build_people_master.py
│   ├── build_people_knowledge_graph_pep.py
│   ├── build_people_summary_index.py
│   ├── build_pep_people_spotlight.py
│   ├── build_pep_people_time_index.py
│   ├── enrich_pep_people_time_index.py
│   ├── write_people_union_snapshot.py
│   └── build_neo4j_graph.py
├── reports/
│   ├── report_low_coverage_places.py
│   ├── validate_people_info.py
│   ├── validate_story_markdown.py
│   ├── run_two_phase_validation.py
│   ├── run_storymap_checks.py
│   └── check_pages_deploy.py
├── debug/
│   ├── check_llm_health.py
│   ├── test_random_basemaps.py
│   ├── review_hard_places.py
│   └── repair_profile_artifacts.py
├── oneshot/
│   ├── inspect_lichun_3d_state.py
│   ├── inspect_lichun_firstload.py
│   ├── inspect_lichun_markers.py
│   ├── repro_lichun_amap_fallback.py
│   ├── repro_lichun_console.py
│   ├── repro_lichun_geovis_requests.py
│   ├── repro_lichun_localhost.py
│   ├── repro_lichun_map.py
│   └── fix_story_markdown_corpus.py
└── extras/
    ├── batch_generate_pep_people.py
    ├── sync_storymap_examples_from_batch_runs.py
    ├── homepage_search.py
    └── run_offline_agent_eval.py
```

### 4.2 兼容策略

- **6 个 CI/部署 hot-path 文件保留在 `tools/` 顶层做转发 shim**，shim 一行：
  ```python
  # tools/build_all.py
  from tools.build.build_all import *  # noqa: F401,F403
  from tools.build.build_all import main
  if __name__ == "__main__":
      main()
  ```
- 等 CI / 部署脚本统一切到新路径后，再删 shim。

## 五、Step 3 执行清单（已完成 ✅）

### 5.1 目标布局
```
data/
├── README.md                      # 新增，说明每个子目录的归属
├── corpus/                        # 长期入仓的索引/字典
│   ├── historical_places_index.jsonl
│   ├── place_aliases.json
│   ├── people_master.json
│   ├── people_summary_index.json
│   ├── work_summary_index.json
│   └── ...
├── reports/                       # .gitignore，构建过程产物
│   ├── markdown_smoke_report.json
│   ├── markdown_full_validation.json
│   ├── html_audit_summary.json
│   ├── low_coverage_story_report.json
│   ├── offline_agent_eval_report.json
│   └── performance_baseline.json
└── runtime/                       # 运行时持续读写
    ├── hard_place_review_queue.json
    └── hard_place_review_queue.md
```

### 5.2 影响面

> 进度更新（2026-06-21）：
> - 已创建 `data/corpus/`、`data/reports/`、`data/runtime/`
> - 已将长期入仓的索引/语料迁入 `data/corpus/`
> - `data/*.json` / `data/*.md` 根路径兼容软链已覆盖 corpus / reports / runtime 三类主路径，避免 CI / scripts / tests / 人工脚本立即回归
> - CI 的 Markdown 校验、低覆盖报告、离线评估报告与运行时 queue 默认路径已统一切到 `reports/` / `runtime/`
> - `build_people_master.py`、`review_hard_places.py`、`report_low_coverage_places.py`、`run_offline_agent_eval.py`、`story_geocode_api.py` 已统一通过 `project_paths` 辅助函数或新分层默认路径读写数据
> - `scripts/`、`tests/`、workflow 中面向仓库真实路径的旧根路径硬编码已清零；当前剩余旧根路径引用只保留在兼容测试、兼容 helper 与文档说明
> - `people_union_snapshot.json` 根级兼容软链已补齐；新增报告型产物默认只写 `data/reports/`
> - 重新扫描后，代码层已无新的 `data/*.json` / `data/*.md` 根路径默认入口，兼容层继续保留但不再阻塞 Step 3 关闭
> - 本轮针对 Step 3 收尾回归通过：`28 passed`

## 六、Step 4 执行清单（已完成 ✅）

> 进度更新（2026-06-21）：
> - `tests_support.py` + `tests/conftest.py` 已统一提供 `REPO_ROOT` / `SCRIPT_DIR`，原先写死 `Path(__file__).resolve().parents[1]` 的测试已完成收口
> - 已执行 `pytest tests --collect-only -q`，当前 **500 tests collected**，说明目录拆分未破坏 collection
> - `tests/` 根目录现已只剩 `conftest.py`，其余测试全部下沉到 `tests/unit/`、`tests/integration/`、`tests/data/`
> - `tests/data/` 已承接 `test_data_integrity.py`、`test_validate_story_markdown.py`、`test_offline_eval.py`
> - `tests/integration/` 已承接 `test_artifacts.py`、`test_review_hard_places.py`、`test_offline_profile_locations.py`、`test_static_service.py`、`test_generate_pure_story_map.py`、`test_fastapi_app.py`、`test_story_profile_api.py`、`test_generation_flow.py`、`test_task_service.py`、`test_build_all.py`
> - `tests/unit/` 已承接构建脚本、registry、agent、renderer、path helper、profile builder 等全部模块级测试，包括 `test_output_paths.py`、`test_person_registry.py`、`test_story_agent_router.py`、`test_build_pep_people_spotlight.py`、`test_build_pep_people_time_index.py`、`test_build_stellar_homepage.py`、`test_fix_story_markdown_corpus.py`、`test_profile_builder.py`、`test_story_agent_graph.py`、`test_profile_page_template.py`
> - 第十二批迁移已完成：`test_fix_story_markdown_corpus.py`、`test_profile_builder.py`、`test_story_agent_graph.py`、`test_profile_page_template.py` 下沉到 `tests/unit/`，`test_build_all.py` 下沉到 `tests/integration/`
> - 第十一批迁移后的定向回归通过：`73 passed`
> - 第十二批迁移后针对真实失败完成两处修复并回归通过：`155 passed`
> - `tools/reports/run_storymap_checks.py` 的默认 smoke pytest 目标与 Ruff 目标已切到 `tests/unit/`、`tests/integration/`、`tests/data/` 新目录
> - `.github/workflows/python-ci.yml` 已显式按 `collect -> unit -> integration -> data` 顺序执行，`docs/README.md` 也已补充本地分层跑法说明
> - 本地 smoke 入口 `scripts/test_storymap.sh --skip-ruff` 已按新路径实测通过：`252 passed`
> - 既有迁移批次回归保持通过：第十批 `45 passed`、第九批 `53 passed`、第八批 `23 passed`、第七批 `34 passed`、第六批 `41 passed`、第五批 `17 passed`、第四批 `18 passed`、第三批 `5 passed`、第二批 `20 passed`
> - 当前 Step 4 已从“前置清理 + 首批迁移”推进到“结构拆分 + CI 分层 + 文档入口”全部落地，剩余仅是后续按需微调

### 6.1 目标布局
```
tests/
├── conftest.py
├── unit/                          # 模块级测试：build / agent / renderer / registry / helpers
├── integration/                   # FastAPI / Agent / 构建管线 / 端到端工作流
│   ├── test_fastapi_app.py
│   ├── test_generation_flow.py
│   ├── test_build_all.py
│   └── ...
└── data/                          # 数据层级回归（无代码逻辑校验）
    ├── test_data_integrity.py
    ├── test_offline_eval.py
    └── test_validate_story_markdown.py
```

### 6.2 影响面
- `pyproject.toml` 已声明 `testpaths = ["tests"]` 与 `[tool.pytest.ini_options]`。
- `.github/workflows/python-ci.yml` 已按 `collect -> unit -> integration -> data` 分层执行。
- `docs/README.md` 已补充本地命令：`pytest tests/unit`、`pytest tests/integration`、`pytest tests/data`。

### 6.3 阻塞前提（实际试过的教训）

**当前进度与剩余阻塞**：
- `tests_support.py` + `tests/conftest.py` 已提供统一 `REPO_ROOT` / `SCRIPT_DIR` 入口，`parents[1]` 这一类深度依赖已完成收口。
- 早先阻塞目录下沉的裸 import / shim 兼容问题已基本排掉；本轮真实修复点主要集中在“命中真实实现模块而非 shim”与“清理 renderer / graph cache 后再注入 payload”。
- `test_output_paths.py` 已改为 reload `tools.build.build_all` / `tools.build.build_stellar_homepage` 真实实现，同时清理旧别名模块缓存，避免继续命中 shim。
- `test_profile_page_template.py` 已改为 monkeypatch `load_home_graph_payload(...)` 并显式清理相关 cache，避免对仓库现有图谱内容产生脆弱依赖。
- `tools/reports/run_storymap_checks.py` 的默认 smoke 清单与 `.github/workflows/python-ci.yml`、`docs/README.md` 已完成对齐，Step 4 现阶段已无结构性阻塞。

## 七、Step 5 执行清单（已完成 ✅）

- ✅ 新增 `docs/README.md`：项目文档总览
- ✅ 新增 `docs/architecture.md`：仓库目录 + 数据流总图
- ✅ 新增 `docs/reorg_plan.md`：本路线图
- ✅ `.gitignore` 扩充：data/ 报告类产物默认不入仓
- ✅ `orange.PNG` 已迁移到 `assets/orange.png`，并同步修复 `tools/build_stellar_homepage.py` 候选路径

## 八、执行守则

1. 每个 Step **独立分支 + 独立 PR**，不要混做。
2. 每步完成后跑 `pytest -q` + `tools/build_all.py` + 线上冒烟（参考上一轮的 `python3 - <<PY ... PY`）。
3. 任何破坏 CI 入口或 systemd 入口的改动，都必须在 PR 描述里显式列出"老路径还能用吗"。
4. 转发 shim 保留至少一个发布周期（24h+）再删。
5. `data/`、`scripts/` 的路径改动需要先在 staging 跑一次 deploy（可改 `--app-dir` 测试）。

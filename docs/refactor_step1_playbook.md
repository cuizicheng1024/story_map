# Step 1 执行手册 · `storymap/script/` 拆子包

> 配套文档：`docs/reorg_plan.md`（总路线图）、`docs/architecture.md`（架构总览）。
> 本文件聚焦"怎么改"，颗粒度做到可照搬执行。
> 最近一次更新：2026-06-20。

---

## 一、设计方针（不要绕开）

| 方针 | 为什么 |
| --- | --- |
| **保留原文件路径作为转发层**，不直接 `git mv` 删除 | 仓库里有 ~240 处外部 `from storymap.script.<mod> import ...`，转发层让外部调用零修改 |
| 一次只拆**一个子包**，独立提交 + 跑全量 tests | 上一会话试过一次混合拆 → 27 个测试同时挂，定位成本爆炸 |
| `__file__.parents[N]` 必须每搬一次复核 N | 这是核心子包阶段已经踩过的回归源（见 §三-1） |
| 转发层透传范围 = **非 dunder 全成员**（含 `_xxx` 半私有） | `parsers._parse_date_location_details` 这种半私有 API 被外部调用方依赖（见 §三-2） |
| 不动 systemd / CI / GH Actions 显式调用的"入口路径" | 见 `docs/reorg_plan.md` §3.4 入口清单 |

---

## 二、阶段总览（截至 2026-06-20）

| 阶段 | 子包 | 文件数 | 状态 |
| --- | --- | --- | --- |
| 1.1 | `core/` （models / parsers / project_paths / env_utils / person_registry） | 5 | ✅ 已落地 + 447 tests passed |
| 1.2 | `map/`  （map_client / geocode_service / story_geocode_api） | 3 | ⏳ 计划 |
| 1.3 | `profile/` （profile_builder / map_html_renderer / person_tooltip_js / templates） | 3 + 模板目录 | ⏳ 计划 |
| 1.4 | `runtime/` （runtime_support / story_runtime_*  / story_agent_* ） | 12 | ⏳ 计划 |
| 1.5 | `api/`  （api / app_factory / story_*_api / static / proxy） | 8 | ⏳ 计划 |
| 1.6 | `cli/`  （story_cli / story_entrypoints / story_tooling / story_map 入口段） | 4 | ⏳ 计划 |
| 1.7 | 清理：删 fallback 裸 import 分支、删转发层（**至少跑一个发布周期再做**） | — | ⏳ 最末步 |

---

## 三、阶段 1.1（已完成）回顾 · 必读经验

### 1. `__file__.parents[N]` 必须按"新深度"重算

子包文件比平铺文件**多一层目录**。已踩过的命中行：

| 旧路径 | 旧深度 | 新路径（移到 `core/`） | 新深度 |
| --- | --- | --- | --- |
| `script/project_paths.py` `parents[2]` | repo root | `script/core/project_paths.py` | 必须改 `parents[3]` |
| `script/parsers.py` `parents[2]` | repo root | `script/core/parsers.py` | 必须改 `parents[3]` |

> 现象：`test_place_aliases.py` 在 collection 阶段抛 `RuntimeError: 启动校验失败：缺少人物故事目录：.../storymap/storymap/examples/story`（路径多一层 `storymap/`）就是这个原因。

**操作手法**：每搬一个文件，先 `rg '__file__' <新文件>`，逐个手工对一遍 N 是否要 +1（如果搬到二级嵌套，比如 `storymap/script/api/v1/xxx.py`，则要 +2）。

### 2. 转发层成员过滤规则

最初写成 `not k.startswith("_")` → 把所有 `_xxx` 半私有函数全过滤掉了，外部 `parsers._parse_date_location_details` 调用立刻挂掉（27 个测试同时失败）。

**最终规则**：

```python
globals().update(
    {k: v for k, v in vars(_impl).items() if not (k.startswith("__") and k.endswith("__"))}
)
```

只过滤 dunder（`__name__ / __file__ / __doc__` 等），其余一律透传。

### 3. 子包内的相对 import 不用动

迁移后 `core/parsers.py` 里 `from .models import ...` 继续工作（仍是同级目录）。fallback 分支 `from models import ...` 同样不用动 —— 它本来就是 `sys.path` 兜底，移到子包后行为不变（相对 import 优先生效，ImportError 才进 fallback）。

### 4. tests 中 `importlib.import_module("storymap.script.person_registry")` 完全兼容

转发层让 `storymap.script.person_registry` 这个模块对象仍然存在且有所有原成员。无需改 tests。

---

## 四、转发层模板（一字不差可贴用）

每搬一个 `<mod>.py` 到 `<pkg>/<mod>.py`，原位置改写为：

```python
"""转发层：实际实现已迁移至 storymap.script.<pkg>.<mod>。"""

from __future__ import annotations

from storymap.script.<pkg>.<mod> import *  # noqa: F401,F403
from storymap.script.<pkg> import <mod> as _impl

# 透传非 dunder 全部成员（含以 _ 开头的半私有函数），
# 保证 `from storymap.script.<mod> import _x` 与 `<mod>._x` 全部兼容。
globals().update(
    {k: v for k, v in vars(_impl).items() if not (k.startswith("__") and k.endswith("__"))}
)

del _impl
```

替换 `<pkg>` 和 `<mod>` 即可。**不要**手工列符号清单，会漏。

---

## 五、各子包详细执行清单

### 5.1 阶段 1.2 · `map/`

**目标**

```
storymap/script/map/
├── __init__.py
├── map_client.py        ← script/map_client.py
├── geocode_service.py   ← script/geocode_service.py
└── geocode_api.py       ← script/story_geocode_api.py（重命名：去掉 story_ 前缀）
```

**已知的 `__file__` 命中行**（必改 N）

| 文件 | 旧 | 新（移到 `map/`） |
| --- | --- | --- |
| `map_client.py:392` `os.path.dirname(__file__) + "../.."` | repo root（`../..` 跳过 script/storymap） | 改成 `"..", "..", ".."`（跳 map/script/storymap） |
| `map_client.py:395` `load_project_env(from_file=__file__, ...)` | 由 `env_utils.load_project_env` 解析 | **不用动**：`load_project_env` 会自己 walk-up 找 `.env`，不依赖固定深度（动前 `rg 'def load_project_env' storymap/script/core/env_utils.py` 确认一遍） |
| `geocode_service.py:27` 同上 | 同上 | 同上 |
| `geocode_service.py:297` `os.path.dirname(os.path.abspath(__file__))` | 用于查同目录文件 | **不用动**（仍取自身目录） |
| `story_geocode_api.py:16` `parents[2]` | repo root | 改 `parents[3]` |

**外部调用面**（搬迁前先 grep 一遍确认全部走转发层）

```bash
rg "from storymap\.script\.(map_client|geocode_service|story_geocode_api)" --type py
rg "import (map_client|geocode_service|story_geocode_api)\b" --type py
```

**重命名注意**：`story_geocode_api.py → map/geocode_api.py` 改了名字，原 `script/story_geocode_api.py` **必须保留**为转发层指向 `map.geocode_api`，否则 `app_factory` 里 `from .story_geocode_api import router` 会断。

**验证**

```bash
python3 -m pytest tests/test_story_geocode_api.py tests/test_map_client.py -q
python3 -m pytest tests/ -q --ignore=tests/test_fastapi_app.py --ignore=tests/test_generate_pure_story_map.py
# 本地起后端再 curl 一次
nohup bash scripts/start_storymap.sh 8765 > /tmp/storymap_8765.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8765/health
```

---

### 5.2 阶段 1.3 · `profile/`

**目标**

```
storymap/script/profile/
├── __init__.py
├── builder.py          ← script/profile_builder.py
├── renderer.py         ← script/map_html_renderer.py
├── tooltip_js.py       ← script/person_tooltip_js.py
└── templates/          ← script/templates/ 整目录 mv
    ├── design_tokens.css
    └── profile_page.html
```

**已知的 `__file__` 命中行**

| 文件 | 旧 | 新（移到 `profile/`） |
| --- | --- | --- |
| `profile_builder.py:73-74` `parents[2] / "data" / ...` | repo root | 改 `parents[3]` |
| `map_html_renderer.py:40` `Path(__file__).with_name("templates")` | `script/templates` | **不用动**：`with_name` 是同目录改名，迁移后取 `profile/templates`，正好对应 |
| `map_html_renderer.py:60` 同上 | 同 40 | 同上 |
| `map_html_renderer.py:551` `parents[2]` | repo root | 改 `parents[3]` |

**模板路径一并迁**：`script/templates/` 整目录 `git mv` 到 `profile/templates/`，文件不动。

**外部调用面**

```bash
rg "from storymap\.script\.(profile_builder|map_html_renderer|person_tooltip_js)" --type py
rg "from storymap\.script\.templates" --type py   # 应该为空，模板靠路径加载
```

**模板路径硬编码扫描**（不能漏）

```bash
rg "script/templates" --type py
rg "storymap/script/templates" --type py
```

任何写死 `storymap/script/templates` 的位置都得改成 `storymap/script/profile/templates`，或者直接走 `renderer.py` 提供的 `_TEMPLATE_DIR` 入口。

**验证**

```bash
python3 -m pytest tests/test_profile_builder.py tests/test_profile_page_template.py tests/test_offline_profile_locations.py -q
# 跑一次最小 rebuild 确认模板还能加载
python3 tools/build_all.py --skip-master --skip-pep --concurrency 8 2>&1 | tail -10
```

---

### 5.3 阶段 1.4 · `runtime/`

**目标**

```
storymap/script/runtime/
├── __init__.py
├── support.py          ← script/runtime_support.py
├── helpers.py          ← script/story_runtime_helpers.py
├── api.py              ← script/story_runtime_api.py
└── agent/              ← script/story_agent_*.py 一次搬完
    ├── __init__.py
    ├── fallbacks.py    ← story_agent_fallbacks.py
    ├── graph.py        ← story_agent_graph.py
    ├── llm_parser.py   ← story_agent_llm_parser.py
    ├── memory.py       ← story_agent_memory.py
    ├── router.py       ← story_agent_router.py
    ├── runtime.py      ← story_agent_runtime.py
    ├── state.py        ← story_agent_state.py
    ├── telemetry.py    ← story_agent_telemetry.py
    └── tool_runner.py  ← story_agent_tool_runner.py
```

> 注意：已有 `storymap/script/agent/` 目录，是上一会话拆出来的 high-level（core/generation/knowledge/runtime）。本阶段的 `runtime/agent/` 是**低层 9 个 story_agent_\* 实现**，命名上和已存在的 `agent/` 会冲突。
>
> **解决方案二选一**：
> 1. 把现有 `storymap/script/agent/` 改名为 `storymap/script/agent_facade/`，本阶段新目录占用 `agent/`；
> 2. 本阶段改用 `runtime/legacy_agent/` 命名，不动现有 `agent/`。
>
> 建议方案 2，避免 ripple。下面清单按方案 2 写。

**已知的 `__file__` 命中行**

| 文件 | 旧 | 新（移到 `runtime/legacy_agent/`） |
| --- | --- | --- |
| `story_agent_memory.py:12` `os.path.join(__file__, "..", "..")` | repo root（从 script 跳到根） | 改成 `"..", "..", "..", ".."`（多两层：legacy_agent / runtime） |
| `story_agent_graph.py:173` `parents[2]` | repo root | 改 `parents[4]` |
| `story_agents.py:28` `os.path.join(__file__, "..", "..")` | repo root | **story_agents.py 不属于本阶段**（它是 runtime/agent 的 facade，归属待定，见下） |
| `story_agents.py:932` `os.path.dirname(__file__)` | script/ 自身 | 同上 |

**`story_agents.py` 归属**：它既是 9 个 `story_agent_*` 模块的入口，也是 LangGraph 编排器。建议：
- 保留在原位置 `storymap/script/story_agents.py`，作为 facade，里面 import 全部改成 `from .runtime.legacy_agent.xxx import ...`；
- 不动其 `__file__` 推断逻辑。

**`runtime_support.py / story_runtime_helpers.py / story_runtime_api.py`** 三个 runtime 文件目前没 `__file__` 直接命中（grep 已确认），搬迁时只需关心 import 转发。

**外部调用面**

```bash
rg "from storymap\.script\.(runtime_support|story_runtime|story_agent_)" --type py
rg "from storymap\.script import story_agent" --type py
```

**验证**

```bash
python3 -m pytest tests/test_story_agent_graph.py tests/test_story_agent_memory.py tests/test_story_agent_router.py tests/test_story_agent_runtime.py tests/test_story_agents_stability.py -q
python3 -m pytest tests/test_startup_env_config.py -q   # runtime_support 启动校验
```

---

### 5.4 阶段 1.5 · `api/`

**目标**

```
storymap/script/api/
├── __init__.py          ← 留空或仅做 re-export
├── root.py              ← script/api.py（重命名避免和包同名）
├── factory.py           ← script/app_factory.py
├── proxy.py             ← script/proxy.py
├── static.py            ← script/static.py
├── artifacts.py         ← script/story_artifact_api.py（去掉 story_ 前缀）
├── generation.py        ← script/story_generation_api.py
├── profile.py           ← script/story_profile_api.py
└── runtime.py           ← script/story_runtime_api.py（与 5.3 同一文件，需协调谁先落地）
```

**关键冲突**：原文件名是 `api.py`，子包名也想叫 `api/`。Python 不允许子包名和同级模块名相同。**必须重命名**为 `api/root.py` + 在原位置 `script/api.py` 写转发层：

```python
# script/api.py（转发层）
from storymap.script.api.root import *  # noqa: F401,F403
from storymap.script.api import root as _impl
globals().update({k: v for k, v in vars(_impl).items() if not (k.startswith("__") and k.endswith("__"))})
del _impl
```

**已知的 `__file__` 命中行**

| 文件 | 旧 | 新（移到 `api/`） |
| --- | --- | --- |
| `api.py:62` `parents[2]` | repo root | 改 `parents[3]`（重命名为 root.py 后） |

**入口保护清单**（不能改路径）

- `storymap/script/api.py` → 仍可被 `from storymap.script.api import app` 访问？**会冲突**。
  - 解决：`storymap/script/api/__init__.py` 里写 `from .root import *` + `from .root import app`，让 `storymap.script.api.app` 仍可用。
  - 同时**保留**老 `storymap/script/api.py`？**不行**，包和模块同名 Python 会优先包。**必须删掉**老 `storymap/script/api.py` 文件，转发完全靠 `__init__.py`。
- `app_factory.py` 被 `cli/start_storymap.sh` 链路里的 `uvicorn` 命令引用 → 确认 `scripts/start_storymap.sh` 用的是哪条路径。

**外部调用面**（数量较大，整改前先全量 grep）

```bash
rg "from storymap\.script\.(api|app_factory|proxy|static|story_artifact_api|story_generation_api|story_profile_api|story_runtime_api)" --type py
rg "from storymap\.script import (api|app_factory)" --type py
```

**验证**

```bash
python3 -m pytest tests/test_fastapi_app.py tests/test_story_profile_api.py tests/test_story_geocode_api.py tests/test_task_service.py tests/test_static_service.py -q
# 本地真实启动
nohup bash scripts/start_storymap.sh 8765 > /tmp/storymap_8765.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8765/health && curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/amap/config
```

---

### 5.5 阶段 1.6 · `cli/`

**目标**

```
storymap/script/cli/
├── __init__.py
├── main.py             ← script/story_cli.py
├── entrypoints.py      ← script/story_entrypoints.py
└── tooling.py          ← script/story_tooling.py
```

**注意：`story_map.py` 不搬**。它是 systemd / `scripts/start_storymap.sh` 的入口文件，路径已硬编码。内部 import 改成新路径即可。

`story_map.py:118` 的 `load_project_env(from_file=__file__, ...)` 不需要动（同 5.1 解释）。

**外部调用面**

```bash
rg "from storymap\.script\.(story_cli|story_entrypoints|story_tooling)" --type py
rg "python3 -m storymap\.script\.story_cli" .   # bash 脚本里有没有显式调用
rg "python3 storymap/script/story_cli" .
```

**验证**

```bash
python3 -m storymap.script.story_cli --help  # 转发层必须保 CLI 可用
python3 -m storymap.script.cli.main --help   # 新路径也要通
python3 -m pytest tests/test_story_tooling.py -q
```

---

## 六、每搬一个文件的 6 步标准动作

1. **Read 原文件**（必须先 Read 才能 Edit）。
2. **`cp` 到新位置**（不用 `git mv`，要先留旧文件做转发层，git 历史靠下一次提交 message 带 `rename:` 标记）：
   ```bash
   mkdir -p storymap/script/<pkg>
   cp storymap/script/<mod>.py storymap/script/<pkg>/<mod>.py
   ```
3. **复核 `__file__.parents[N]`**：
   ```bash
   rg "__file__|parents\[" storymap/script/<pkg>/<mod>.py
   ```
   逐行确认 N 是否要 +1 / +2。同时复核 `os.path.join(__file__, "..", "..")` 这种字面写法的 `..` 数量。
4. **改写原文件为转发层**（模板见 §四）。
5. **跑测试**：先跑该模块直接相关的 tests，再跑全量。
6. **手测**：起后端 `curl /health`，再起前端 8123 拉一两个人物页 200。

---

## 七、风险与回滚

### 7.1 高风险点

| 风险 | 出现位置 | 缓解方案 |
| --- | --- | --- |
| 包与同名模块冲突 | `api.py` ↔ `api/` | 必须删旧 `api.py`，转发挂在 `api/__init__.py` |
| `parents[N]` 漏改 | 任何含 `__file__` 的迁移文件 | 移动后立刻 `rg __file__` 复核 |
| 半私有 `_xxx` 被吞 | 转发层 | 用 §四模板（dunder-only 过滤） |
| 现有 `agent/` 命名冲突 | 阶段 1.4 | 用 `runtime/legacy_agent/` 命名 |
| 模板路径硬编码 | `script/templates` 字符串 | 阶段 1.3 之前先 `rg 'script/templates'` |
| CI 写死 module path | `.github/workflows/deploy-pages.yml` | 每阶段读一遍 workflow，必要时同步改 |

### 7.2 回滚步骤

每阶段独立提交（commit message 用 `refactor(step1.x): split <pkg>`）。回滚直接：

```bash
git revert <commit-sha>
# 或在分支上
git reset --hard HEAD~1
```

转发层让回滚成本极低——只是把新目录删掉、把原文件还原即可，外部调用方完全无感。

### 7.3 转发层何时删除

**至少跑一个发布周期 + 一次火山云部署 + 一次 staging 冒烟通过**后，再启动"清理阶段 1.7"：

1. 用 `rg "from storymap\.script\.<mod> "` 确认 0 个外部调用方还在用旧路径；
2. 用 `rg "import <mod>$"` 确认 0 个裸 import；
3. 删除原位置文件，提交 message `refactor(step1.7): remove forwarding shims for <pkg>`。

---

## 八、当前已落地证据（阶段 1.1 验收）

| 项 | 证据 |
| --- | --- |
| 新子包 | `storymap/script/core/{__init__,models,parsers,project_paths,env_utils,person_registry}.py` |
| 转发层 | `storymap/script/{models,parsers,project_paths,env_utils,person_registry}.py` 均改为 12 行转发模板 |
| `parents` 修正 | `core/project_paths.py:48` → `parents[3]`；`core/parsers.py:159` → `parents[3]` |
| tests | `pytest tests/ --ignore=test_fastapi_app --ignore=test_generate_pure_story_map` → **447 passed** |
| 本地双服务 | 8765 后端 `/health` ok、8123 静态站 `index.html / 苏轼.html` 均 200 |
| 顺手修复 | `tests/test_build_stellar_homepage.py` 2 条 `searchHit` 断言更新（与本次重构无关，是上一会话遗留） |

---

## 九、下次开工 checklist

按本手册执行下一阶段时，先按顺序回答：

- [ ] 当前阶段对应 §五 哪一节？
- [ ] 该节列出的所有 `__file__` 命中行，新深度算了吗？
- [ ] 涉及"包/模块同名冲突"的阶段（仅 1.5 api）：旧 `api.py` 删了吗？
- [ ] 该节"外部调用面"的 `rg` 命令跑过吗？输出是否有意外的"裸 import"？
- [ ] 转发层模板贴对了吗（含 dunder-only 过滤的注释）？
- [ ] 验证命令的 pytest 全绿吗？
- [ ] `curl /health` 200 吗？
- [ ] commit message 是否带 `refactor(step1.x):` 前缀？

照单走完，单阶段约 30~60 分钟可完成 + 验证。

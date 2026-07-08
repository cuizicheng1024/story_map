# StoryMap Agent 架构全景

项目中有 **两条独立的 Agent 管线**，分别服务于"人物传记生成"和"知识审计构建"。

---

## 一、管线总览

```
┌─────────────────────────────────────────────────────────────┐
│                       StoryMap 项目                          │
├──────────────────────────┬──────────────────────────────────┤
│  管线 A：人物传记生成主链路    │  管线 B：知识审计构建管线              │
│  路径: storymap/script/     │  路径: tools/build/agents/         │
│  runtime/legacy_agent/     │                                    │
├──────────────────────────┼──────────────────────────────────┤
│  触发: 用户输入人物姓名       │  触发: 构建脚本 / CLI 命令            │
│  目标: 生成人物 HTML + 地图   │  目标: 审计 + 修复知识性错误           │
│  6 个 Agent                │  5 个 Agent                        │
└──────────────────────────┴──────────────────────────────────┘
```

---

## 二、管线 A：人物传记生成主链路

> **代码位置**：[`storymap/script/runtime/legacy_agent/graph.py`](file:///Users/bytedance/Desktop/storymap/storymap/script/runtime/legacy_agent/graph.py)

### 2.1 流程概览

输入一个人物姓名 → LLM 检索资料 → 地名坐标映射 → 生成 Markdown → 审校修正 → **交付最终产物**。

### 2.2 六个 Agent

| # | Agent | 节点名 | 工具 | 功能 |
|---|-------|--------|------|------|
| 1 | **Supervisor** | `supervisor` | — | 决策中枢，根据共享状态决定下一步 |
| 2 | **SearchAgent** | `search_agent` | `search_person_info` | 检索人物资料（维基/百度百科 + LLM 整理） |
| 3 | **GeocodeAgent** | `geocode_agent` | `fetch_ancient_place_map` | 古今地名 → 现代坐标 |
| 4 | **EditorAgent** | `editor_agent` | `generate_markdown` | 基于资料生成/修订 Markdown |
| 5 | **CriticAgent** | `critic_agent` | `validate_markdown` | 审稿：时间线、地名精度、身份一致性 |
| 6 | **DeliverAgent** | `deliver_agent` | — | **交付 Agent**：输出最终 Markdown |

### 2.3 执行流程（LangGraph 状态图）

```
                         START
                           │
                           ▼
                    ┌──────────────┐
                    │  Supervisor  │
                    │ （决策中枢）   │
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────────────────────┐
           │               │                               │
           ▼               ▼                               │
   ┌──────────────┐ ┌──────────────┐              ┌──────────────┐
   │ SearchAgent  │ │ GeocodeAgent │   ...        │ DeliverAgent │
   │ （资料检索）   │ │ （地名坐标）   │              │  （交付）     │
   └──────┬───────┘ └──────┬───────┘              └──────┬───────┘
          │                │                            │
          └────────┬───────┘                            │
                   │                                    │
                   │  所有工作节点完成后返回 Supervisor     │
                   │  （条件路由，支持修订循环）            │
                   │                                    │
                   ▼                                    │
            ┌──────────────┐                            │
            │  Supervisor  │◄───────────────────────────┘
            │ （再次决策）   │
            └──────┬───────┘
                   │
                   │  validation.pass = true
                   │  或 达到最大修订轮次
                   │
                   ▼
                  END
```

### 2.4 Supervisor 决策逻辑

Supervisor 通过检查共享状态 `StoryAgentState` 的字段来决定下一步：

| 条件 | 下一步 |
|------|--------|
| `search_result` 为空 | → SearchAgent |
| `place_maps` 缺失 | → GeocodeAgent |
| `draft_markdown` 为空 | → EditorAgent |
| `needs_redraft` 为真 | → EditorAgent（重新写稿） |
| `validation` 为空 | → CriticAgent |
| `validation.pass` 为真 | → **DeliverAgent（交付）** |
| `needs_revision` 为真 | → 根据反馈类型路由回 GeocodeAgent/EditorAgent/SearchAgent |
| 达到最大修订轮次 | → **DeliverAgent（强制交付）** |

### 2.5 共享状态

所有 Agent 通过 `StoryAgentState` 共享数据：

```
StoryAgentState:
  ├── person              # 人物姓名
  ├── plan                # 执行计划
  ├── next_step           # Supervisor 决定的下一个 Agent
  ├── search_result       # SearchAgent 输出：结构化资料
  ├── place_maps          # GeocodeAgent 输出：地名→坐标映射列表
  ├── draft_markdown      # EditorAgent 输出：草稿
  ├── validation          # CriticAgent 输出：{pass, risk_level, issues}
  ├── critic_feedback     # 审校反馈列表
  ├── revision_count      # 修订轮次计数
  ├── final_markdown      # DeliverAgent 输出：最终 Markdown
  └── execution_trace     # 执行轨迹
```

### 2.6 各 Agent 详解

#### Supervisor（决策中枢）

- **无工具调用**，纯逻辑节点
- 根据 `StoryAgentState` 判断流程推进
- 内置异常降级策略：LLM 预算紧张、工具失败时自动调整路由
- 代码：[`router.py`](file:///Users/bytedance/Desktop/storymap/storymap/script/runtime/legacy_agent/router.py)

#### SearchAgent（资料检索）

- **工具**：`search_person_info`
- 从维基百科 API + 百度百科 HTML 抓取人物摘要
- 调用 LLM 将资料整理为结构化 JSON（dynasty, summary, identities, achievements, timeline, places, cautions）
- 支持 Memory 缓存（已检索人物可复用）
- 失败时回退到最小检索结果

#### GeocodeAgent（地名映射）

- **工具**：`fetch_ancient_place_map` + `queue_hard_place_review`
- 从 SearchAgent 结果中提取所有地名
- 逐个查询古今地名映射（古称 → 现代城市 → 高德 API / 离线字典 → 坐标）
- 无法解析的地名投递到人工审核队列
- 支持 Memory 缓存

#### EditorAgent（Markdown 生成）

- **工具**：`generate_markdown`
- 输入：检索资料 + 地名映射 + Critic 反馈 + 运行时反思
- 调用 LLM 生成结构化 Markdown（人物档案 → 人生足迹 → 地点坐标 → 生平时间线 → 历史影响）
- 自动嵌入 short_review 短评
- 失败时回退到确定性 Markdown 组装

#### CriticAgent（审校）

- **工具**：`validate_markdown`
- 检查：时间线顺序、地名精度、古现代城市过度映射、生卒年与享年自洽、引文归属、身份信息混写
- 内置高频风险规则（亚里士多德"吾爱吾师"、郑和"马三保"、霍去病古地名等）
- 输出 `{pass, risk_level, issues}` 决定是否需要修订

#### DeliverAgent（交付）

- **无工具调用**，纯终态节点
- 从 `final_markdown` 或 `draft_markdown` 提取最终产物
- 追加执行轨迹到 state
- 管线结束，返回结果给上层 `generation_service`

---

## 三、管线 B：知识审计构建管线

> **代码位置**：[`tools/build/agents/`](file:///Users/bytedance/Desktop/storymap/tools/build/agents/)

### 3.1 流程概览

全量扫描 538+ 人物 HTML → 检测 6 类知识错误 → 自动修复 → 二次审计 + 坐标补全 → 汇总报告。

### 3.2 五个 Agent

| # | Agent | 类名 | 核心职责 |
|---|-------|------|---------|
| 1 | **搜索 Agent** | `SearcherAgent` | 全量扫描 HTML，检测 6 类知识性错误 |
| 2 | **编辑 Agent** | `EditorAgent` | 自动修复搜索发现的错误 |
| 3 | **审阅 Agent** | `ReviewerAgent` | 修复后二次审计 + 前后对比 + 记忆写入 |
| 4 | **地理定位 Agent** | `GeoLocatorAgent` | 古地名 → 现代城市 → 坐标回填 |
| 5 | **拼接 Agent** | `AssemblerAgent` | 管线调度中心，汇总报告 + 仪表板生成 |

### 3.3 执行流程

```
  ┌──────────────────────────────────────┐
  │          AssemblerAgent              │
  │         （管线调度中心）                │
  └──────────────────────────────────────┘
                    │
     ┌──────────────┼──────────────┐
     │ 阶段 1        │ 阶段 2        │ 阶段 3（并行）
     ▼              ▼              ▼
┌─────────┐   ┌─────────┐   ┌──────────┬──────────┐
│Searcher │──▶│ Editor  │──▶│ Reviewer │GeoLocator│
│ Agent   │   │ Agent   │   │  Agent   │  Agent   │
└─────────┘   └─────────┘   └──────────┴──────────┘
     │              │              │          │
     │ 审计报告 JSON  │ 修复日志      │ 对比报告   │ 坐标回填
     ▼              ▼              ▼          ▼
  ┌──────────────────────────────────────────┐
  │              汇总报告 + 仪表板              │
  │   audit_dashboard.html                   │
  │   project_memory.md ← 记忆写入            │
  └──────────────────────────────────────────┘
```

### 3.4 依赖关系

- **阶段 1 → 阶段 2**：硬依赖（编辑必须基于搜索结果）
- **阶段 3 内部**：审阅 + 地理定位 **并行执行**（互不依赖，操作不同文件子集）
- 所有 Agent 继承自 `BaseAgent`，统一获得：日志、重试、异常边界、原子 I/O、耗时统计

---

## 四、两条管线的关系

```
管线 A（人物传记生成）              管线 B（知识审计构建）
═══════════════════════            ═══════════════════════
输入：人物姓名                       输入：HTML 产物目录
输出：.md + .html + 地图             输出：审计报告 + 修复 + 仪表板

         ┌─────────────────────────────────┐
         │   管线 A 生成的 HTML 文件          │
         │   (artifacts/story_map/*.html)   │
         └──────────────┬──────────────────┘
                        │
                        ▼
         ┌─────────────────────────────────┐
         │   管线 B 对这些 HTML 进行审计      │
         │   - 检测 LLM 思考泄露             │
         │   - 修复章节编号                   │
         │   - 补全缺失坐标                   │
         │   - 清理占位符                     │
         └─────────────────────────────────┘
```

两条管线是**上下游关系**：
- 管线 A（运行时）生成人物 HTML
- 管线 B（构建时）审计并修复 HTML 中的知识性错误

---

## 五、Agent 基类架构

所有 11 个 Agent 中有 5 个（管线 B）继承自统一基类：

```
BaseAgent (tools/build/agents/base.py)
  ├── SearcherAgent
  ├── EditorAgent
  ├── ReviewerAgent
  ├── GeoLocatorAgent
  └── AssemblerAgent
```

基类提供：
- 结构化日志 + 执行耗时统计
- 自动异常捕获与 `AgentReport` 状态上报
- 可配置的重试机制（`max_retries` + `retry_delay`）
- 安全文件 I/O（`_safe_read` / `_safe_write` / `_safe_read_json` / `_safe_write_json`）
- 输入校验钩子（`_pre_run`）
- 生命周期管理（`run()` → `_pre_run()` → `_execute()` → `_post_run()`）

管线 A 的 Agent 是 LangGraph 节点，共享 `StoryAgentState` 而非基类实例。

---

## 六、关键文件索引

| 文件 | 说明 |
|------|------|
| [graph.py](file:///Users/bytedance/Desktop/storymap/storymap/script/runtime/legacy_agent/graph.py) | 管线 A 全部 Agent 节点 + LangGraph 编排 |
| [router.py](file:///Users/bytedance/Desktop/storymap/storymap/script/runtime/legacy_agent/router.py) | Supervisor 决策逻辑 |
| [state.py](file:///Users/bytedance/Desktop/storymap/storymap/script/runtime/legacy_agent/state.py) | StoryAgentState 定义 |
| [base.py](file:///Users/bytedance/Desktop/storymap/tools/build/agents/base.py) | 管线 B Agent 基类 |
| [assembler.py](file:///Users/bytedance/Desktop/storymap/tools/build/agents/assembler.py) | 管线 B 调度中心 |
| [searcher.py](file:///Users/bytedance/Desktop/storymap/tools/build/agents/searcher.py) | 搜索 Agent |
| [editor.py](file:///Users/bytedance/Desktop/storymap/tools/build/agents/editor.py) | 编辑 Agent |
| [reviewer.py](file:///Users/bytedance/Desktop/storymap/tools/build/agents/reviewer.py) | 审阅 Agent |
| [geolocator.py](file:///Users/bytedance/Desktop/storymap/tools/build/agents/geolocator.py) | 地理定位 Agent |

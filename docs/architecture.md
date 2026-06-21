# 架构总图

> 这是一份"读完就能上手"的工程视角说明，**不替代** [`storymap/docs/maintenance_map.md`](../storymap/docs/maintenance_map.md) 里的细节维护图。

## 一、当前仓库目录全貌

```
mapsotryforstudents/
├── README.md / install.md                # 项目门面与安装
├── docs/                                 # 工程视角文档（导览/架构/重组计划）
├── storymap/
│   ├── __init__.py
│   ├── docs/                             # 产品视角文档 + Agent Prompt
│   ├── examples/story/*.md               # 人物 Markdown 语料库（核心数据）
│   └── script/                           # 核心源码：真实实现已拆到子包，旧根文件保留 shim 兼容
│       ├── agent/                        # 故事生成 / 编排 / 离线评估
│       ├── api/                          # FastAPI 应用骨架 / 路由 / 运行时装配
│       ├── cli/                          # CLI 入口与交互逻辑
│       ├── core/                         # parser / model / project path / artifact 等基础模块
│       ├── map/                          # 地理编码 / 地图客户端
│       ├── profile/                      # 人物页数据构建 / 渲染 / 模板
│       ├── runtime/                      # Task / API / legacy agent runtime
│       ├── story_map.py                  # 兼容入口 shim
│       └── ...                           # 其余 shim 与 facade
├── tools/                                # 构建/校验/调试脚本（CLI）
├── tests/                                # 单元 + 集成 + 数据回归测试
├── data/                                 # 索引 / 语料 / 报告 / 队列
├── scripts/                              # 部署 / 启动 / 回滚 shell
├── cli/generate_pure_story_map.py        # CI 直接调用的 CLI（不要改名）
├── artifacts/story_map/*.html            # 全量构建产物（507 张静态页）
├── vendor/                               # 前端三方资源（React/Tailwind/Babel）
└── assets/
    └── orange.png                       # 站点 favicon + 首页吉祥物
```

## 二、最重要的几条数据流

### Flow A：Markdown 语料 -> 静态人物页（核心生产链路）

```
storymap/examples/story/*.md
  ↓  parsers.parse_story_document
  ↓  profile_builder.build_profile_data
  ↓  map_html_renderer.render_profile_html  (注入 __DATA__ / __BUILD_META__)
  ↓
artifacts/story_map/{人物}.html
```

入口脚本：`cli/generate_pure_story_map.py`、`tools/build_all.py`

### Flow B：人物页 -> 首页星座

```
artifacts/story_map/*.html  (扫 __EXPORT_DATA__)
  + storymap/examples/story/*.md  (补朝代/出生地)
  ↓  tools/build_stellar_homepage.py
  ↓
artifacts/story_map/index.html
artifacts/story_map/stellar_home_data.json
artifacts/story_map/stellar_home_data_detail.json
```

### Flow C：新人物生成（Agent 链路）

```
用户输入"人名" or "人名 + 资料"
  ↓  story_agent_graph 调度 (Generation -> Critic -> Reviser -> Validator)
  ↓  story_agent_tool_runner + story_agent_memory
  ↓  story_profile_api / story_geocode_api  (落 hard_place_review_queue)
  ↓
storymap/examples/story/{人物}.md
  ↓ Flow A
artifacts/story_map/{人物}.html
```

### Flow D：运行时 FastAPI 服务

```
scripts/start_storymap.sh
  → storymap/script/story_map.py --serve
  → app_factory.create_app()
  → api.py / static.py / proxy.py
```

绑定端口 `8765`，systemd 单元 `storymap.service`，公网入口 `http://124.174.16.20`。

## 三、已完成重构与剩余技术债

| 反模式 | 现状 | 影响 | 计划修复 |
| --- | --- | --- | --- |
| `sys.path.insert` 注入 | 主链路已清理 | 包结构已可稳定演进 | 后续仅需删除历史说明与兼容尾巴 |
| `storymap/script/*.py` 互相裸 `import xxx` | 真实实现已拆包，仍有 shim / ImportError fallback | 兼容层仍增加理解成本 | 发布稳定后分批删除 shim 与 fallback |
| `tools/` 平铺 | 真实实现已拆到 `build/reports/debug/oneshot` | 顶层仍保留少量兼容入口 | 稳定后精简顶层 shim |
| `data/` 长期文件 + 报告产物混放 | 真实读写已切到 `corpus/reports/runtime` | 根目录兼容软链仍需维护 | 观察一个发布周期后再评估是否继续收口 |

完整路线图 → [`./reorg_plan.md`](./reorg_plan.md)

## 四、关键约束（维护前必须知道）

1. **远端 systemd 入口** = `scripts/start_storymap.sh` → `storymap/script/story_map.py`
2. **CI 入口** = `cli/generate_pure_story_map.py`、`tools/build_all.py`、`tools/build_stellar_homepage.py`、`tools/validate_story_markdown.py`
3. **静态资源源文件** = `assets/orange.png`，构建后会复制到 `artifacts/story_map/orange.png`，页面仍引用 `./orange.png`
4. **首页吉祥物图片候选路径**（`tools/build_stellar_homepage.py`）现以 `assets/orange.png` 为主，兼容回退保留 `tools/orange.png`、`./orange.png`、`./orange.PNG`
5. **人物 Markdown 语料路径** = `storymap/examples/story/`，被 GitHub Actions 的 path filter 监控（参见 `.github/workflows/deploy-pages.yml`）
6. **`data/` 兼容层** = 真实读写路径已切到 `data/corpus/`、`data/reports/`、`data/runtime/`；根目录 `data/*.json` / `data/*.md` 暂保留兼容软链（例如 `data/people_master.json`、`data/markdown_smoke_report.json`、`data/hard_place_review_queue.{json,md}`），新增脚本应优先使用新路径辅助函数

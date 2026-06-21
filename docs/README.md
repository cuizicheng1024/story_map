# 文档导览（StoryMap）

> 本文件是仓库内**文档入口**。所有项目文档按"使用者视角"分四类：

## 一、给"用户/演示"看的
| 文档 | 用途 |
| --- | --- |
| [`../README.md`](../README.md) | 项目介绍、在线演示、目录索引 |
| [`../install.md`](../install.md) | 安装、本地启动、部署、维护命令 |

## 二、给"内容贡献者"看的（人物 Markdown 创作）
| 文档 | 用途 |
| --- | --- |
| [`../storymap/docs/person_markdown_spec.md`](../storymap/docs/person_markdown_spec.md) | 人物 Markdown 字段规范，所有 `storymap/examples/story/*.md` 都按这套写 |
| [`../storymap/docs/extract_names_prompt.md`](../storymap/docs/extract_names_prompt.md) | 从教材里抽取人物名的 LLM Prompt |
| [`../storymap/docs/fact_check_prompt.md`](../storymap/docs/fact_check_prompt.md) | 事实核查 Prompt |
| [`../storymap/docs/story_system_prompt.md`](../storymap/docs/story_system_prompt.md) | Story Agent System Prompt（生成 Markdown 时使用） |
| [`../storymap/docs/maintenance_map.md`](../storymap/docs/maintenance_map.md) | 维护图：每个模块、每个数据文件、每个脚本的归属 |

## 三、给"工程贡献者"看的
| 文档 | 用途 |
| --- | --- |
| [`../tools/README.md`](../tools/README.md) | `tools/` 下脚本的分层与各文件用途 |
| [`../cli/README.md`](../cli/README.md) | CLI 入口（`generate_pure_story_map.py` 等） |
| [`./architecture.md`](./architecture.md) | 仓库目录、关键模块、数据流总图 |
| [`./reorg_plan.md`](./reorg_plan.md) | 目录重组路线图（Step 1~5）与已完成执行清单 |

## 四、给"运维"看的
| 文档 | 用途 |
| --- | --- |
| [`../install.md`](../install.md) | 火山云 ECS 部署细节、systemd 配置 |
| [`../scripts/`](../scripts/) | 部署/启动/回滚/线上自检脚本（每个文件顶部都有注释） |

---

## 数据目录速查

```
data/
├── corpus（长期入仓）           — historical_places_index.jsonl / place_aliases.json / people_*
├── reports（按 .gitignore 排除） — *_report.json / markdown_*_validation.json / html_audit_*
└── runtime queue                — hard_place_review_queue.{json,md}（仅本地，自动落盘）
```

> `data/` 下哪些应当入仓、哪些是生成产物，详见 [data/README.md](../data/README.md)。
> 当前真实写入位置优先使用 `data/corpus/`、`data/reports/`、`data/runtime/`；旧 `data/*.json` / `data/*.md` 根路径仍保留兼容软链。

## 构建/部署入口速查

| 我想 ... | 直接跑 |
| --- | --- |
| 本地启动开发服务 | `scripts/start_storymap.sh` |
| 跑一次本地自检 | `scripts/test_storymap.sh` |
| 全量构建（人物页 + 首页 + 索引） | `python3 tools/build_all.py` |
| 校验 Markdown 语料 | `python3 tools/validate_story_markdown.py --report-json data/reports/markdown_smoke_report.json` |
| 部署到火山云 ECS | `scripts/deploy_storymap_release.sh --identity <key.pem> --verify-public` |
| 回滚上一版本 | `scripts/rollback_storymap_release.sh` |

## 测试分层速查

| 我想 ... | 直接跑 |
| --- | --- |
| 先确认 collection 没坏 | `python3 -m pytest tests --collect-only -q` |
| 只跑单元测试 | `python3 -m pytest tests/unit -q` |
| 只跑集成测试 | `python3 -m pytest tests/integration -q` |
| 只跑数据回归 | `python3 -m pytest tests/data -q` |
| 跑本地 smoke 检查 | `scripts/test_storymap.sh` |

> CI 当前也按 `unit -> integration -> data` 顺序执行；`scripts/test_storymap.sh` 保留为本地 smoke 入口，默认只跑一组代表性测试。

# `tools/oneshot/`

> 一次性的复现 / 诊断 / 数据修补脚本。**不会被任何 CI / 部署链路或其它脚本引用**。

这些脚本是过去线上 issue 排查时留下的，长期价值有限，但暂时保留作为复现参考。

## 当前清单

| 脚本 | 起源场景 |
| --- | --- |
| `inspect_lichun_3d_state.py` | 排查李纯页 3D 视角初始状态异常 |
| `inspect_lichun_firstload.py` | 排查李纯页首屏空白 |
| `inspect_lichun_markers.py` | 排查李纯页地图标记缺失 |
| `repro_lichun_amap_fallback.py` | 复现高德 SDK 加载失败 |
| `repro_lichun_console.py` | 抓李纯页控制台报错 |
| `repro_lichun_geovis_requests.py` | 复现 GeoVis 网络请求 |
| `repro_lichun_localhost.py` | 本地 localhost 复现 |
| `repro_lichun_map.py` | 地图组件复现 |
| `fix_story_markdown_corpus.py` | 一次性修补 storymap/examples/story/*.md 中的脏数据（被 `tests/test_fix_story_markdown_corpus.py` 通过显式路径 import） |

## 维护规则

- **新增**：新的复现脚本写到这里，文件名带 `<场景>_<日期>` 帮助未来回溯
- **删除**：超过 3 个月未被引用 + 对应 issue 已关闭，可以直接删
- **不要 import**：本目录脚本应当自包含；不要在其它 tools/ 脚本里 import 这里的代码
- **保持顶层 `tools/__init__.py` 不存在**：不让 `tools` 成为 Python 包，避免误用相对 import

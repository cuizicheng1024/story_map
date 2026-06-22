# 本轮重构收口总结

## 范围

本轮工作同时覆盖两条主线：

1. Agent 架构 8 项优化与执行链路收口
2. 5 个巨型文件拆分与职责瘦身

目标是：

- 在不破坏外部接口的前提下，持续把巨型流程文件拆成更清晰的 orchestration + 模块实现
- 为历史人物生成、任务执行、地图地理编码、人物资料装配和前端大文件提供更稳定的演进边界
- 在每一轮拆分后都做定向回归，避免“结构更漂亮但行为漂移”

## 已完成项

### 1. generation_service 主流程分层

已完成：

- 缓存命中、复用 markdown、首次生成、降级返回拆成阶段函数
- progress / finalize 闭包外提为执行上下文
- generation_api 已透传 checkpoint_store
- checkpoint finalize 闭环完成

结果：

- 主流程更接近阶段编排器
- checkpoint / resume 能力边界更清晰

### 2. task_service 巨型流程拆分

已完成：

- 任务结果汇总与终态解析拆到 `task_result_compiler`
- 状态流转与恢复逻辑拆到 `task_state_flow`
- submit 执行壳拆到 `task_execution_flow`
- `_run_task()` 主编排拆到 `task_run_pipeline`
- 后台归档刷新拆到 `task_archive_refresher`
- 目标解析拆到 `task_target_resolver`

结果：

- `task_service.py` 从巨型流程文件收敛为 orchestration 层
- queue slot、future 生命周期、异常归一化、任务终态提交职责边界更稳定

### 3. profile/builder 地点与坐标装配拆分

已完成：

- 地点宽松匹配、坐标聚合、主地点选择、fallback 地点构建拆到 `profile_location_utils`
- 兼容保留 `_collapse_sparse_single_site_locations()`、`_sort_profile_locations()` 等包装入口

结果：

- `builder.py` 更偏资料总装配入口
- 地点解析逻辑可单独维护和复用

### 4. map_client 地理编码与 markdown 坐标段拆分

已完成：

- geocode candidate 规则拆到 `geocode_candidates`
- geocode cache / negative cache / metrics / persistence 拆到 `geocode_runtime_state`
- HTTP geocode 访问与 provider bridge 拆到 `geocode_http`、`geocode_provider_bridge`
- env / timeout / key / feature flag 配置拆到 `geocode_config`
- markdown 坐标段解析拆到 `coords_markdown`、`coords_markdown_sections`

结果：

- `map_client.py` 明显变薄，主要保留运行时状态装配、坐标转换和兼容壳
- `append_coords_section()`、`compute_total_distance_km()` 所在链路已有独立模块承接

### 5. local_history_qa 拆分

已完成：

- 请求解析拆到 `local_history_qa_request`
- 回答构建与检索式兜底拆到 `local_history_qa_answering`
- `LocalHistoryQAAgent` 收口为薄协调器

结果：

- 本地人物问答的“请求解析”和“回答生成”已分层
- 后续扩展问答路由时不必再修改主入口类

### 6. star-office 前端大文件拆分

已完成：

- 文案与静态映射拆到 `ui-copy-data.js`
- 语言绑定拆到 `ui-language-bindings.js`
- 资产指导文案拆到 `ui-asset-guidance.js`
- 资产选择态拆到 `ui-asset-selection.js`
- 资产列表与缩略图拆到 `ui-asset-drawer-list.js`
- 上传与刷新流程拆到 `ui-asset-upload-flow.js`

结果：

- `.tmp_star_office_ui/frontend/index.html` 已不再承担大块静态数据和完整 UI 细节实现
- `tools/build/sync_star_office_ui.py` 同步链路保持可用

### 7. 历史循环导入修复

已完成：

- 修复 `generation_api <-> agent/generation` 循环导入
- `storymap/script/agent/__init__.py` 改为按符号懒加载

结果：

- `tests/integration/test_offline_profile_locations.py` 不再在 collection 阶段报 ImportError

## 本轮新增模块

本轮新增的代表性模块包括：

- `storymap/script/runtime/task_state_flow.py`
- `storymap/script/runtime/task_execution_flow.py`
- `storymap/script/runtime/task_run_pipeline.py`
- `storymap/script/runtime/local_history_qa_request.py`
- `storymap/script/runtime/local_history_qa_answering.py`
- `storymap/script/profile/profile_location_utils.py`
- `storymap/script/map/coords_markdown_sections.py`
- `storymap/script/map/geocode_config.py`
- `storymap/script/map/geocode_provider_bridge.py`
- `.tmp_star_office_ui/frontend/ui-copy-data.js`
- `.tmp_star_office_ui/frontend/ui-language-bindings.js`
- `.tmp_star_office_ui/frontend/ui-asset-guidance.js`
- `.tmp_star_office_ui/frontend/ui-asset-selection.js`
- `.tmp_star_office_ui/frontend/ui-asset-drawer-list.js`
- `.tmp_star_office_ui/frontend/ui-asset-upload-flow.js`

## 已验证回归

已通过的关键回归包括：

- `tests/unit/test_map_client.py`
- `tests/unit/test_local_history_qa_agent.py`
- `tests/unit/test_profile_builder.py`
- `tests/integration/test_task_service.py`
- `tests/integration/test_generation_flow.py`
- `tests/integration/test_offline_profile_locations.py`

其中一轮汇总回归结果为：

- `115 passed`

修复循环导入后，补充组合回归结果为：

- `72 passed`

## 兼容性说明

本轮重构有意识保留了多处兼容入口，避免外部依赖或测试直接失效：

- `map_client.py` 里保留了若干私有函数名，便于测试 monkeypatch
- `profile/builder.py` 中保留了部分兼容包装函数
- `task_service.py` 对外接口保持稳定
- `LocalHistoryQAAgent.answer()` 的对外返回结构未变
- `star-office` 仍通过原有同步脚本生成最终产物页面

## 当前残余事项

从代码主线角度看，本轮核心目标已完成。剩余事项主要属于交付级收尾，而不是主功能阻塞：

1. 如有需要，可继续对 `star-office` 里剩余零散 helper 做最后一轮归类
2. 如有需要，可将本总结继续扩展为面对团队的发布说明或变更公告

## 结论

当前可以把这轮工作视为：

- Agent 架构优化：已完成
- 5 个巨型文件拆分：已完成
- 关键历史阻塞问题修复：已完成
- 核心回归验证：已完成

后续若继续推进，更建议进入“增量优化 / 文档化 / 发布说明”阶段，而不是再以“大规模拆分”为主。

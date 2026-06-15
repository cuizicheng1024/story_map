# Debug Session: task-blocking-bug [OPEN]

## Goal
- 重新分析是否存在阻塞性 bug。
- 对“新任务生成”执行一次全流程测试，确认卡点在冷启动、任务线程、状态持久化，还是外部依赖。

## Symptoms
- `tests/test_fastapi_app.py::test_generate_then_poll_task_flow[asyncio]` 存在可复现失败，现象是任务在轮询窗口内保持 `running`。
- 同一用例在预热后可通过，疑似存在冷启动或竞争问题。
- 用户要求进一步确认是否存在阻塞性 bug，并执行一个新任务生成的完整流程测试。

## Hypotheses
1. 首次任务执行时会同步扫描大量人物档案与 JSON 数据，导致首个任务明显变慢。
2. 成功路径后半段的汇总或持久化逻辑存在阻塞，状态迟迟未从 `running` 切换到终态。
3. `/task` 读取路径与后台线程更新存在竞争，导致轮询读到旧状态。
4. 真实全流程任务会被 LLM、导出、首页刷新或地理解析等外部依赖卡住。

## Evidence Plan
- 先读取调试技能说明并启动 debug server。
- 仅增加最小化插桩，记录任务从提交到完成的关键时间点。
- 复现测试失败场景，再执行一次真实新任务全流程。
- 用日志证据判定根因，再决定是否需要最小修复。

## Evidence Collected
- 预热前测试链路日志显示：`story_person_names()` 首次扫描约 `610ms`，`known_authentic_person_names()` 首次扫描约 `1341ms`，总计约 `2s`，而单人物生成与汇总仅约 `10ms` 量级。
- 真实任务 `杨振宁` 通过 `/generate -> /task` 跑通到业务终态，但被真实性过滤拦截，最终状态为 `failed`，并非线程卡死。
- 真实任务 `董卓` 同样被真实性过滤拦截，且对应人物 Markdown 明确存在于 `storymap/examples/story/董卓.md`。
- 读取 `董卓.md` 后确认正文含有“`文学虚构人物`”字样，但该字样出现在“貂蝉（文学虚构人物）”这一知识点示例中，不应反向判定“董卓”本人是虚构人物。

## Hypothesis Status
| ID | Hypothesis | Status | Evidence |
|----|------------|--------|----------|
| A | 首次任务执行会同步扫描大量人物档案与 JSON 数据，导致首个任务明显变慢 | Confirmed | 调试日志显示数据集扫描约 `2s`，占据首个任务主要耗时 |
| B | 成功路径后半段的汇总或持久化逻辑存在阻塞 | Rejected | 测试日志中单人物生成和 summary 构建都在毫秒级完成 |
| C | `/task` 读取路径与后台线程更新存在竞争 | Rejected | 日志可见状态正常从 `running` 切到终态，未见状态丢失 |
| D | 真实全流程任务会被业务规则或外部依赖拦截 | Confirmed | `杨振宁` 与 `董卓` 均在真实性过滤处失败，其中 `董卓` 为明显误判 |

## Interim Conclusion
- 当前更像是两类问题叠加：
- 一类是冷启动性能问题，会让首个任务看起来“长时间 running”。
- 另一类是真实性过滤误判，会把合法人物直接拦截成失败，这比单纯慢更阻塞真实使用。

## Fixes Applied
- 将真实性判定收窄到文档前部的“声明型行”，避免正文里提及虚构配角时误伤真实人物。
- 为人物 Markdown 扫描结果增加缓存，并让“可发布人物 / 拒绝人物”共享同一次目录扫描。
- 在任务链路中关闭同步首页刷新，避免 `/generate` 一直等待 `build_pep_people_spotlight.py` 和 `build_stellar_homepage.py` 两个子进程完成。

## Post-fix Verification
- `pytest` 定向验证通过：`tests/test_project_paths.py`、`tests/test_task_service.py`、`tests/test_fastapi_app.py` 相关用例共 9 条通过。
- 真实 HTTP 全流程验证：
  - `POST /generate` 提交 `董卓`
  - 第 1 次轮询为 `running`
  - 第 2 次轮询即为 `completed`
  - 调试日志显示：数据集扫描约 `0.31s`，人物生成约 `13ms`，任务总耗时约 `0.34s`
- 当前仍存在非阻塞问题：`董卓` 结果为 `completed`，但内部人物结果为 `degraded`，原因是 Markdown 数据质量提示“年份表缺少现称列”。

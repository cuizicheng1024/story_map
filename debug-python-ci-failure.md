# [OPEN] Python CI Failure

## Session
- session_id: `python-ci-failure`
- started_at: `2026-06-08`
- scope: `GitHub Actions / Python CI`

## Symptom
- GitHub Pages 部署成功
- `Python CI` 持续失败
- 本地与模拟 CI 环境多数情况下可通过，说明问题更可能出在 GitHub Actions 实际运行环境或日志可见性不足

## Hypotheses
1. CI 失败发生在 `ruff` 阶段，而不是 `pytest` 阶段
2. CI 失败来自 GitHub Linux runner 的环境差异，本地 macOS 无法直接复现
3. `python-ci.yml` 的自检步骤日志颗粒度太粗，真实错误没有被直接暴露
4. `tools/run_storymap_checks.py` 仍存在环境选择或路径问题，只在 Actions 安装方式下触发
5. Node 24 强制切换警告不是根因，只是伴随噪音

## Evidence Plan
- 将 CI 的 `Run StoryMap Checks` 拆成更细粒度步骤
- 在 workflow 中输出 Python、pip、ruff、pytest 的来源与版本
- 分别独立执行 `ruff` 与 `pytest`
- 若仍失败，再根据具体失败阶段做最小修复

## Status
- waiting_for: `pytest failure detail from GitHub summary`

## Evidence
- Commit `7fe5df1` added split CI steps and environment probes
- GitHub run `#12` showed `Run Ruff Check` passed and `Run Pytest Suite` failed
- Fresh local Python 3.11 venv reproduced the exact pytest command with `27 passed`
- GitHub run `#14` narrowed the failure to `Pytest test_fastapi_app`
- A clean local repro without `artifacts/story_map/` failed with `GET / -> 404`
- After updating the test to create its own temporary homepage artifact, the same clean repro passed

## Hypothesis Review
- H1 rejected: failure is not in `ruff`; it is in `pytest`
- H2 rejected: the real trigger is a clean-checkout test assumption, not Ubuntu-specific Python behavior
- H3 confirmed: earlier workflow logging was too coarse to identify the failing stage
- H4 rejected: resolver logic is not the root cause
- H5 confirmed: Node 24 warning is unrelated to the Python test failure

## Root Cause
- `tests/test_fastapi_app.py::test_root_serves_homepage_html` assumed `artifacts/story_map/index.html` already existed
- That file is not tracked by git, so GitHub Actions clean checkout returned `404` for `/`
- Local developer machines masked the issue because the artifact often already existed from prior builds

## Fix
- Make `test_root_serves_homepage_html` create a temporary `index.html` and monkeypatch the static roots
- Add a regression test to ensure `李斯` profile card prefers the death-scene quote when available

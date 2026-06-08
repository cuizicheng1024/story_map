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

## Hypothesis Review
- H1 rejected: failure is not in `ruff`; it is in `pytest`
- H2 still plausible: issue appears specific to GitHub Ubuntu runner
- H3 confirmed: earlier workflow logging was too coarse to identify the failing stage
- H4 still plausible: resolver logic may not be root cause now that direct `pytest` still fails on CI
- H5 confirmed: Node 24 warning is unrelated to the Python test failure

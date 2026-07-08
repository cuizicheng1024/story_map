"""Trace 苏轼 Agent 管线调用全过程，输出为 Markdown 格式。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storymap.script.agent.llm_client import StoryAgentLLM
from storymap.script.runtime.legacy_agent.runners import generate_markdown_with_agents


def fmt_json(obj, max_len=500):
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(s) > max_len:
        return s[:max_len] + "\n... (truncated)"
    return s


def main():
    person = "苏轼"
    print(f"# 管线 A Agent 调用 Trace — {person}\n")
    print(f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    t0 = time.monotonic()

    # Step 1: 创建 LLM 客户端
    print("## 1. 初始化\n")
    llm = StoryAgentLLM()
    print(f"- Model: `{llm.model}`")
    print(f"- Base URL: `{llm.baseUrl}`")
    print(f"- Timeout: {llm.timeout}s")
    print()

    # Step 2: 调用管线
    print("## 2. 管线执行\n")
    print("```")
    sys.stdout.flush()

    t_start = time.monotonic()
    result = generate_markdown_with_agents(
        llm=llm,
        person=person,
        max_revisions=2,
    )
    elapsed = time.monotonic() - t_start
    print("```\n")
    print(f"**总耗时**: {elapsed:.1f}s\n")

    state = result.get("state", {})
    if not isinstance(state, dict):
        state = {}

    # ── 3. 执行路径 ──
    print("## 3. 执行路径 (execution_trace)\n")
    trace = state.get("execution_trace", [])
    if trace:
        for i, step in enumerate(trace):
            print(f"{i+1}. {step}")
    else:
        print("(无)")
    print()

    # ── 4. 工具调用详情 ──
    print("## 4. 工具调用详情 (tool_traces)\n")
    tool_traces = state.get("tool_traces", [])
    if tool_traces:
        for i, t in enumerate(tool_traces):
            tool_name = t.get("tool_name", "?")
            agent_step = t.get("agent_step", "")
            duration = t.get("duration_ms", "?")
            success = t.get("success", True)
            timed_out = t.get("timed_out", False)
            status = "❌ 超时" if timed_out else ("✅" if success else "❌ 失败")
            print(f"### 4.{i+1} `{tool_name}` ({agent_step}) — {status} ({duration}ms)\n")
            inp = t.get("input_summary", "")
            if inp:
                print("**输入**:")
                print("```json")
                print(inp[:2000])
                print("```")
                print()
            outp = t.get("output_summary", "")
            if outp:
                print("**输出**:")
                print("```json")
                print(outp[:2000])
                print("```")
            err = t.get("error", "")
            if err:
                print(f"**错误**: {err}")
            print()
    else:
        print("(无)")
    print()

    # ── 5. 检索结果 ──
    print("## 5. 检索结果 (search_result)\n")
    sr = state.get("search_result", {})
    if sr:
        print("```json")
        print(fmt_json(sr, max_len=3000))
        print("```")
    else:
        print("(无)")
    print()

    # ── 6. 地名映射 ──
    print("## 6. 地名映射 (place_maps)\n")
    pm = state.get("place_maps", [])
    if pm:
        print(f"共 {len(pm)} 个地点:\n")
        print("| # | 古地名 | 今地名 | 经度 | 纬度 |")
        print("|---|--------|--------|------|------|")
        for j, p in enumerate(pm):
            coord = p.get("coordinate", [None, None]) if isinstance(p, dict) else [None, None]
            lng = coord[0] if coord and len(coord) > 0 else "?"
            lat = coord[1] if coord and len(coord) > 1 else "?"
            name = p.get("name", "?") if isinstance(p, dict) else "?"
            modern = p.get("modern_name", "?") if isinstance(p, dict) else "?"
            print(f"| {j+1} | {name} | {modern} | {lng} | {lat} |")
    else:
        print("(无)")
    print()

    # ── 7. Markdown 草稿 ──
    print("## 7. Markdown 草稿 (draft_markdown)\n")
    draft = state.get("draft_markdown", "")
    if draft:
        print("```markdown")
        print(draft[:3000])
        if len(draft) > 3000:
            print(f"\n... (共 {len(draft)} 字符，已截断)")
        print("```")
    else:
        print("(无)")
    print()

    # ── 8. 校验结果 ──
    print("## 8. 校验结果 (validation / critic_feedback)\n")
    validation = state.get("validation", {})
    feedback = state.get("critic_feedback", [])
    if validation:
        print("**validation**:")
        print("```json")
        print(fmt_json(validation, max_len=2000))
        print("```")
        print()
    if feedback:
        print(f"**critic_feedback** ({len(feedback)} 条):")
        for j, f in enumerate(feedback):
            print(f"- [{f.get('field', '?')}] {f.get('claim', '?')} → {f.get('correction', '?')} (confidence: {f.get('confidence', '?')})")
    if not validation and not feedback:
        print("(无)")
    print()

    # ── 9. 最终 Markdown ──
    print("## 9. 最终交付 (final_markdown)\n")
    final_md = result.get("markdown", "") or state.get("final_markdown", "")
    if final_md:
        print(f"**长度**: {len(final_md)} 字符\n")
        print("```markdown")
        print(final_md[:5000])
        if len(final_md) > 5000:
            print(f"\n... (共 {len(final_md)} 字符，已截断)")
        print("```")
    else:
        print("(无)")
    print()

    # ── 10. 统计 ──
    print("## 10. 统计信息\n")
    print(f"| 指标 | 值 |")
    print(f"|------|----|")
    print(f"| 修订轮次 | {state.get('revision_count', '?')} / {state.get('max_revisions', '?')} |")
    print(f"| LLM 调用 | {state.get('llm_calls_used', '?')} / {state.get('llm_calls_limit', '?')} |")
    print(f"| 需要修订 | {state.get('needs_revision', '?')} |")
    print(f"| 降级原因 | {state.get('degraded_reasons', [])} |")
    print(f"| 记忆命中 | {state.get('memory_hits', {})} |")
    print(f"| 记忆未命中 | {state.get('memory_misses', {})} |")
    print(f"| LangGraph 可用 | {result.get('langgraph_available', '?')} |")
    print(f"| 总耗时 | {elapsed:.1f}s |")
    print()

    # ── 11. HTML ──
    html = result.get("html", "") or state.get("html", "")
    render_error = result.get("render_error", "") or state.get("render_error", "")
    print("## 11. HTML 渲染\n")
    if html:
        print(f"**HTML 长度**: {len(html)} 字符")
        print(f"**包含 AMap**: {'是' if 'AMap' in html else '否'}")
        print(f"**包含足迹点位**: {'是' if 'pts' in html else '否'}")
    else:
        print("(未生成 HTML — Markdown 中可能缺少 `### 足迹` 段落)")
    if render_error:
        print(f"**渲染错误**: {render_error}")
    print()

    total = time.monotonic() - t0
    print(f"---\n*全流程耗时: {total:.1f}s*")


if __name__ == "__main__":
    main()

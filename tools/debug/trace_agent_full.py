"""Trace Agent 管线调用全过程，输出完整原始数据。"""
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


def main():
    person = "杜甫"
    print(f"{'='*80}")
    print(f"  管线 A 全链路 Trace — {person}")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    sys.stdout.flush()

    llm = StoryAgentLLM()
    print(f"[INIT] model={llm.model}  base_url={llm.baseUrl}  timeout={llm.timeout}s\n")
    sys.stdout.flush()

    t0 = time.monotonic()
    result = generate_markdown_with_agents(llm=llm, person=person, max_revisions=5, max_llm_calls=12)
    elapsed = time.monotonic() - t0

    state = result.get("state", {})
    if not isinstance(state, dict):
        state = {}

    print(f"\n{'─'*80}")
    print(f"[DONE] 总耗时: {elapsed:.1f}s")
    print(f"{'─'*80}\n")

    # ── execution_trace ──
    print("=" * 80)
    print("  execution_trace (执行路径)")
    print("=" * 80)
    for i, step in enumerate(state.get("execution_trace", [])):
        print(f"  {i+1}. {step}")

    # ── tool_traces ──
    print(f"\n{'='*80}")
    print(f"  tool_traces (工具调用, 共 {len(state.get('tool_traces', []))} 次)")
    print(f"{'='*80}")
    for i, t in enumerate(state.get("tool_traces", []) or []):
        tool = t.get("tool_name", "?")
        agent = t.get("agent_step", "")
        dur = t.get("duration_ms", "?")
        ok = t.get("success", True)
        to = t.get("timed_out", False)
        status = "TIMEOUT" if to else ("OK" if ok else "FAIL")
        print(f"\n  [{i+1}] {tool}  ({agent})  {dur}ms  {status}")
        inp = t.get("input_summary", "")
        if inp:
            print(f"       input:  {inp[:300]}")
        outp = t.get("output_summary", "")
        if outp:
            print(f"       output: {outp[:500]}")
        err = t.get("error", "")
        if err:
            print(f"       ERROR:  {err}")

    # ── search_result ──
    print(f"\n{'='*80}")
    print("  search_result (检索结果)")
    print("=" * 80)
    sr = state.get("search_result", {})
    if sr:
        print(json.dumps(sr, ensure_ascii=False, indent=2, default=str))

    # ── place_maps ──
    print(f"\n{'='*80}")
    print(f"  place_maps (地名映射, 共 {len(state.get('place_maps', []))} 条)")
    print("=" * 80)
    for pm in state.get("place_maps", []) or []:
        if isinstance(pm, dict):
            print(f"  {pm.get('query','?'):20s} → 今{pm.get('modern_name','?'):20s}  [{pm.get('lat','?')}, {pm.get('lng','?')}]  src={pm.get('source','?')}")

    # ── draft_markdown ──
    print(f"\n{'='*80}")
    print(f"  draft_markdown (草稿, {len(state.get('draft_markdown',''))} chars)")
    print("=" * 80)
    print(state.get("draft_markdown", "(无)"))

    # ── validation / critic_feedback ──
    print(f"\n{'='*80}")
    print("  validation + critic_feedback")
    print("=" * 80)
    val = state.get("validation", {})
    if val:
        print(f"  pass={val.get('pass')}  risk={val.get('risk_level')}  issues={len(val.get('issues',[]))}")
        for iss in val.get("issues", []) or []:
            print(f"    [{iss.get('field','?')}] {iss.get('claim','?')} (confidence: {iss.get('confidence','?')})")
    fb = state.get("critic_feedback", [])
    if fb:
        for f in fb:
            print(f"    critic_feedback: {json.dumps(f, ensure_ascii=False, default=str)[:300]}")

    # ── final_markdown ──
    print(f"\n{'='*80}")
    print(f"  final_markdown ({len(result.get('markdown','') or state.get('final_markdown',''))} chars)")
    print("=" * 80)
    print(result.get("markdown", "") or state.get("final_markdown", ""))

    # ── HTML ──
    html = result.get("html", "") or state.get("html", "")
    print(f"\n{'='*80}")
    print(f"  HTML ({len(html)} chars)")
    print("=" * 80)
    if html:
        print(html[:2000])
        if len(html) > 2000:
            print(f"\n... (共 {len(html)} 字符，已截断)")
    else:
        print("(无)")

    # ── stats ──
    print(f"\n{'='*80}")
    print("  统计信息")
    print("=" * 80)
    print(f"  修订轮次:     {state.get('revision_count','?')} / {state.get('max_revisions','?')}")
    print(f"  LLM 调用:     {state.get('llm_calls_used','?')} / {state.get('llm_calls_limit','?')}")
    print(f"  需要修订:     {state.get('needs_revision','?')}")
    print(f"  降级原因:     {state.get('degraded_reasons',[])}")
    print(f"  记忆命中:     {state.get('memory_hits',{})}")
    print(f"  记忆未命中:   {state.get('memory_misses',{})}")
    print(f"  LangGraph:    {result.get('langgraph_available','?')}")
    print(f"  总耗时:       {elapsed:.1f}s")
    print(f"  render_error: {result.get('render_error','')}")


if __name__ == "__main__":
    main()

"""
============================================================================
  agent.generation_tools — LLM 可调用的工具集 (Tool Manifest)
============================================================================
  本模块负责把 "与人物 markdown / 坐标 / 数据质量" 相关的操作打包成 @tool，
  供 LLM 在生成过程中显式调用。当前暴露 3 个工具：

      geocode_markdown           —— 给 markdown 注入坐标表
      parse_story_markdown       —— 抽出 places / events / points 三元组
      validate_story_markdown    —— 校验时间线、地点、坐标完整性

----------------------------------------------------------------------------
  一、Tool / Memory Plan
----------------------------------------------------------------------------
  所有工具函数都是纯函数 (无副作用、不写盘)，仅接受 markdown 字符串返回字典或字符串
  调用方负责把工具结果落盘到 markdown 文件 / checkpoint / result 字典

  工具注册依赖注入 (Callable)
      append_coords_section   : 把坐标表拼到 markdown 末尾
      parse_places / parse_events
                                : 把 markdown 拆成结构化记录
      build_points            : 把 places + events 合并成地图点位
      collect_quality_metrics : 计数 (timeline_rows / places / coords / ...)
      validate_data_quality   : 返回 issues 列表
      print_quality_report    : 把 metrics + issues 打印到 stdout (供人读)

----------------------------------------------------------------------------
  二、PDCA 循环
----------------------------------------------------------------------------
  Plan  : 新增工具时把 description 写得 "动词 + 输入 + 输出" 三段式，便于 LLM 准确触发
  Do    : create_generation_tools() 接收一组 Callable，返回 dict[name → callable]
  Check : 上层应在 result["_validation"]["issues"] 读取 validate_story_markdown 输出
  Act   : 若新增工具引入了新的副作用，需要在 generation_service 的 cache_dependency_paths
          列表中登记依赖文件路径

----------------------------------------------------------------------------
  三、5M1E
----------------------------------------------------------------------------
  Man(人)        : 维护者修改 tool description 时必须同步给 docs/ 下的 prompt 模板
  Machine(机)   : 无
  Material(料)  : markdown 字符串大小敏感，建议人物 markdown 不超过 ~50KB
  Method(法)    : 全部走 @tool 装饰器统一签名 (md: str) -> Dict / str / List
  Measurement(测): 上层 UI 不直接展示工具调用，需要在 telemetry 里加埋点
  Environment(环): 工具注册顺序敏感，LLM 在多工具下倾向先调用排在首位的工具
============================================================================
"""

from __future__ import annotations

from typing import Callable, Dict, List

from ..cli.tooling import tool


def create_generation_tools(
    *,
    append_coords_section: Callable[[str], str],
    parse_places: Callable[[str], List[Dict[str, str]]],
    parse_events: Callable[[str], List[Dict[str, str]]],
    build_points: Callable[..., List[Dict[str, object]]],
    collect_quality_metrics: Callable[[str], Dict[str, int]],
    validate_data_quality: Callable[[str], List[str]],
    print_quality_report: Callable[[str], None],
) -> Dict[str, Callable[..., object]]:
    @tool(name="geocode_markdown", description="为人物 Markdown 补齐地点坐标与地理编码信息")
    def geocode_markdown(md: str) -> str:
        return append_coords_section(md)

    @tool(name="parse_story_markdown", description="把人物 Markdown 解析为地点、事件与地图点位")
    def parse_story_markdown(md: str) -> Dict[str, object]:
        places = parse_places(md)
        events = parse_events(md)
        points = build_points(places, events)
        return {
            "places": places,
            "events": events,
            "points": points,
        }

    @tool(name="validate_story_markdown", description="校验人物 Markdown 的时间线、地点与坐标质量")
    def validate_story_markdown(md: str) -> Dict[str, object]:
        metrics = collect_quality_metrics(md)
        issues = validate_data_quality(md)
        print_quality_report(md)
        return {
            "metrics": metrics,
            "issues": issues,
        }

    return {
        "geocode_markdown": geocode_markdown,
        "parse_story_markdown": parse_story_markdown,
        "validate_story_markdown": validate_story_markdown,
    }

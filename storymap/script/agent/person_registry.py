"""人物注册:生成新人物之后,自动把基础信息登记到三层 corpus index 里。

# 为什么
- 之前需要手工跑 ``tools/build/homepage/main.py`` 才会把新人物放进
  人类群星闪耀时首页节点网络;agent_v2 跑完只写 .md / .html,缺这一步,索引
  数据会和新人物脱节。
- 集中在这个模块之后,任何入口 (v1 ``generate_for_person``、批量脚本、CI) 只
  要在新增人物完成后调一次 ``register_new_person(person)``, 后续步骤就由它负责。

# 三层索引
- ``data/corpus/people_master.json``           基础字段 (person / has_story / story_md /
                                              birth_year / dynasty / birthplace / ...)
- ``data/corpus/people_summary_index.json``    人物卡数据 (status / short_review /
                                              identities / achievements / works / quotes)
- ``data/corpus/people_birth_coords_wgs84.json``  {(person): [lat, lng]} — 出生坐标,
                                              决定首页节点是否能落图

# 写策略 (idempotent)
- 已存在 -> 不重写。注册函数总是返回 ``{"skipped": [...], "added": [...]}``,
  调用方可以拿来打日志。
- 三层之间没硬约束;``people_summary_index`` 没填的允许只填人名,后续可以
  由后台任务慢慢补 status / quote。

# 出生坐标来源
1. 优先用 ``people_birth_coords_wgs84.json`` 已有的
2. 其次从 markdown frontmatter / 「籍贯」「祖籍」句中抽取,调 ``geocode_city``
3. 都没有就跳过,不在 corpus 里写 (避免错坐标写进首页)

# Homepage 重建
``rebuild_homepage=True`` 时调用 ``tools/build/homepage/main.py`` 重生
``artifacts/story_map/index.html`` + ``stellar_home_data*.json``。这是一个相对
重的步骤,默认关闭。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_LOGGER = logging.getLogger("storymap.script.agent.person_registry")

# 默认路径,可以由参数覆盖 (便于测试)
_REPO_ROOT = Path(os.getenv("STORYMAP_REPO_ROOT") or Path(__file__).resolve().parents[3])

_PEOPLE_MASTER_PATH = _REPO_ROOT / "data" / "corpus" / "people_master.json"
_PEOPLE_SUMMARY_PATH = _REPO_ROOT / "data" / "corpus" / "people_summary_index.json"
_BIRTH_COORDS_PATH = _REPO_ROOT / "data" / "corpus" / "people_birth_coords_wgs84.json"


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _LOGGER.warning("读 %s 失败: %s", path, e)
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _extract_meta_from_markdown(md: str, person: str) -> Dict[str, Any]:
    """从 markdown 里尽量抓出 birth_year / death_year / dynasty / birthplace / status。"""
    text = md or ""
    info: Dict[str, Any] = {
        "person": person,
        "has_story": bool(text.strip()),
        "story_md": "",
        "birth_year": None,
        "death_year": None,
        "dynasty": "",
        "birthplace": "",
        "birthplace_raw": "",
        "birthplace_modern": "",
        "foreign_name": "",
        "country": "",
        "country_zh": "",
    }
    # 出生年份 — 处理"- **出生**：约公元前331年"、"- **出生**：公元680年"等变体
    # 注意 markdown 中常有 **加粗** 标记包裹关键词
    _b = r"(?:生于|\*{0,2}出生\*{0,2}[于在]?|生卒[：:])"
    year_patterns = [
        # 明确的公元前表示（如"约公元前331年"、"约前257年"）
        (re.compile(_b + r"\s*[:：]?\s*(?:约\s*)?公?元?\s*前\s*(\d{1,4})\s*年"), True),
        # 公元后表示或没有标记的正数年份（如"公元680年"、"689年"）
        (re.compile(_b + r"\s*[:：]?\s*(?:约\s*)?(?:公?元\s*)?(\d{1,4})\s*年"), False),
    ]
    for pat, is_bce in year_patterns:
        m = re.search(pat, text[:1200])
        if m:
            try:
                year_val = int(m.group(1))
                # 跳过明显是世纪编号的片段（如"7世纪初"→7、"6世纪"→6）
                # 方式：检查匹配区域前是否有"世纪初"/"世纪中叶"/"世纪"字样
                ctx_start = max(0, m.start() - 8)
                ctx_before = text[ctx_start:m.end()]
                is_century_fragment = bool(re.search(r'\d\s*世纪', ctx_before))
                if is_century_fragment:
                    continue
                # 过滤不合理的小数字（如纯粹的在位年数、世纪编号等）
                # 但BCE的小数字是合理的（如公元前45年）
                if not is_bce and year_val < 50:
                    continue
                info["birth_year"] = -year_val if is_bce else year_val
                break
            except Exception:
                pass
    # 出生地 (按字面找 籍贯 / 生于X / 祖籍X)
    patterns = [
        r"籍贯[:：]\s*([\u4e00-\u9fa5A-Za-z·\s,，()（）]{2,40})",
        r"出生地[:：]?\s*([\u4e00-\u9fa5A-Za-z·\s,，()（）]{2,40})",
        r"生于([\u4e00-\u9fa5A-Za-z·\s,，()（）]{2,30})",
        r"祖籍[:：]?\s*([\u4e00-\u9fa5A-Za-z·\s,，()（）]{2,30})",
    ]
    for pat in patterns:
        m = re.search(pat, text[:2000])
        if m:
            raw = m.group(1).strip().rstrip("。,，;；")
            info["birthplace_raw"] = raw
            info["birthplace"] = raw
            break
    # 去世年份 — 支持 "- **去世**：前257年" 等格式
    _d = r"(?:\*{0,2}(?:去世|卒于|逝世)\*{0,2})"
    death_patterns = [
        (re.compile(_d + r"\s*[:：]?\s*(?:约\s*)?公?元?\s*前\s*(\d{1,4})\s*年"), True),
        (re.compile(_d + r"\s*[:：]?\s*(?:约\s*)?(?:公?元\s*)?(\d{1,4})\s*年"), False),
    ]
    for pat, is_bce in death_patterns:
        m = re.search(pat, text[:2000])
        if m:
            try:
                year_val = int(m.group(1))
                info["death_year"] = -year_val if is_bce else year_val
                break
            except Exception:
                pass
    # dynasty — 多种格式：朝代 / 时代 / - **时代**：xxx
    for pat in [
        r"[-*]\s*\*{0,2}(?:朝代|时代|dynasty|Dynasty)\*{0,2}\s*[:：]\s*([\u4e00-\u9fa5A-Za-z·\-\s]{2,40})",
        r"(?:朝代|时代|dynasty|Dynasty)\s*[:：]\s*([\u4e00-\u9fa5A-Za-z·\-\s]{2,40})",
    ]:
        m = re.search(pat, text[:1500])
        if m:
            info["dynasty"] = m.group(1).strip().rstrip("。,，;；")
            break
    return info


# ---------------------------------------------------------------------------
# 三个 corpus 的 idempotent 更新
# ---------------------------------------------------------------------------

def update_people_master(person: str, md_text: str) -> Tuple[bool, str]:
    payload = _read_json(_PEOPLE_MASTER_PATH)
    if not isinstance(payload, dict):
        payload = {"generated_at": "", "count": 0, "people": []}
    people: List[Dict[str, Any]] = list(payload.get("people") or [])
    if any(p.get("person") == person for p in people if isinstance(p, dict)):
        return False, "already-present"
    entry = _extract_meta_from_markdown(md_text, person)
    entry["story_md"] = f"storymap/examples/story/{person}.md"
    people.append(entry)
    payload["people"] = people
    payload["count"] = len(people)
    payload["generated_at"] = _now_iso()
    _write_json(_PEOPLE_MASTER_PATH, payload)
    return True, "added"


def update_people_summary(person: str, md_text: str) -> Tuple[bool, str]:
    payload = _read_json(_PEOPLE_SUMMARY_PATH)
    if not isinstance(payload, dict):
        payload = {}
    items: Dict[str, Any] = dict(payload.get("items") or {})
    if person in items:
        return False, "already-present"
    items[person] = {
        "spotlight": "",
        "quotes": [],
        "review": "",
        "reviews": [],
        "intro": "",
        "title": "",
        "honor": "",
        "short_review": "",
        "status": "",
        "identities": "",
        "achievements": "",
        "works": [],
    }
    payload["items"] = items
    _write_json(_PEOPLE_SUMMARY_PATH, payload)
    return True, "added"


def update_birth_coords(person: str, md_text: str) -> Tuple[bool, str]:
    payload = _read_json(_BIRTH_COORDS_PATH)
    if not isinstance(payload, dict):
        payload = {}
    if person in payload:
        return False, "already-present"
    # 优先用 md 里抽出来的 birthplace
    meta = _extract_meta_from_markdown(md_text, person)
    place = meta.get("birthplace_modern") or meta.get("birthplace_raw") or meta.get("birthplace")
    if not place:
        return False, "no-birthplace"
    try:
        from ..map.map_client import geocode_city
    except Exception:
        try:
            from storymap.script.map.map_client import geocode_city
        except Exception as exc:
            _LOGGER.warning("geocode_city 不可用: %s", exc)
            return False, "geocode-unavailable"
    try:
        coord = geocode_city(place)
    except Exception as e:
        _LOGGER.warning("geocode_city(%s) failed: %s", place, e)
        return False, "geocode-failed"
    if not coord or not isinstance(coord, (tuple, list)) or len(coord) != 2:
        return False, "no-coord"
    lat, lng = float(coord[0]), float(coord[1])
    if not (17.5 <= lat <= 55.5 and 72.0 <= lng <= 136.5):
        return False, "coord-out-of-china"
    payload[person] = [round(lat, 6), round(lng, 6)]
    _write_json(_BIRTH_COORDS_PATH, payload)
    return True, "added"


# ---------------------------------------------------------------------------
# 顶层入口
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# LLM-fill summary (P1-5)
# ---------------------------------------------------------------------------

_SUMMARY_FILL_INSTRUCTIONS = """你是「人类群星闪耀时」项目的人物摘要助手。基于提供的 markdown 人物档案,
抽取并以 JSON 形式返回这些字段:
- status: 一句话人物综述,50-120 字,中文 (e.g. "三国时期曹魏权臣,深谋远虑的军事家。")
- short_review: 更短的 20-60 字版本,适合人物卡副标题
- identities: 一句话人物身份描述,涵盖朝代/职业 (e.g. "三国曹魏权臣、战略家")
- achievements: 主要成就一句话,用「·」分隔 (e.g. "抵御北伐 · 发动高平陵之变 · 奠定晋朝基础")
- works: 3-5 部主要作品或事迹标签数组 (e.g. ["高平陵之变", "抵御诸葛亮北伐", "灭公孙渊"])
- intro: 100-200 字人物介绍

严格只输出一个 JSON 对象,不要任何其它文字,不要 Markdown 包外。"""


def _build_summary_messages(person: str, md_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": _SUMMARY_FILL_INSTRUCTIONS},
        {
            "role": "user",
            "content": (
                f"人物: {person}\n\n# Markdown 摘录 (前 4000 字)\n\n"
                f"{md_text[:4000]}"
            ),
        },
    ]


def _parse_llm_summary_json(raw: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出里抓 JSON,容错处理 markdown 围栏、解释性前缀等。"""
    import json as _json

    if not raw:
        return None
    text = str(raw).strip()
    # 去掉 ```json ... ``` 围栏
    if text.startswith("```"):
        # 去掉首行 ```json / ```
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()
    # 抓首个 { ... } 块
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return _json.loads(text[start:end + 1])
    except Exception as e:
        _LOGGER.warning("解析 LLM 摘要 JSON 失败: %s", e)
        return None


def llm_fill_summary_for(
    person: str,
    md_text: str,
    *,
    timeout_seconds: int = 60,
) -> Tuple[bool, str]:
    """调用 LLM 给人物摘要字段填值,写回 ``people_summary_index``。

    返回:
      (ok, detail)
      - ok=True, detail="filled" / "fields=<f1>,<f2>" 成功补完
      - ok=False, detail="llm-unavailable" / "no-md" / "no-json" / "..." 失败原因
    """
    if not md_text or not md_text.strip():
        return False, "no-md"
    try:
        from .registry import StoryAgentLLM
    except Exception as exc:
        _LOGGER.warning("StoryAgentLLM 不可用: %s", exc)
        return False, "llm-unavailable"
    try:
        llm = StoryAgentLLM()
    except Exception as exc:
        _LOGGER.warning("初始化 LLM 客户端失败: %s", exc)
        return False, "llm-init-failed"
    messages = _build_summary_messages(person, md_text)
    try:
        raw = llm.think(messages, temperature=0.2, timeout=timeout_seconds)
    except Exception as exc:
        _LOGGER.warning("LLM.think 失败: %s", exc)
        return False, "llm-call-failed"
    parsed = _parse_llm_summary_json(raw)
    if not parsed:
        return False, "no-json"
    return _write_summary_fields(person, parsed)


def _write_summary_fields(person: str, fields: Dict[str, Any]) -> Tuple[bool, str]:
    payload = _read_json(_PEOPLE_SUMMARY_PATH)
    if not isinstance(payload, dict):
        payload = {}
    items: Dict[str, Any] = dict(payload.get("items") or {})
    existing = dict(items.get(person) or {})
    acceptable = {
        "status", "short_review", "identities",
        "achievements", "works", "intro", "title", "honor",
    }
    written: List[str] = []
    for k, v in fields.items():
        if k not in acceptable:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, list) and not v:
            continue
        existing[k] = v
        written.append(str(k))
    if not written:
        return False, "empty-fields"
    existing.setdefault("spotlight", "")
    existing.setdefault("quotes", [])
    existing.setdefault("review", "")
    existing.setdefault("reviews", [])
    items[person] = existing
    payload["items"] = items
    _write_json(_PEOPLE_SUMMARY_PATH, payload)
    return True, f"fields={','.join(written)}"


def _spawn_background_summary_fill(person: str, md_text: str, timeout_seconds: int = 60) -> None:
    """在后台线程里跑 LLM-fill,不阻塞主调用。

    失败只 log,不抛异常;外部调用方要么继续 fire-and-forget,要么用
    ``llm_fill_summary_for`` 同步版本。
    """

    def _runner() -> None:
        try:
            ok, detail = llm_fill_summary_for(person, md_text, timeout_seconds=timeout_seconds)
            _LOGGER.info("async_summary_fill ok=%s detail=%s person=%s", ok, detail, person)
        except Exception as exc:
            _LOGGER.warning("async_summary_fill crashed: %s person=%s", exc, person)

    import threading as _t
    t = _t.Thread(target=_runner, name=f"summary-fill-{person}", daemon=True)
    t.start()





def register_new_person(
    person: str,
    *,
    md_path: Optional[str] = None,
    md_text: Optional[str] = None,
    html_path: Optional[str] = None,
    rebuild_homepage: bool = False,
    dry_run: bool = False,
    paths: Optional[Dict[str, Path]] = None,
    llm_fill_summary: bool = True,
    async_fill_summary: bool = False,
    summary_timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """注册新人物到三层 corpus,可选重跑首页构建。

    参数:
      person:           必填,人物名
      md_path:          可选,markdown 路径,会从那里读文本
      md_text:          可选,直接传入 markdown 字符串 (覆盖 md_path)
      html_path:        可选,保留给将来注册 logo / preview
      rebuild_homepage: True 时调 ``tools/build/homepage/main.py``,较慢
      dry_run:          True 时只统计会做什么,不实际写盘

    返回:
      ``{"person": ..., "master": (ok, detail), "summary": (ok, detail),
        "birth_coords": (ok, detail), "homepage_rebuild": (ok, detail)}``
    """
    global _PEOPLE_MASTER_PATH, _PEOPLE_SUMMARY_PATH, _BIRTH_COORDS_PATH
    if paths:
        _PEOPLE_MASTER_PATH = paths.get("master", _PEOPLE_MASTER_PATH)
        _PEOPLE_SUMMARY_PATH = paths.get("summary", _PEOPLE_SUMMARY_PATH)
        _BIRTH_COORDS_PATH = paths.get("birth_coords", _BIRTH_COORDS_PATH)

    if not md_text and md_path and Path(md_path).exists():
        try:
            md_text = Path(md_path).read_text(encoding="utf-8")
        except Exception as e:
            _LOGGER.warning("读 md %s 失败: %s", md_path, e)
            md_text = ""

    md_payload = md_text or ""
    out: Dict[str, Any] = {"person": person, "md_chars": len(md_payload)}

    def _mirror_to_artifacts() -> str:
        """把更新后的 corpus 同步到 artifacts/story_map/ (前端可直接 fetch)。"""
        try:
            artifacts_dir = _REPO_ROOT / "artifacts" / "story_map"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            for src, fname in (
                (_PEOPLE_SUMMARY_PATH, "people_summary_index.json"),
                (_BIRTH_COORDS_PATH, "people_birth_coords_wgs84.json"),
                (_PEOPLE_MASTER_PATH, "people_master.json"),
            ):
                if src and src.exists():
                    (artifacts_dir / fname).write_text(
                        src.read_text(encoding="utf-8"), encoding="utf-8"
                    )
        except Exception as exc:
            return f"mirror-failed: {exc}"
        return "mirrored"

    out["artifacts_mirror"] = (False, "skipped")  # 失败兜底

    if dry_run:
        out["master"] = (False, "dry-run")
        out["summary"] = (False, "dry-run")
        out["birth_coords"] = (False, "dry-run")
        return out

    out["master"] = update_people_master(person, md_payload)
    out["summary"] = update_people_summary(person, md_payload)
    out["birth_coords"] = update_birth_coords(person, md_payload)

    # summary 字段里 status / identities / achievements / works 一开始是空,
    # 用 LLM 把这些字段填上后再 rebuild_homepage 才能在首页人物卡上看到内容。
    if llm_fill_summary and md_payload.strip():
        if async_fill_summary:
            _spawn_background_summary_fill(
                person, md_payload, timeout_seconds=summary_timeout_seconds,
            )
            out["summary_fill"] = (True, "scheduled-background")
        else:
            try:
                ok, detail = llm_fill_summary_for(
                    person, md_payload, timeout_seconds=summary_timeout_seconds,
                )
                out["summary_fill"] = (ok, detail)
            except Exception as exc:
                _LOGGER.warning("llm_fill_summary_for 异常: %s", exc)
                out["summary_fill"] = (False, f"exception: {exc}")
    else:
        out["summary_fill"] = (False, "skipped")

    out["artifacts_mirror"] = (True, _mirror_to_artifacts())

    if rebuild_homepage:
        script = _REPO_ROOT / "tools" / "build" / "homepage" / "main.py"
        if not script.exists():
            out["homepage_rebuild"] = (False, "missing-builder-script")
        else:
            try:
                subprocess.run(
                    ["python3", str(script)],
                    cwd=str(_REPO_ROOT),
                    check=True,
                    capture_output=True,
                    timeout=600,
                )
                out["homepage_rebuild"] = (True, "rebuilt")
            except subprocess.CalledProcessError as e:
                out["homepage_rebuild"] = (False, f"builder-failed: {e}")
            except Exception as e:
                out["homepage_rebuild"] = (False, f"builder-error: {e}")
    else:
        out["homepage_rebuild"] = (False, "skipped")
    return out

from __future__ import annotations

import json
import os
import re
import threading
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen


def first_env(*names: str) -> str:
    for name in names:
        val = os.getenv(name)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def env_flag(*names: str) -> bool:
    return first_env(*names).strip().lower() in {"1", "true", "yes", "on", "y"}


def apply_minimax_env_aliases() -> None:
    key = first_env(
        "LLM_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX_API_Key",
        "minimax_API_KEY",
        "minimax_API_Key",
        "MIMO_API_KEY",
        "MIMO_API_Key",
    )
    base = first_env(
        "LLM_BASE_URL",
        "MINIMAX_BASE_URL",
        "MINIMAX_API_BASE_URL",
        "minimax_BASE_URL",
        "minimax_API_Base_URL",
        "MIMO_BASE_URL",
    )
    model = first_env(
        "LLM_MODEL_ID",
        "MINIMAX_MODEL",
        "MINIMAX_MODEL_ID",
        "minimax_MODEL",
        "minimax_MODEL_ID",
        "MODEL",
        "MIMO_MODEL",
        "MIMO_MODEL_ID",
    )
    if key:
        os.environ.setdefault("LLM_API_KEY", key)
        os.environ.setdefault("MIMO_API_KEY", key)
        os.environ.setdefault("API_KEY", key)
    if base:
        os.environ.setdefault("LLM_BASE_URL", base)
        os.environ.setdefault("MIMO_BASE_URL", base)
        os.environ.setdefault("BASE_URL", base)
    if model:
        os.environ.setdefault("LLM_MODEL_ID", model)
        os.environ.setdefault("MODEL", model)
        os.environ.setdefault("MIMO_MODEL", model)
    if key and base and not os.getenv("LLM_PROVIDER") and "minimax" in base.lower():
        os.environ["LLM_PROVIDER"] = "minimax"


def collect_startup_issues(project_root: str) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    root = os.path.abspath(project_root)
    story_dir = os.path.join(root, "storymap", "examples", "story")
    artifact_dir = os.path.join(root, "artifacts", "story_map")
    runtime_dir = os.path.join(root, "artifacts", "runtime")

    if not os.path.isdir(story_dir):
        errors.append(f"缺少人物故事目录：{story_dir}")
    else:
        notes.append(f"人物故事目录可用：{story_dir}")

    for directory, label in ((artifact_dir, "产物目录"), (runtime_dir, "运行时目录")):
        try:
            os.makedirs(directory, exist_ok=True)
            notes.append(f"{label}可写：{directory}")
        except Exception as exc:
            errors.append(f"{label}不可写：{directory}（{exc}）")

    llm_key = first_env("LLM_API_KEY", "MINIMAX_API_KEY", "MIMO_API_KEY", "API_KEY")
    llm_base = first_env("LLM_BASE_URL", "MINIMAX_BASE_URL", "MIMO_BASE_URL", "BASE_URL")
    llm_model = first_env("LLM_MODEL_ID", "MINIMAX_MODEL", "MIMO_MODEL", "MODEL")
    missing_llm = []
    if not llm_key:
        missing_llm.append("LLM_API_KEY")
    if not llm_base:
        missing_llm.append("LLM_BASE_URL")
    if not llm_model:
        missing_llm.append("LLM_MODEL_ID")
    if missing_llm:
        warnings.append(
            "缺少大模型配置：{names}；人物自动生成与在线识别可能失败。".format(
                names=", ".join(missing_llm)
            )
        )
    else:
        notes.append("大模型配置完整")

    geovis_token = first_env("GEOVIS_TOKEN", "GeoVisKey", "DATACLOUD_TOKEN", "DATACLOUD_MAP_TOKEN")
    amap_js_key = first_env("AMAP_KEY")
    amap_security = first_env("AMAP_SECURITY")
    if geovis_token:
        notes.append("GeoVis 前端地图配置完整")
    else:
        warnings.append("缺少 GeoVisKey/GEOVIS_TOKEN；地图页面在浏览器端可能无法直接加载底图。")
    if not amap_js_key:
        warnings.append("缺少 AMAP_KEY；高德前端地图能力将不可用。")
    elif not amap_security:
        warnings.append("缺少 AMAP_SECURITY；部分环境下高德 JS SDK 可能加载失败。")
    else:
        notes.append("高德前端地图配置完整")

    geocode_key = first_env(
        "location_api",
        "locaion_api",
        "LOCATION_API",
        "MAPSCO_API_KEY",
        "AMAP_WEBSERVICE_KEY",
        "AMAP_WEB_SERVICE_KEY",
        "AMAP_REST_KEY",
    )
    if not geocode_key:
        warnings.append("缺少地理编码密钥；新地点可能无法在线解析坐标。")
    else:
        notes.append("地理编码配置可用")

    return {"errors": errors, "warnings": warnings, "notes": notes}


def validate_startup_or_raise(logger: object, project_root: str, *, strict: bool = False) -> Dict[str, List[str]]:
    issues = collect_startup_issues(project_root)
    for message in issues["notes"]:
        logger.info("startup_check ok=%s", message)
    for message in issues["warnings"]:
        logger.warning("startup_check warning=%s", message)
    for message in issues["errors"]:
        logger.error("startup_check error=%s", message)

    if issues["errors"]:
        raise RuntimeError("启动校验失败：" + "；".join(issues["errors"]))
    if strict and issues["warnings"]:
        raise RuntimeError("严格启动校验失败：" + "；".join(issues["warnings"]))
    return issues


class SharedLLMClientFactory:
    def __init__(self, client_cls):
        self._client_cls = client_cls
        self._cached_client = None
        self._lock = threading.Lock()

    def get_client(self, event_callback=None):
        if event_callback:
            return self._client_cls(event_callback=event_callback)
        if self._cached_client is None:
            with self._lock:
                if self._cached_client is None:
                    self._cached_client = self._client_cls()
        return self._cached_client


def build_amap_config_js() -> bytes:
    key = (os.getenv("AMAP_KEY") or "").strip()
    sec = (os.getenv("AMAP_SECURITY") or "").strip()
    return (
        "window.AMAP_KEY={key};window.AMAP_SECURITY={security};".format(
            key=json.dumps(key, ensure_ascii=False),
            security=json.dumps(sec, ensure_ascii=False),
        ).encode("utf-8")
    )


def build_geovis_config_js() -> bytes:
    token = first_env("GEOVIS_TOKEN", "GeoVisKey", "DATACLOUD_TOKEN", "DATACLOUD_MAP_TOKEN")
    return f"window.GEOVIS_TOKEN={json.dumps(token, ensure_ascii=False)};".encode("utf-8")


def local_history_reply(messages: object) -> str:
    if not isinstance(messages, list):
        return "史料未载；我不敢妄言。"
    last_user = ""
    sys_text = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "")
        if role == "system":
            sys_text = content
        if role == "user":
            last_user = content

    name = ""
    dynasty = ""
    birthplace = ""
    life = ""
    if sys_text:
        matched = re.search(r"扮演历史人物[:：]\s*([^\n。]+)", sys_text)
        if matched:
            name = matched.group(1).strip()
        matched = re.search(r"朝代[:：]\s*([^\n]+)", sys_text)
        if matched:
            dynasty = matched.group(1).strip()
        matched = re.search(r"籍贯[:：]\s*([^\n]+)", sys_text)
        if matched:
            birthplace = matched.group(1).strip()
        matched = re.search(r"生卒[:：]\s*([^\n]+)", sys_text)
        if matched:
            life = matched.group(1).strip()

    if not name:
        name = "在下"

    question = str(last_user or "").strip()
    compact_question = re.sub(r"\s+", " ", question)
    strict_mode = bool(sys_text and "你只基于给定资料作答" in sys_text)

    intro_lines = [f"{name if name != '在下' else '在下'}在此。"]
    meta = "；".join(
        [
            part
            for part in [
                dynasty and f"时在{dynasty}",
                birthplace and f"籍贯{birthplace}",
                life and f"生卒{life}",
            ]
            if part
        ]
    )
    if meta:
        intro_lines.append(meta + "。")

    if any(token in compact_question for token in ["你是谁", "你是誰", "何人", "何许人", "介绍你", "自我介绍"]):
        return "\n".join(intro_lines + ["我以所历与所闻相告：所述若无据，必言“史料未载”。"])

    timeline = ""
    if sys_text:
        matched = re.search(r"【足迹时间线】\n([\s\S]*?)(?:\n\n【|$)", sys_text)
        if matched:
            cleaned = []
            for line in [ln.strip() for ln in matched.group(1).splitlines() if ln.strip()]:
                stripped = re.sub(r"；意义：.*$", "", line).strip()
                if stripped:
                    cleaned.append(stripped)
            timeline = "\n".join(cleaned[:10])

    if any(token in compact_question for token in ["严格史实", "适度想象", "想象模式", "史实模式"]):
        return "\n".join(
            intro_lines
            + [
                "我可按两种口径答你：",
                "- **严格史实**：只凭已给的资料与通行史识；不确定处直说“史料未载/存疑”。",
                "- **适度想象**：不违背大史实的前提下补足细节，但会用“（或许/我推想）”标注推测。",
            ]
        )

    if "地动仪" in compact_question or "候风地动仪" in compact_question:
        answer = [
            "你问 **地动仪** 的原理，我就直说其大意：",
            "- 史载为“候风地动仪”，用于**感知远方地震**并指示方位；细部结构后世多有复原，难言尽确。",
            "- 通常的复原说法是：仪内有触发机构，受震则使某一方向的机关**释放**，令外部相应方位的“龙”口落丸，坠入“蟾”口，以示震来方向。",
        ]
        if strict_mode:
            answer.append("- 若要更细的杠杆/倒摆细节，史料并不一致，我不敢妄断。")
        return "\n".join(intro_lines + answer)

    if "浑天仪" in compact_question:
        return "\n".join(
            intro_lines
            + [
                "你问 **浑天仪**：",
                "- 它用同心的环与刻度，模拟天球与日月星辰的运行，用来**演示天象**并辅助观测。",
                "- 我所重者在“以器证理”：把天文理论落到可操作的仪器上。",
            ]
        )

    if any(token in compact_question for token in ["足迹", "行程", "去过", "走过", "迁", "路", "到过", "在哪", "哪里"]):
        if timeline:
            return "\n".join(intro_lines + ["我大略记得行止如下：", timeline, "若你要细问某一站，我可据此展开。"])
        return "\n".join(intro_lines + ["史料未载；我不敢妄言。"])

    if sys_text:
        matched = re.search(r"【人物要点】\n([\s\S]*?)(?:\n\n【|$)", sys_text)
        facts = matched.group(1).strip() if matched else ""
        if facts:
            keywords = [word for word in re.split(r"[，,。；;\s]+", compact_question) if 1 <= len(word) <= 6]
            hits = []
            for line in [item.strip() for item in facts.splitlines() if item.strip()]:
                if any(keyword and keyword in line for keyword in keywords):
                    hits.append(line)
            if hits:
                return "\n".join(intro_lines + ["我可据此答你：", "- " + "\n- ".join(hits[:6])])

    hint = "你可问：我为何作此抉择？此事在当时是什么处境？我最难忘的一次远行在何处？"
    return "\n".join(
        intro_lines
        + [
            "此问我尽力答之。若你给我更具体的对象（人/事/器物/作品），我可答得更准。",
            hint,
        ]
    )


def vendor_content_type(name: str) -> str:
    lower = str(name or "").lower()
    if lower.endswith(".css"):
        return "text/css; charset=utf-8"
    if lower.endswith(".js"):
        return "application/javascript; charset=utf-8"
    return "application/octet-stream"


def fetch_vendor_bytes(name: str, vendor_sources: Dict[str, List[str]]) -> Tuple[str, bytes]:
    urls = vendor_sources.get(name) or []
    if not urls:
        raise RuntimeError("vendor_not_found")
    last_err: Optional[Exception] = None
    for url in urls:
        try:
            request = Request(
                url=url,
                method="GET",
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; story_map/1.0)",
                    "Accept": "*/*",
                },
            )
            with urlopen(request, timeout=12) as response:
                data = response.read()
            if data:
                return vendor_content_type(name), data
        except Exception as exc:
            last_err = exc
    raise RuntimeError(str(last_err) if last_err else "vendor_fetch_failed")


def resolve_cors_origin(origin: str, allowed_origins: List[str]) -> Optional[str]:
    if not origin:
        return "*" if "*" in allowed_origins else None
    if "*" in allowed_origins:
        return "*"
    if origin in allowed_origins:
        return origin
    return None


def validate_input_text(text: object, max_text_len: int) -> Optional[str]:
    if not isinstance(text, str):
        return "输入必须是字符串"
    cleaned = text.strip()
    if not cleaned:
        return "输入不能为空"
    if len(cleaned) > max_text_len:
        return f"输入过长（最多 {max_text_len} 字符）"
    return None


def format_seconds(sec: float) -> str:
    return f"{sec:.2f}s"


def compute_overlaps(people: List[Dict[str, object]]) -> List[Dict[str, object]]:
    counts: Dict[str, int] = {}
    for item in people:
        locations = item.get("locations") or []
        names = set()
        for loc in locations:
            name = (loc.get("modernName") or loc.get("name") or "").strip()
            if name:
                names.add(name)
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    overlaps = [{"name": name, "count": count} for name, count in counts.items() if count >= 2]
    overlaps.sort(key=lambda item: (-item["count"], item["name"]))
    return overlaps


def build_conclusion(results: List[Dict[str, object]], multi: bool) -> str:
    ok = [
        item
        for item in results
        if bool(item.get("ok")) or str(item.get("status") or "").strip() == "degraded"
    ]
    failed = [
        item
        for item in results
        if not (bool(item.get("ok")) or str(item.get("status") or "").strip() == "degraded")
    ]
    if multi:
        return f"合并视图完成：人物 {len(ok)}，失败 {len(failed)}"
    if ok:
        return f"生成完成：人物 {len(ok)}，失败 {len(failed)}"
    return "未生成成功"

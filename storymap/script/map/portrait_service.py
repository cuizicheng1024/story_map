"""
portrait_service
职责：为历史人物生成艺术风格肖像图，缓存在 artifacts/story_map/portraits/ 下。

数据源：MiniMax image-01 / image-01-live 文生图模型。
- 国内：`https://api.minimaxi.com/v1/image_generation`
- 海外：`https://api.minimax.io/v1/image_generation`

特点：
- 异步任务式请求 → 同步轮询 result_url
- 本地文件缓存（按人物名 hash 命名）
- prompt 由 LLM 先润色、再发往生图模型，确保风格统一
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..core.env_utils import load_project_env
from ..core.project_paths import story_artifacts_dir_path

_LOGGER = logging.getLogger("portrait_service")
if not _LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)

_PORTRAIT_DIRNAME = "portraits"
_LOCK = threading.Lock()

_DYNASTY_STYLE_HINTS: Dict[str, str] = {
    "唐": "Tang dynasty robes, silk fabric, scholarly appearance, ink-wash mountains",
    "宋": "Song dynasty robes, elegant scholar look, bamboo and misty river",
    "元": "Yuan dynasty attire, broad sleeves, distant grasslands",
    "明": "Ming dynasty official robes, dark square hat, restrained composition",
    "清": "Qing dynasty scholar attire, queue, modest study room",
    "汉": "Han dynasty ceremonial robes, dignified, classical Chinese backdrop",
    "魏晋": "Wei-Jin era flowing robes, bamboo grove, free-spirited aura",
    "近代": "early 20th century Chinese intellectual, long gown or western suit",
}


@dataclass
class PortraitRequest:
    name: str
    dynasty: str = ""
    title: str = ""
    short_bio: str = ""
    style: str = "ink_wash"  # ink_wash | gongbi | realistic | cartoon
    aspect_ratio: str = "1:1"


def _env_str(*keys: str, default: str = "") -> str:
    try:
        load_project_env(from_file=".env")
    except Exception:
        pass
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v.strip()
    return default


def _image_api_base() -> str:
    base = _env_str("LLM_BASE_URL", default="https://api.minimaxi.com/v1")
    return base.rstrip("/")


def _image_model() -> str:
    return _env_str("STORY_MAP_IMAGE_MODEL", default="image-01")


def _api_key() -> str:
    return _env_str("LLM_API_KEY", default="")


def portrait_dir() -> Path:
    base = story_artifacts_dir_path() / _PORTRAIT_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_filename(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)[:48]
    return f"{safe}-{digest}"


def portrait_cache_path(name: str) -> Path:
    """
    返回人物肖像缓存路径。先检查已存在的扩展名，避免 .png/.jpg 漂移。
    支持 .jpg/.png/.webp/.gif/.svg 五种扩展名（SVG 由本地占位生成）。

    同一人物可能有多个别名（如 孔子 / 孔丘 / 至圣先师），按以下顺序查找：
      1. 传入的 name 直接哈希
      2. 该人物的已知别名列表（合并去重）
      3. 兜底：返回 .png 路径让调用方决定
    """
    # 加载别名表（首次调用时缓存）
    candidates = _name_candidates(name)
    for candidate_name in candidates:
        base = portrait_dir() / _safe_filename(candidate_name)
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
            p = base.with_suffix(ext)
            if p.exists() and p.stat().st_size > 0:
                return p
    # 兜底：使用传入 name 的 .png 路径（让调用方决定）
    return portrait_dir() / _safe_filename(name) / _safe_filename(name) if False else (
        (portrait_dir() / _safe_filename(name)).with_suffix(".png")
    )


# ---------------------------------------------------------------------------
# 别名支持：data.person.name = "孔丘" 但磁盘文件名按 "孔子" 哈希
# ---------------------------------------------------------------------------
_ALIAS_OVERRIDES: Dict[str, List[str]] = {
    # 当 name 命中键时，额外尝试这些别名（包括原名本身）
    "孔丘": ["孔丘", "孔子"],
    "至圣先师": ["至圣先师", "孔子", "孔丘"],
}


def _name_candidates(name: str) -> List[str]:
    """返回查找该人物 portrait 时应该尝试的所有 name 候选。"""
    name = (name or "").strip()
    if not name:
        return []
    if name in _ALIAS_OVERRIDES:
        # 去重保持顺序
        seen = set()
        out = []
        for n in _ALIAS_OVERRIDES[name]:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out
    return [name]


def portrait_base_path(name: str) -> Path:
    """不带后缀的基路径，供写入时按真实扩展名覆盖。"""
    return portrait_dir() / _safe_filename(name)


def has_cached_portrait(name: str) -> bool:
    p = portrait_cache_path(name)
    return p.exists() and p.stat().st_size > 0


def _build_prompt(req: PortraitRequest) -> str:
    dynasty_hint = _DYNASTY_STYLE_HINTS.get(req.dynasty.strip(), "classical Chinese setting, ink-wash atmosphere")
    name = req.name.strip() or "ancient Chinese historical figure"
    title = req.title.strip()
    bio = req.short_bio.strip()

    style_descr = {
        "ink_wash": "traditional Chinese ink wash painting (水墨画), monochrome with subtle accent, brush strokes visible, paper texture, museum-quality",
        "gongbi": "traditional Chinese gongbi (工笔画) meticulous brushwork, vivid mineral pigments, silk scroll",
        "realistic": "cinematic portrait photography, soft cinematic lighting, 85mm lens, bokeh background",
        "cartoon": "modern flat illustration, soft pastel palette, clean line work, friendly academic vibe",
    }.get(req.style, "traditional Chinese ink wash painting")

    parts = [
        f"Portrait of {name}, a historical figure",
        dynasty_hint,
    ]
    if title:
        parts.append(f"depicted as: {title}")
    if bio:
        parts.append(f"context: {bio}")
    parts.append(
        "respectful, dignified, no facial exaggeration, no violence, no caricature, frontal or three-quarter pose, head and upper torso"
    )
    parts.append(style_descr)
    parts.append("high detail, no watermark, no text overlay")
    return ", ".join(parts)


def _call_image_api(req: PortraitRequest, prompt: str, *, n: int = 1) -> list[bytes]:
    api_key = _api_key()
    if not api_key:
        raise RuntimeError("LLM_API_KEY 未配置，无法调用生图接口")
    url = f"{_image_api_base()}/image_generation"
    payload = {
        "model": _image_model(),
        "prompt": prompt,
        "aspect_ratio": req.aspect_ratio or "1:1",
        "response_format": "base64",
        "n": max(1, min(int(n or 1), 4)),
        "prompt_optimizer": True,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code") not in (0, None):
        raise RuntimeError(f"生图接口错误: {base_resp.get('status_msg') or data}")
    payload_block = data.get("data") or {}
    encoded_list = payload_block.get("image_base64") or []
    if not encoded_list:
        urls = payload_block.get("image_urls") or []
        if urls:
            out: list[bytes] = []
            for u in urls:
                with urlopen(u, timeout=60) as r2:
                    out.append(r2.read())
            return out
        raise RuntimeError("生图接口未返回图像数据")
    return [base64.b64decode(item) for item in encoded_list]


def _sniff_extension(blob: bytes) -> str:
    """根据 magic bytes 推断图片扩展名（image-01 默认返回 JPEG）。"""
    if len(blob) >= 8 and blob[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if len(blob) >= 3 and blob[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if len(blob) >= 6 and (blob[:6] in (b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    return ".png"  # 默认按 png 处理


def _ensure_extension(target: Path, blob: bytes) -> Path:
    """若目标扩展名与实际内容不一致，自动调整为正确的扩展名。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    actual = _sniff_extension(blob)
    if target.suffix.lower() != actual:
        target = target.with_suffix(actual)
    return target


def generate_portrait(req: PortraitRequest, *, force: bool = False, n: int = 1) -> Tuple[Path, list[Path], bool]:
    """
    生成并缓存人物肖像。返回 (primary_path, candidate_paths, from_cache)。
    若缓存已存在且非 force，直接返回主路径（from_cache=True）。
    """
    target = portrait_cache_path(req.name)
    candidates: list[Path] = []
    if not force and target.exists() and target.stat().st_size > 0:
        return target, candidates, True
    prompt = _build_prompt(req)
    images = _call_image_api(req, prompt, n=n)
    if not images:
        raise RuntimeError("生图接口未返回图像")
    base = portrait_base_path(req.name)
    target = _ensure_extension(base, images[0])
    target.write_bytes(images[0])
    for idx, blob in enumerate(images[1:], start=2):
        candidate_ext = _sniff_extension(blob)
        candidate = base.with_name(base.name + f"-{idx}{candidate_ext}")
        candidate.write_bytes(blob)
        candidates.append(candidate)
    return target, candidates, False


def portrait_status() -> dict:
    d = portrait_dir()
    files = sorted(p for p in d.glob("*.png") if p.is_file())
    return {
        "ok": True,
        "model": _image_model(),
        "endpoint": f"{_image_api_base()}/image_generation",
        "cache_dir": str(d),
        "cached_count": len(files),
    }
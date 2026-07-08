"""
故事地图 Agent 记忆缓存模块。

本模块提供了一个基于 JSON 文件的持久化缓存存储（StoryAgentMemoryStore），
用于缓存历史人物搜索（people）和古地名坐标映射（places）的结果，
以减少对搜索/地理编码 API 的重复调用。

核心特性：
- 支持可配置的 TTL（生存时间），过期条目自动淘汰
- 线程安全的读写操作（RLock）
- 多进程安全的写入策略（通过 PID 区分临时文件）
- 支持按桶（bucket）粒度的缓存失效
- 使用 schema_version 防止不兼容的缓存数据被加载

默认配置：
- 缓存文件路径：<项目根>/.cache/story_agent_memory.json（可通过环境变量覆盖）
- 默认 TTL：7 天（604800 秒）
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Dict, List, Optional
from ...core.project_paths import project_root_path


# =============================================================================
# 全局常量
# =============================================================================

# 内存缓存的 schema 版本号，用于兼容性校验
# 当缓存数据结构发生不兼容变更时，应递增此版本号
DEFAULT_MEMORY_SCHEMA_VERSION = 2

# 默认缓存过期时间：7 天（单位：秒）
DEFAULT_MEMORY_TTL_SECONDS = 7 * 24 * 60 * 60


# =============================================================================
# 配置解析函数
# =============================================================================

def resolve_memory_cache_path() -> str:
    """
    解析内存缓存文件的存储路径。

    优先使用环境变量 `STORY_AGENT_MEMORY_CACHE` 指定的路径；
    若未设置，则使用默认路径 `<项目根>/.cache/story_agent_memory.json`。

    Returns:
        str: 缓存文件的绝对路径。
    """
    path = (os.getenv("STORY_AGENT_MEMORY_CACHE") or "").strip()
    if path:
        return os.path.abspath(os.path.expanduser(path))
    return os.path.join(project_root_path(), ".cache", "story_agent_memory.json")


def resolve_memory_ttl_seconds() -> int:
    """
    解析缓存过期时间（TTL）。

    优先使用环境变量 `STORY_AGENT_MEMORY_TTL_SECONDS` 指定的值；
    若未设置或解析失败，则返回默认值 7 天。

    Returns:
        int: TTL 值，单位秒，保证非负。
    """
    raw = (os.getenv("STORY_AGENT_MEMORY_TTL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_MEMORY_TTL_SECONDS
    try:
        return max(0, int(raw))
    except Exception:
        return DEFAULT_MEMORY_TTL_SECONDS


# =============================================================================
# 内部工具函数
# =============================================================================

def _now_ts() -> float:
    """
    获取当前 Unix 时间戳（秒，浮点数）。

    Returns:
        float: 当前时间戳。
    """
    return float(time.time())


def _normalize_place_key(text: str) -> str:
    """
    对地名进行归一化处理，生成统一的地名键。

    归一化步骤：
    1. 去除首尾空白，转为小写
    2. 去除所有空白字符（空格、制表符、换行）
    3. 去除括号及括号内的内容（包括中英文括号）
    4. 去除标点符号
    5. 去除常见后缀词（如"一带"、"附近"、"周边"等）

    Args:
        text: 原始地名字符串。

    Returns:
        str: 归一化后的地名键，若输入为空则返回空字符串。
    """
    content = str(text or "").strip().lower()
    if not content:
        return ""

    # 步骤 1：去除所有空白字符
    content = re.sub(r"[\s\t\r\n]+", "", content)

    # 步骤 2：去除括号及括号内容（中英文括号均支持）
    content = re.sub(r"[（(].*?[）)]", "", content)

    # 步骤 3：去除标点符号
    content = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'""'·•/\\|-]+", "", content)

    # 步骤 4：去除常见地理后缀词
    content = re.sub(r"(一带|附近|周边|地区|境内|境外|等地|之地|左右|一线)$", "", content)

    return content.strip()


# =============================================================================
# 缓存存储核心类
# =============================================================================

class StoryAgentMemoryStore:
    """
    故事 Agent 的持久化内存缓存存储。

    使用 JSON 文件作为持久化后端，维护两个数据桶：
    - `people`：人物搜索缓存
    - `places`：古地名坐标映射缓存

    每个桶中的条目均包含 `updated_at` 时间戳，
    读取时自动检查并淘汰过期条目。

    线程安全：所有读写操作均使用 threading.RLock() 保护。
    进程安全：写入时使用 PID 区分的临时文件，再原子替换。
    """

    def __init__(
        self,
        path: Optional[str] = None,
        *,
        ttl_seconds: Optional[int] = None,
        schema_version: int = DEFAULT_MEMORY_SCHEMA_VERSION,
    ) -> None:
        """
        初始化内存缓存存储。

        Args:
            path: 缓存文件的路径，若为 None 则使用默认路径。
            ttl_seconds: 缓存过期时间（秒），若为 None 则使用环境变量或默认值。
            schema_version: 缓存 schema 版本号，不匹配的旧缓存将被忽略。

        Raises:
            无显式异常；路径相关错误在首次 _save 时才会暴露。
        """
        # 解析并规范化缓存文件路径
        self.path = os.path.abspath(os.path.expanduser(path or resolve_memory_cache_path()))

        # 设置 TTL，0 表示永不过期
        self.ttl_seconds = resolve_memory_ttl_seconds() if ttl_seconds is None else max(0, int(ttl_seconds))

        # Schema 版本号，至少为 1
        self.schema_version = max(1, int(schema_version))

        # 可重入锁，保护多线程并发访问
        self._lock = threading.RLock()

        # 延迟加载标记：首次读写时才从文件加载
        self._loaded = False

        # 内存中的缓存数据，初始为空
        self._data: Dict[str, object] = self._empty_payload()

    # -------------------------------------------------------------------------
    # 内部数据结构
    # -------------------------------------------------------------------------

    def _empty_payload(self) -> Dict[str, object]:
        """
        构建一个空的缓存载荷（payload）。

        Returns:
            dict: 包含 schema_version、空的 people 和 places 字典。
        """
        return {
            "schema_version": self.schema_version,
            "people": {},
            "places": {},
        }

    def _schema_version_from_payload(self, payload: object) -> int:
        """
        从缓存载荷中提取 schema 版本号。

        兼容两种字段名：`schema_version` 和 `version`。

        Args:
            payload: 从 JSON 文件加载的缓存载荷。

        Returns:
            int: schema 版本号，无法识别时返回 0。
        """
        if not isinstance(payload, dict):
            return 0
        raw = payload.get("schema_version", payload.get("version"))
        try:
            return int(raw or 0)
        except Exception:
            return 0

    # -------------------------------------------------------------------------
    # 缓存过期检查
    # -------------------------------------------------------------------------

    def _entry_expired(self, entry: object) -> bool:
        """
        检查一个缓存条目是否已过期。

        过期判定条件：
        - TTL 为 0：永不过期
        - 条目不是 dict 类型：视为已过期
        - 无法读取 updated_at：视为已过期
        - updated_at <= 0：视为已过期
        - 当前时间 - updated_at > TTL：已过期

        Args:
            entry: 缓存条目（应为包含 updated_at 字段的字典）。

        Returns:
            bool: True 表示已过期，False 表示有效。
        """
        # TTL 为 0 表示永不过期
        if self.ttl_seconds <= 0:
            return False

        # 非字典类型视为异常数据，标记为过期
        if not isinstance(entry, dict):
            return True

        # 提取更新时间戳
        try:
            updated_at = float(entry.get("updated_at") or 0)
        except Exception:
            return True

        # 无效时间戳视为过期
        if updated_at <= 0:
            return True

        # 判断是否超过 TTL
        return (_now_ts() - updated_at) > self.ttl_seconds

    # -------------------------------------------------------------------------
    # 缓存加载与持久化
    # -------------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """
        确保缓存数据已从文件加载到内存（延迟加载策略）。

        仅在首次调用时执行加载，后续调用直接返回。
        加载时进行 schema 版本校验，不兼容的缓存将被忽略。
        """
        with self._lock:
            if self._loaded:
                return
            self._loaded = True

            # 文件不存在时跳过加载
            if not os.path.exists(self.path):
                return

            # 读取 JSON 文件
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return

            # 类型校验
            if not isinstance(payload, dict):
                return

            # Schema 版本校验：不兼容的版本不加载
            if self._schema_version_from_payload(payload) != self.schema_version:
                return

            # 加载 people 桶
            people = payload.get("people")
            if isinstance(people, dict):
                self._data["people"] = people

            # 加载 places 桶
            places = payload.get("places")
            if isinstance(places, dict):
                self._data["places"] = places

    def _save(self) -> None:
        """
        将内存中的缓存数据持久化到 JSON 文件。

        写入策略：
        1. 确保父目录存在
        2. 先写入带 PID 的临时文件（避免多进程冲突）
        3. 使用 os.replace 原子替换目标文件
        """
        with self._lock:
            # 确保父目录存在
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            # 更新 schema 版本号
            self._data["schema_version"] = self.schema_version

            # 使用 PID 区分的临时文件，防止多进程互相覆盖
            tmp_path = f"{self.path}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)

            # 原子替换
            os.replace(tmp_path, self.path)

    # -------------------------------------------------------------------------
    # 桶级别的读取、写入与失效
    # -------------------------------------------------------------------------

    def _read_bucket_entry(self, bucket_name: str, key: str, value_field: str) -> Optional[Dict[str, object]]:
        """
        从指定桶中读取一个条目的值。

        读取时自动检查过期：若条目已过期，则将其从桶中移除并持久化。

        Args:
            bucket_name: 桶名称（如 "people"、"places"）。
            key: 条目的键。
            value_field: 条目中存储值的字段名（如 "search_result"、"place_map"）。

        Returns:
            条目的值（dict），若不存在或已过期则返回 None。
        """
        self._ensure_loaded()
        with self._lock:
            # 获取桶
            bucket = self._data.get(bucket_name)
            if not isinstance(bucket, dict):
                return None

            # 获取条目
            entry = bucket.get(key)
            if not isinstance(entry, dict):
                return None

            # 过期检查与自动淘汰
            if self._entry_expired(entry):
                bucket.pop(key, None)
                self._save()
                return None

            # 提取值字段
            value = entry.get(value_field)
            return dict(value) if isinstance(value, dict) else None

    def _write_bucket_entry(self, bucket_name: str, key: str, value_field: str, value: Dict[str, object]) -> None:
        """
        向指定桶中写入或更新一个条目的值。

        若桶不存在则自动创建；条目的 updated_at 会被更新为当前时间。

        Args:
            bucket_name: 桶名称（如 "people"、"places"）。
            key: 条目的键。
            value_field: 条目中存储值的字段名。
            value: 要写入的值（dict）。
        """
        if not key or not isinstance(value, dict):
            return
        self._ensure_loaded()
        with self._lock:
            # 获取或创建桶
            bucket = self._data.setdefault(bucket_name, {})
            if not isinstance(bucket, dict):
                return

            # 读取现有记录（保留其他字段），仅更新目标字段
            record = bucket.get(key) if isinstance(bucket.get(key), dict) else {}
            record = dict(record or {})
            record[value_field] = dict(value)
            record["updated_at"] = _now_ts()
            bucket[key] = record

        # 持久化
        self._save()

    def _invalidate_bucket_entry(self, bucket_name: str, key: str) -> bool:
        """
        使指定桶中的某个条目失效（删除）。

        Args:
            bucket_name: 桶名称。
            key: 要删除的条目键。

        Returns:
            bool: True 表示成功删除，False 表示条目不存在。
        """
        if not key:
            return False
        self._ensure_loaded()
        removed = False
        with self._lock:
            bucket = self._data.get(bucket_name)
            if not isinstance(bucket, dict):
                return False
            removed = key in bucket
            if removed:
                bucket.pop(key, None)
        if removed:
            self._save()
        return removed

    # -------------------------------------------------------------------------
    # 公开 API：人物搜索缓存
    # -------------------------------------------------------------------------

    def get_person_search(self, person: str) -> Optional[Dict[str, object]]:
        """
        获取指定人物的搜索缓存结果。

        Args:
            person: 人物名称。

        Returns:
            搜索结果的字典，若缓存未命中或已过期则返回 None。
        """
        key = str(person or "").strip()
        if not key:
            return None
        return self._read_bucket_entry("people", key, "search_result")

    def set_person_search(self, person: str, search_result: Dict[str, object]) -> None:
        """
        缓存指定人物的搜索结果。

        Args:
            person: 人物名称。
            search_result: 搜索结果数据（dict）。
        """
        key = str(person or "").strip()
        self._write_bucket_entry("people", key, "search_result", search_result)

    def invalidate_person_search(self, person: str) -> bool:
        """
        使指定人物的搜索缓存失效。

        Args:
            person: 人物名称。

        Returns:
            bool: True 表示缓存存在且已删除。
        """
        key = str(person or "").strip()
        return self._invalidate_bucket_entry("people", key)

    # -------------------------------------------------------------------------
    # 公开 API：古地名坐标映射缓存
    # -------------------------------------------------------------------------

    def get_place_map(self, place_name: str) -> Optional[Dict[str, object]]:
        """
        获取指定古地名的坐标映射缓存。

        地名会经过归一化处理（去空白、去括号、去标点、去后缀）后作为键。

        Args:
            place_name: 古地名原始名称。

        Returns:
            坐标映射的字典，若缓存未命中或已过期则返回 None。
        """
        key = _normalize_place_key(str(place_name or ""))
        if not key:
            return None
        return self._read_bucket_entry("places", key, "place_map")

    def set_place_map(self, place_name: str, place_map: Dict[str, object]) -> None:
        """
        缓存指定古地名的坐标映射结果。

        Args:
            place_name: 古地名原始名称。
            place_map: 坐标映射数据（dict）。
        """
        key = _normalize_place_key(str(place_name or ""))
        self._write_bucket_entry("places", key, "place_map", place_map)

    def invalidate_place_map(self, place_name: str) -> bool:
        """
        使指定古地名的坐标映射缓存失效。

        Args:
            place_name: 古地名原始名称。

        Returns:
            bool: True 表示缓存存在且已删除。
        """
        key = _normalize_place_key(str(place_name or ""))
        return self._invalidate_bucket_entry("places", key)

    # -------------------------------------------------------------------------
    # 公开 API：批量失效
    # -------------------------------------------------------------------------

    def invalidate_all(self, bucket: str = "") -> int:
        """
        批量使缓存失效。

        可按桶名称选择性失效，也可以清空所有桶。

        Args:
            bucket: 目标桶名称。
                    "people" → 仅清空人物缓存；
                    "places" 或 "place_map" → 仅清空地名词缓存；
                    其他值（含空字符串） → 清空所有桶。

        Returns:
            int: 被删除的缓存条目数量。
        """
        self._ensure_loaded()
        removed = 0
        bucket_names: List[str]

        # 确定需要清空的桶
        normalized_bucket = str(bucket or "").strip().lower()
        if normalized_bucket == "people":
            bucket_names = ["people"]
        elif normalized_bucket in {"places", "place_map"}:
            bucket_names = ["places"]
        else:
            bucket_names = ["people", "places"]

        # 清空指定桶
        with self._lock:
            for bucket_name in bucket_names:
                current = self._data.get(bucket_name)
                if not isinstance(current, dict):
                    continue
                removed += len(current)
                self._data[bucket_name] = {}

        # 持久化变更
        if removed:
            self._save()
        return removed


# =============================================================================
# 全局单例存储
# =============================================================================

# 全局默认存储实例（延迟初始化单例）
_DEFAULT_STORE: Optional[StoryAgentMemoryStore] = None

# 保护默认实例创建的线程锁
_DEFAULT_STORE_LOCK = threading.Lock()


def get_default_memory_store() -> StoryAgentMemoryStore:
    """
    获取全局默认的 StoryAgentMemoryStore 单例。

    线程安全的延迟初始化：首次调用时创建实例，后续调用返回同一实例。

    Returns:
        StoryAgentMemoryStore: 全局默认缓存存储实例。
    """
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = StoryAgentMemoryStore()
        return _DEFAULT_STORE


__all__ = [
    "DEFAULT_MEMORY_SCHEMA_VERSION",
    "DEFAULT_MEMORY_TTL_SECONDS",
    "StoryAgentMemoryStore",
    "get_default_memory_store",
    "resolve_memory_cache_path",
    "resolve_memory_ttl_seconds",
]

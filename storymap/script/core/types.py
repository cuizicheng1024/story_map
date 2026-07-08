"""核心数据类型定义。

为项目中频繁使用的 Dict[str, object] 松散类型提供 TypedDict/dataclass，
提升 IDE 自动补全、重构安全性和代码可读性。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, TypedDict

# ── 坐标 ────────────────────────────────────────────────────────────────

# (lat, lng) 元组，WGS84
Coord = Tuple[float, float]

# 坐标搜索缓存：key → [(lat, lng, score), ...]
CoordSearchMap = dict  # Dict[str, List[Tuple[float, float, float]]]
CoordCache = dict  # Dict[str, Coord]


# ── 地点 ────────────────────────────────────────────────────────────────

class LocationItem(TypedDict, total=False):
    """单条地点记录，对应人物轨迹中的一个点。"""
    name: str
    location: str
    ancient: str
    modern: str
    lat: float
    lng: float
    type: str          # move / stay / journey
    time: str
    stay: str
    event: str
    meaning: str
    quote: str
    md: str            # raw markdown snippet
    poster: str        # location poster image URL (filled by _attach_location_posters)


# ── 人物记录 ────────────────────────────────────────────────────────────

class LifeEventPoint(TypedDict, total=False):
    """生卒事件坐标点。"""
    date: str
    location: str
    lat: Optional[float]
    lng: Optional[float]
    coordSystem: str


class PersonHighlights(TypedDict, total=False):
    """人物关键标签（头衔、地位、身份、成就、代表作品、历史评价）。"""
    honor: str
    status: str
    identities: str
    achievements: str
    works: List[str]
    reviews: List[str]


class PersonRecord(TypedDict, total=False):
    """完整的人物元数据记录。"""
    name: str
    nameRaw: str
    foreignName: str
    foreignCountry: str
    foreignCountryZh: str
    title: str
    description: str
    descriptionHighlights: List[dict]
    quote: str
    shortReview: str
    dynasty: str
    courtesyName: str        # 字
    artName: str             # 号
    aliases: List[str]
    birthplace: str
    nativePlace: str
    avatar: str
    birth: LifeEventPoint
    death: LifeEventPoint
    lifespan: str
    highlights: PersonHighlights


# ── 完整 Profile ────────────────────────────────────────────────────────

class MapStyle(TypedDict):
    """地图视觉配置。"""
    pathColor: str
    markers: dict  # {"normal": {...}, "birth": {...}, "death": {...}}


class WorkSummary(TypedDict, total=False):
    """单条作品摘要。"""
    title: str
    dynasty: str
    genre: str
    summary: str
    description: str
    highlights: str


class ProfileData(TypedDict, total=False):
    """人物 Profile 完整输出，即 build_profile_data 的返回值。"""
    person: PersonRecord
    locations: List[LocationItem]
    coordinateSystem: str
    mapStyle: MapStyle
    textbookPoints: List[dict]
    examPoints: List[dict]
    workTexts: dict
    workSummaries: List[WorkSummary]


# ── 任务相关 ────────────────────────────────────────────────────────────

class TaskSnapshot(TypedDict, total=False):
    """异步人物生成任务的快照。"""
    task_id: str
    status: str
    people: List[str]
    text: str
    created_at: float
    updated_at: float
    progress: int
    error: str
    exists: bool
    ok: bool


class TaskListPayload(TypedDict, total=False):
    """任务列表接口返回结构。"""
    tasks: List[TaskSnapshot]
    total: int
    limit: int
    offset: int


# ── Star Office ──────────────────────────────────────────────────────────

class StarOfficeStatusPayload(TypedDict, total=False):
    """Star Office 状态接口返回。"""
    state: str
    detail: str
    progress: int
    updated_at: str
    officeName: str


class StarOfficeAgentPayload(TypedDict, total=False):
    """Star Office Agent 项。"""
    agentId: str
    name: str
    state: str
    authStatus: str
    area: str
    avatar: str


class StarOfficeMemoPayload(TypedDict):
    """Star Office 备忘录返回。"""
    success: bool
    date: str
    memo: str


# ── 生成配额 ────────────────────────────────────────────────────────────

class QuotaResult(TypedDict):
    """每日配额消费结果。"""
    allowed: bool
    limit: int
    used: int
    remaining: Optional[int]
    reset_on: str


# ── 调试事件 ────────────────────────────────────────────────────────────

class DebugEvent(TypedDict, total=False):
    """一条 TEA 调试事件。"""
    sessionId: str
    runId: str
    hypothesisId: str
    location: str
    msg: str
    data: dict
    ts: int
    origin: str
    referer: str
    userAgent: str


__all__ = [
    "Coord",
    "CoordCache",
    "CoordSearchMap",
    "DebugEvent",
    "LifeEventPoint",
    "LocationItem",
    "MapStyle",
    "PersonHighlights",
    "PersonRecord",
    "ProfileData",
    "QuotaResult",
    "StarOfficeAgentPayload",
    "StarOfficeMemoPayload",
    "StarOfficeStatusPayload",
    "TaskListPayload",
    "TaskSnapshot",
    "WorkSummary",
]

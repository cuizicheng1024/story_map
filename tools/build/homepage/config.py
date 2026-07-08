from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from storymap.script.core.project_paths import (
    data_corpus_file_path,
    data_corpus_dir_path,
    data_reports_dir_path,
    project_root_path,
    story_artifacts_dir_path,
    story_md_dir_path,
)
from storymap.script.core.person_registry import person_redirects

try:
    from tools.build.sync_star_office_ui import sync_star_office_ui as _sync_orange_office_ui_impl
except Exception:
    try:
        from tools.sync_star_office_ui import sync_star_office_ui as _sync_orange_office_ui_impl
    except Exception:
        _sync_orange_office_ui_impl = None

REPO_ROOT = project_root_path()
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
try:
    from storymap.script.core.env_utils import apply_story_map_env_aliases, env_flag
    from storymap.script.profile.graph_service import (
        graph_backend_name,
        load_home_graph_payload_with_source,
        should_sync_to_neo4j,
        sync_graph_payload_to_neo4j,
        write_normalized_graph_json,
    )
except Exception:
    apply_story_map_env_aliases = None
    env_flag = None
    graph_backend_name = None
    load_home_graph_payload_with_source = None
    should_sync_to_neo4j = None
    sync_graph_payload_to_neo4j = None
    write_normalized_graph_json = None
if load_dotenv:
    load_dotenv(dotenv_path=str((REPO_ROOT / ".env").resolve()))
    load_dotenv(dotenv_path=str((REPO_ROOT.parent / ".env").resolve()))
    load_dotenv(dotenv_path=str((REPO_ROOT / "data" / ".env").resolve()))
if apply_story_map_env_aliases:
    apply_story_map_env_aliases()
STORY_MD_DIR = story_md_dir_path()
STORY_MAP_DIR = story_artifacts_dir_path()
GRAPH_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "graph"
DATA_CORPUS_DIR = data_corpus_dir_path()
DATA_REPORTS_DIR = data_reports_dir_path()
SUMMARY_INDEX_JSON = data_corpus_file_path("people_summary_index.json")
WORK_SUMMARY_INDEX_JSON = data_corpus_file_path("work_summary_index.json")
KNOWLEDGE_GRAPH_JSON = data_corpus_file_path("people_knowledge_graph.json")
BIRTH_COORDS_WGS84_JSON = data_corpus_file_path("people_birth_coords_wgs84.json")
HOMEPAGE_PET_ASSET_OUTPUT_NAME = "orange.png"
HOMEPAGE_PET_ASSET_CANDIDATES = [
    REPO_ROOT / "assets" / "orange.png",
    REPO_ROOT / "tools" / "orange.png",
    REPO_ROOT / "orange.png",
    REPO_ROOT / "orange.PNG",
    REPO_ROOT / "tools" / "orange-avatar.png",
    REPO_ROOT / "orange-avatar.png",
]
HOME_DETAIL_NODE_FIELDS: Tuple[str, ...] = (
    "review",
    "work_summaries",
    "relations",
    "relations_meta",
    "domain_tags",
    "risk_level",
    "audit_pass",
    "audit_uncertain",
)
MIN_YEAR = -800
MAX_YEAR = 2000
ROLE_BAND_SPECS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("military", "军事", ("军事家", "兵家", "将领", "将军", "武将", "统帅", "元帅", "名将", "军人", "起义军领袖")),
    ("politics", "政治", ("政治家", "改革家", "革命家", "外交家", "领袖", "君主", "帝王", "皇帝", "总统", "丞相", "宰相", "大臣", "官员", "赞普", "首领")),
    ("literature", "文学", ("文学家", "诗人", "词人", "作家", "文豪", "散文家", "小说家", "剧作家", "文人", "辞赋家", "翻译家")),
    ("academic", "学术思想", ("哲学家", "教育家", "史学家", "历史学家", "学者", "理学家", "儒学家", "经学家", "古文字学家", "考古学家", "思想史家")),
    ("thought", "思想", ("思想家", "宗教家", "社会活动家", "启蒙思想家", "理论家", "法家代表人物")),
    ("science", "科学", ("科学家", "数学家", "物理学家", "化学家", "生物学家", "医学家", "医家", "发明家", "工程师", "农学家", "天文学家", "地理学家", "地质学家")),
    ("art", "艺术", ("艺术家", "画家", "书法家", "音乐家", "戏剧家", "戏曲家", "建筑师", "雕塑家", "设计师")),
]
ROLE_BAND_ORDER: List[str] = [item[0] for item in ROLE_BAND_SPECS] + ["other"]
ROLE_BAND_LABELS: Dict[str, str] = {key: label for key, label, _ in ROLE_BAND_SPECS}
ROLE_BAND_LABELS["other"] = "其他"
PERSON_PAGE_REDIRECTS: Dict[str, str] = person_redirects()

"""锁住 builder 核心人物构建行为。

跑: ``python3 -m pytest storymap/tests/test_builder.py -v``
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from storymap.script.profile.builder import (
    build_profile_data,
    extract_title_from_text,
    extract_works,
)


class TestExtractWorks:
    def test_extracts_from_list(self):
        works = extract_works("《静夜思》、《将进酒》、《蜀道难》")
        assert len(works) >= 3
        assert any("静夜思" in w for w in works)

    def test_handles_empty(self):
        assert extract_works("") == []


class TestExtractTitle:
    def test_extracts_first_line_as_title(self):
        title = extract_title_from_text("《将进酒》\n李白\n君不见黄河之水天上来")
        assert title is not None
        assert isinstance(title, str)

    def test_handles_empty(self):
        result = extract_title_from_text("")
        assert isinstance(result, str)


class TestBuildProfileDataMinimal:
    """对 build_profile_data 做基本的入参校验和空值防御测试。"""

    def test_rejects_empty_md(self):
        result = build_profile_data(
            "",
            fallback_person="",
            allow_geocode=False,
            split_ancient_modern=MagicMock(return_value=("", "")),
            batch_split_ancient_modern=MagicMock(),
            fuzzy_coord_lookup=MagicMock(return_value=None),
            lookup_coords_from_historical_index=MagicMock(return_value=None),
            resolve_place_coord=MagicMock(return_value=None),
            build_points_fn=MagicMock(return_value=[]),
        )
        assert result is None

    def test_rejects_none_md(self):
        result = build_profile_data(
            None,  # type: ignore[arg-type]
            fallback_person="",
            allow_geocode=False,
            split_ancient_modern=MagicMock(return_value=("", "")),
            batch_split_ancient_modern=MagicMock(),
            fuzzy_coord_lookup=MagicMock(return_value=None),
            lookup_coords_from_historical_index=MagicMock(return_value=None),
            resolve_place_coord=MagicMock(return_value=None),
            build_points_fn=MagicMock(return_value=[]),
        )
        assert result is None

    def test_rejects_md_with_only_whitespace(self):
        result = build_profile_data(
            "   \n\n  ",
            fallback_person="",
            allow_geocode=False,
            split_ancient_modern=MagicMock(return_value=("", "")),
            batch_split_ancient_modern=MagicMock(),
            fuzzy_coord_lookup=MagicMock(return_value=None),
            lookup_coords_from_historical_index=MagicMock(return_value=None),
            resolve_place_coord=MagicMock(return_value=None),
            build_points_fn=MagicMock(return_value=[]),
        )
        assert result is None

from storymap.script.quality.markdown_rules import run_html_quality_checks


def test_quality_rules_emit_structured_issue_codes():
    data = {
        "person": {"name": "测试人物", "shortReview": "", "description": "Let me think about what I know about 测试人物:"},
        "locations": [{"name": "未知地点", "lat": None, "lng": None}],
        "markdown": "## 一、简介\n内容\n## 一、重复\n待补充 待补充 待补充 待补充",
    }

    issues = run_html_quality_checks(data)
    codes = {issue["code"] for issue in issues}

    assert "MISSING_SHORT_REVIEW" in codes
    assert "LLM_THINK_LEAK" in codes
    assert "MISSING_COORDINATE" in codes
    assert "DUPLICATE_CHAPTER_NUMBER" in codes
    assert "TOO_MANY_PLACEHOLDERS" in codes
    assert all("severity" in issue for issue in issues)
    assert all("auto_fixable" in issue for issue in issues)


def test_quality_rules_flag_low_geocode_confidence():
    data = {
        "person": {"name": "测试人物", "shortReview": "人物", "description": "正常描述"},
        "locations": [{"name": "模糊地点", "lat": 30.0, "lng": 120.0, "geocodeConfidence": 0.6}],
        "markdown": "## 一、简介\n内容",
    }

    issues = run_html_quality_checks(data)
    codes = {issue["code"] for issue in issues}

    assert "GEO_LOW_CONFIDENCE" in codes

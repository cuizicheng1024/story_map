import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import offline_eval


GT_MD = """# 李白

## 人物档案

### 基本信息
- **姓名**：李白
- **时代**：唐朝
- **出生**：公元701年，碎叶城（今吉尔吉斯斯坦托克马克市）
- **去世**：公元762年，当涂（今安徽省马鞍山市当涂县）
- **享年**：61岁
- **主要身份**：诗人、文学家
- **历史地位**：诗仙
- **主要成就**：诗歌创作

### 生平概述
李白，唐朝诗人。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克市 | 出生 |
| 762年 | 当涂 | 安徽省马鞍山市当涂县 | 去世 |
"""


PRED_MD = """# 李白

## 人物档案

### 基本信息
- **姓名**：李白（字太白，号青莲居士）
- **时代**：唐代
- **出生**：公元701年，碎叶城（今吉尔吉斯斯坦托克马克市）
- **去世**：公元762年，当涂（今安徽省马鞍山市当涂县）
- **享年**：61岁
- **主要身份**：唐代诗人、浪漫主义文学代表人物
- **历史地位**：诗仙
- **主要成就**：诗歌创作

### 生平概述
李白，唐代诗人。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克市 | 出生 |
| 762年 | 当涂 | 安徽省马鞍山市当涂县 | 去世 |
"""


def test_compare_markdown_against_ground_truth_scores_expected_fields():
    report = offline_eval.compare_markdown_against_ground_truth(
        person="李白",
        generated_markdown=PRED_MD,
        ground_truth_markdown=GT_MD,
    )

    assert report["scores"]["name_accuracy"] == 1.0
    assert report["scores"]["dynasty_accuracy"] == 1.0
    assert report["scores"]["birth_year_accuracy"] == 1.0
    assert report["scores"]["death_year_accuracy"] == 1.0
    assert report["scores"]["identity_recall"] == 1.0
    assert report["scores"]["place_recall"] == 1.0
    assert report["weighted_accuracy"] >= 0.8


def test_compare_markdown_against_ground_truth_accepts_bare_numeric_years():
    pred_md = PRED_MD.replace("公元701年", "701").replace("公元762年", "762")

    report = offline_eval.compare_markdown_against_ground_truth(
        person="李白",
        generated_markdown=pred_md,
        ground_truth_markdown=GT_MD,
    )

    assert report["scores"]["birth_year_accuracy"] == 1.0
    assert report["scores"]["death_year_accuracy"] == 1.0


def test_evaluate_people_aggregates_results(tmp_path):
    gt_dir = tmp_path / "storymap" / "examples" / "story"
    gt_dir.mkdir(parents=True)
    (gt_dir / "李白.md").write_text(GT_MD, encoding="utf-8")
    (gt_dir / "杜甫.md").write_text(GT_MD.replace("李白", "杜甫"), encoding="utf-8")

    report = offline_eval.evaluate_people(
        people=["李白", "杜甫"],
        generate_markdown=lambda person: PRED_MD.replace("李白", person),
        root=tmp_path,
    )

    assert report["count"] == 2
    assert len(report["people"]) == 2
    assert report["aggregate"]["scores"]["name_accuracy"] == 1.0
    assert report["aggregate"]["weighted_accuracy"] >= 0.8


def test_load_benchmark_people_filters_missing_ground_truth(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    gt_dir = tmp_path / "storymap" / "examples" / "story"
    gt_dir.mkdir(parents=True)
    (gt_dir / "李白.md").write_text(GT_MD, encoding="utf-8")
    people_file = data_dir / "sample.json"
    people_file.write_text('["李白", "不存在的人物"]\n', encoding="utf-8")

    people = offline_eval.load_benchmark_people(
        people_file=str(people_file),
        limit=10,
        root=tmp_path,
    )

    assert people == ["李白"]


def test_evaluate_people_returns_zero_score_when_generation_fails(tmp_path):
    gt_dir = tmp_path / "storymap" / "examples" / "story"
    gt_dir.mkdir(parents=True)
    (gt_dir / "李白.md").write_text(GT_MD, encoding="utf-8")

    report = offline_eval.evaluate_people(
        people=["李白"],
        generate_markdown=lambda _person: (_ for _ in ()).throw(RuntimeError("boom")),
        root=tmp_path,
    )

    assert report["count"] == 1
    assert report["people"][0]["weighted_accuracy"] == 0.0
    assert report["people"][0]["error"] == "boom"

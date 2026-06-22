from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from . import generation_service as generation_service_utils
from ..core import parsers as parser_utils
from ..core.project_paths import data_corpus_file_path, project_root_path


def _project_root() -> Path:
    return Path(project_root_path())


def _safe_read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_year(text: str) -> Optional[int]:
    content = str(text or "")
    bce_match = re.search(r"(?:公元\s*)?前\s*(\d{1,4})(?:/\d{1,4})?\s*年?", content)
    if bce_match:
        try:
            return -int(bce_match.group(1))
        except Exception:
            return None
    match = re.search(r"(-?\d{1,4})(?:/\d{1,4})?\s*年", content)
    if not match:
        match = re.search(r"(?:公元\s*)?(-?\d{1,4})(?:/\d{1,4})?(?=[，,（(。\s]|$)", content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _normalize_person_name(text: str) -> str:
    content = _normalize_text(text)
    content = re.sub(r"[（(].*?[)）]", "", content)
    content = re.split(r"[，,、；;：:]", content)[0]
    return content.strip()


def _normalize_dynasty(text: str) -> str:
    content = _normalize_text(text)
    content = content.replace("时期", "").replace("时代", "").replace("朝代", "")
    if len(content) > 1:
        content = re.sub(r"(朝|代)$", "", content)
    return content


def _dynasty_match(lhs: str, rhs: str) -> bool:
    left = _normalize_dynasty(lhs)
    right = _normalize_dynasty(rhs)
    if not left or not right:
        return False
    return left in right or right in left


def _split_identity_tokens(text: str) -> List[str]:
    raw = str(text or "").replace("、", ",").replace("，", ",").replace("；", ",")
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


def _normalize_identity_token(text: str) -> str:
    content = _normalize_text(text)
    content = re.sub(r"^(先秦|两汉|东汉|西汉|三国|魏晋|南北朝|隋|唐|宋|元|明|清|近代|现代)", "", content)
    content = re.sub(r"(代表人物|代表|居士|诗仙|诗圣)$", "", content)
    content = content.replace("主义", "")
    content = content.replace("浪漫", "")
    for suffix in ("家", "人物", "者"):
        if content.endswith(suffix) and len(content) > len(suffix):
            content = content[: -len(suffix)]
    return content.strip()


def _identity_match(lhs: str, rhs: str) -> bool:
    left = _normalize_identity_token(lhs)
    right = _normalize_identity_token(rhs)
    if not left or not right:
        return False
    return left in right or right in left


def _identity_recall(gt_identities: Sequence[str], pred_identities: Sequence[str]) -> float:
    gt_items = [item for item in gt_identities if item]
    pred_items = [item for item in pred_identities if item]
    if not gt_items:
        return 1.0
    hits = 0
    for gt in gt_items:
        if any(_identity_match(gt, pred) for pred in pred_items):
            hits += 1
    return hits / len(gt_items)


def _place_recall(gt_places: Sequence[str], pred_places: Sequence[str]) -> float:
    gt_items = [str(item or "") for item in gt_places if str(item or "")]
    pred_items = [str(item or "") for item in pred_places if str(item or "")]
    if not gt_items:
        return 1.0
    hits = 0
    for gt in gt_items:
        if any((gt in pred) or (pred in gt) for pred in pred_items):
            hits += 1
    return hits / len(gt_items)


def _place_token_set(md: str) -> set[str]:
    parsed = parser_utils.parse_story_document(md)
    values: List[str] = []
    for item in parsed.places or []:
        if not isinstance(item, dict):
            continue
        values.append(str(item.get("ancient") or ""))
        values.append(str(item.get("modern") or ""))
    for loc in parsed.location_sections or []:
        values.append(str(getattr(loc, "name", "") or ""))
        values.append(str(getattr(loc, "location_text", "") or ""))
    out = set()
    for value in values:
        norm = parser_utils._normalize_place_key(value)
        if norm:
            out.add(norm)
    return out


def load_benchmark_people(
    *,
    people: Optional[Sequence[str]] = None,
    people_file: Optional[str] = None,
    limit: Optional[int] = None,
    root: Optional[Path] = None,
) -> List[str]:
    repo_root = root or _project_root()
    selected: List[str] = []
    if people:
        selected = [str(item).strip() for item in people if str(item or "").strip()]
    else:
        sample_path = Path(people_file) if people_file else data_corpus_file_path("pep_history_figures_sample.json", project_root=repo_root)
        raw = _safe_read_json(sample_path)
        if isinstance(raw, list):
            selected = [str(item).strip() for item in raw if str(item or "").strip()]
    deduped: List[str] = []
    seen = set()
    gt_dir = repo_root / "storymap" / "examples" / "story"
    for person in selected:
        if person in seen:
            continue
        seen.add(person)
        if not (gt_dir / f"{person}.md").exists():
            continue
        deduped.append(person)
        if limit and len(deduped) >= limit:
            break
    return deduped


def load_ground_truth_markdown(person: str, *, root: Optional[Path] = None) -> str:
    repo_root = root or _project_root()
    path = repo_root / "storymap" / "examples" / "story" / f"{person}.md"
    return path.read_text(encoding="utf-8")


def extract_core_facts(md: str) -> Dict[str, object]:
    parsed = parser_utils.parse_story_document(md)
    basic = parsed.basic_info
    identities = _split_identity_tokens(basic.identity)
    issues = generation_service_utils.validate_data_quality(md)
    return {
        "name": basic.name,
        "dynasty": basic.dynasty,
        "birth_year": _extract_year(basic.birth_text),
        "death_year": _extract_year(basic.death_text),
        "identities": identities,
        "place_tokens": sorted(_place_token_set(md)),
        "timeline_rows": len(parsed.timeline_rows or []),
        "quality_issues": issues,
    }


def enrich_markdown_for_evaluation(md: str) -> str:
    if not isinstance(md, str) or not md.strip():
        return ""
    from ..map import map_client
    enriched = parser_utils._normalize_markdown_tables(md)
    enriched = map_client.append_coords_section(enriched)
    distance_km = map_client.compute_total_distance_km(enriched)
    if isinstance(distance_km, float):
        enriched = map_client.insert_distance_intro(enriched, distance_km)
    return enriched


def compare_markdown_against_ground_truth(
    *,
    person: str,
    generated_markdown: str,
    ground_truth_markdown: str,
) -> Dict[str, object]:
    gt = extract_core_facts(ground_truth_markdown)
    pred = extract_core_facts(generated_markdown)
    gt_identities = list(gt["identities"])
    pred_identities = list(pred["identities"])
    gt_places = list(gt["place_tokens"])
    pred_places = list(pred["place_tokens"])
    identity_recall = _identity_recall(gt_identities, pred_identities)
    place_recall = _place_recall(gt_places, pred_places)
    structure_pass = 1.0 if not pred["quality_issues"] else 0.0
    scores = {
        "name_accuracy": 1.0 if _normalize_person_name(pred["name"]) == _normalize_person_name(gt["name"]) else 0.0,
        "dynasty_accuracy": 1.0 if _dynasty_match(str(pred["dynasty"]), str(gt["dynasty"])) else 0.0,
        "birth_year_accuracy": 1.0 if pred["birth_year"] == gt["birth_year"] else 0.0,
        "death_year_accuracy": 1.0 if pred["death_year"] == gt["death_year"] else 0.0,
        "identity_recall": round(identity_recall, 4),
        "place_recall": round(place_recall, 4),
        "structure_pass": structure_pass,
    }
    weighted_accuracy = round(
        (
            scores["name_accuracy"] * 0.1
            + scores["dynasty_accuracy"] * 0.1
            + scores["birth_year_accuracy"] * 0.15
            + scores["death_year_accuracy"] * 0.15
            + scores["identity_recall"] * 0.2
            + scores["place_recall"] * 0.2
            + scores["structure_pass"] * 0.1
        ),
        4,
    )
    return {
        "person": person,
        "scores": scores,
        "weighted_accuracy": weighted_accuracy,
        "ground_truth": gt,
        "prediction": pred,
    }


def evaluate_people(
    *,
    people: Sequence[str],
    generate_markdown: Callable[[str], str],
    postprocess_markdown: Optional[Callable[[str], str]] = None,
    root: Optional[Path] = None,
) -> Dict[str, object]:
    repo_root = root or _project_root()
    per_person: List[Dict[str, object]] = []
    for person in people:
        gt_md = load_ground_truth_markdown(person, root=repo_root)
        generation_error = ""
        generated_md = ""
        processed_md = ""
        try:
            generated_md = str(generate_markdown(person) or "")
            processed_md = str(postprocess_markdown(generated_md) if postprocess_markdown else generated_md)
        except Exception as exc:
            generation_error = str(exc).strip() or exc.__class__.__name__
        if generation_error or not (processed_md or generated_md).strip():
            report = {
                "person": person,
                "scores": {
                    "name_accuracy": 0.0,
                    "dynasty_accuracy": 0.0,
                    "birth_year_accuracy": 0.0,
                    "death_year_accuracy": 0.0,
                    "identity_recall": 0.0,
                    "place_recall": 0.0,
                    "structure_pass": 0.0,
                },
                "weighted_accuracy": 0.0,
                "ground_truth": extract_core_facts(gt_md),
                "prediction": {
                    "name": "",
                    "dynasty": "",
                    "birth_year": None,
                    "death_year": None,
                    "identities": [],
                    "place_tokens": [],
                    "timeline_rows": 0,
                    "quality_issues": ["内容为空或生成失败"],
                },
            }
        else:
            report = compare_markdown_against_ground_truth(
                person=person,
                generated_markdown=processed_md or generated_md,
                ground_truth_markdown=gt_md,
            )
        report["raw_markdown"] = generated_md
        report["processed_markdown"] = processed_md or generated_md
        if generation_error:
            report["error"] = generation_error
        per_person.append(report)
    if not per_person:
        return {"count": 0, "people": [], "aggregate": {}}
    metric_names = list(per_person[0]["scores"].keys())
    aggregate_scores = {
        metric: round(
            sum(float(item["scores"][metric]) for item in per_person) / len(per_person),
            4,
        )
        for metric in metric_names
    }
    aggregate = {
        "weighted_accuracy": round(
            sum(float(item["weighted_accuracy"]) for item in per_person) / len(per_person),
            4,
        ),
        "scores": aggregate_scores,
    }
    return {
        "count": len(per_person),
        "people": per_person,
        "aggregate": aggregate,
    }


def write_report(report: Dict[str, object], output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


__all__ = [
    "compare_markdown_against_ground_truth",
    "enrich_markdown_for_evaluation",
    "evaluate_people",
    "extract_core_facts",
    "load_benchmark_people",
    "load_ground_truth_markdown",
    "write_report",
]

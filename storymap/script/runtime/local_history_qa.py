from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

from ..core import parsers as parser_utils
from ..core.person_registry import canonical_person_name, person_redirects
from ..core.project_paths import classify_story_person_authenticity, story_person_names
from .local_history_qa_answering import build_local_history_answer
from .local_history_qa_request import extract_last_user, resolve_person_name


@dataclass(slots=True)
class QAResult:
    handled: bool
    content: str = ""
    person_name: str = ""
    reason: str = ""


class LocalHistoryQAAgent:
    def __init__(self, *, project_root: Callable[[], str]) -> None:
        self._project_root = project_root

    def answer(self, data: object) -> QAResult:
        if not isinstance(data, dict):
            return QAResult(False, reason="invalid_body")
        messages = data.get("messages")
        if not isinstance(messages, list):
            return QAResult(False, reason="messages_required")
        question = extract_last_user(messages)
        if not question:
            return QAResult(False, reason="empty_question")
        person_name = self._resolve_person_name(data, messages)
        if not person_name:
            return QAResult(False, reason="person_missing")
        markdown = self._load_markdown(person_name)
        if not markdown:
            return QAResult(False, person_name=person_name, reason="story_not_found")
        parsed_doc = parser_utils.parse_story_document(markdown)
        content = build_local_history_answer(person_name, question, markdown, parsed_doc)
        if not content:
            return QAResult(False, person_name=person_name, reason="no_local_match")
        return QAResult(True, content=content, person_name=person_name, reason="local_story")

    def _resolve_person_name(self, data: Dict[str, object], messages: List[Dict[str, object]]) -> str:
        known_people = self._list_known_people()
        known_aliases = [str(alias or "").strip() for alias in person_redirects(known_people).keys() if str(alias or "").strip()]
        return resolve_person_name(data, messages, known_people=known_people + known_aliases)

    def _list_known_people(self) -> List[str]:
        try:
            people = story_person_names(Path(self._project_root()) / "storymap" / "examples" / "story")
        except Exception:
            return []
        people.sort(key=len, reverse=True)
        return people

    def _load_markdown(self, person_name: str) -> str:
        story_dir = Path(self._project_root()) / "storymap" / "examples" / "story"
        accepted, _ = classify_story_person_authenticity(person_name, story_dir)
        if not accepted:
            return ""
        known_people = self._list_known_people()
        canonical = str(canonical_person_name(person_name, known_people) or person_name).strip()
        candidate = story_dir / f"{canonical}.md"
        try:
            return candidate.read_text(encoding="utf-8")
        except Exception:
            return ""

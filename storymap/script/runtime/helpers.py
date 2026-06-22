from __future__ import annotations

import os
import threading
from typing import Callable, Dict, List, Optional, Tuple


VENDOR_SOURCES: Dict[str, List[str]] = {
    # Frontend pages rely on CDN-hosted assets (React/Babel/Tailwind).
    # In restricted networks these CDNs may be blocked; serving them via the
    # same origin avoids CORS/DNS issues and keeps pages usable.
    "tailwindcss.js": [
        "https://cdn.tailwindcss.com",
    ],
    "react.production.min.js": [
        "https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js",
        "https://unpkg.com/react@18/umd/react.production.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js",
    ],
    "react-dom.production.min.js": [
        "https://cdn.jsdelivr.net/npm/react-dom@18/umd/react-dom.production.min.js",
        "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js",
    ],
    "babel.min.js": [
        "https://cdn.jsdelivr.net/npm/@babel/standalone@7.24.7/babel.min.js",
        "https://unpkg.com/@babel/standalone@7.24.7/babel.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.24.7/babel.min.js",
    ],
}


def create_runtime_helpers(
    *,
    runtime_support_utils: object,
    local_history_qa_agent_cls: object,
    story_agent_llm_cls: object,
    project_root: Callable[[], str],
    max_text_len: int,
) -> Dict[str, object]:
    client_factory = runtime_support_utils.SharedLLMClientFactory(story_agent_llm_cls)
    local_qa_agent = local_history_qa_agent_cls(project_root=project_root)
    allowed_origins = [o.strip() for o in os.getenv("STORY_MAP_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
    vendor_cache: Dict[str, Tuple[str, bytes]] = {}
    vendor_lock = threading.Lock()

    def amap_config_js() -> bytes:
        return runtime_support_utils.build_amap_config_js()

    def geovis_config_js() -> bytes:
        return runtime_support_utils.build_geovis_config_js()

    def local_history_reply(messages: object) -> str:
        return runtime_support_utils.local_history_reply(messages)

    def local_agent_reply(data: object) -> Dict[str, object]:
        result = local_qa_agent.answer(data)
        return {
            "handled": result.handled,
            "content": result.content,
            "person_name": result.person_name,
            "reason": result.reason,
        }

    def fetch_vendor_bytes(name: str) -> Tuple[str, bytes]:
        return runtime_support_utils.fetch_vendor_bytes(name, VENDOR_SOURCES)

    def resolve_cors_origin(origin: str) -> Optional[str]:
        return runtime_support_utils.resolve_cors_origin(origin, allowed_origins)

    def get_llm_client(event_callback: Optional[callable] = None, timeout_resolver: Optional[callable] = None):
        return client_factory.get_client(event_callback=event_callback, timeout_resolver=timeout_resolver)

    def validate_input_text(text: object) -> Optional[str]:
        return runtime_support_utils.validate_input_text(text, max_text_len)

    def format_seconds(sec: float) -> str:
        return runtime_support_utils.format_seconds(sec)

    return {
        "allowed_origins": allowed_origins,
        "vendor_cache": vendor_cache,
        "vendor_lock": vendor_lock,
        "amap_config_js": amap_config_js,
        "geovis_config_js": geovis_config_js,
        "local_history_reply": local_history_reply,
        "local_agent_reply": local_agent_reply,
        "fetch_vendor_bytes": fetch_vendor_bytes,
        "resolve_cors_origin": resolve_cors_origin,
        "get_llm_client": get_llm_client,
        "validate_input_text": validate_input_text,
        "format_seconds": format_seconds,
    }

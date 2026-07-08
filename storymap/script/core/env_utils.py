import logging
import os

from dotenv import load_dotenv


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def env_flag(*names: str) -> bool:
    return _first_env(*names).strip().lower() in {"1", "true", "yes", "on"}


def apply_story_map_env_aliases() -> None:
    canonical_map = {
        "AMAP_KEY": ("AMAP_KEY", "AMAP_JS_KEY", "AMAP_WEB_KEY", "Amap_API_Key", "AMAP_API_KEY"),
        "AMAP_SECURITY": (
            "AMAP_SECURITY",
            "AMAP_SECURITY_JSCODE",
            "AMAP_SECURITY_JS_CODE",
            "Amap_API_Security",
            "AMAP_API_SECURITY",
            "Amap_API_Secret",
            "AMAP_SCODE",
        ),
        "MAP_STORY_API_BASE": ("MAP_STORY_API_BASE", "STORY_MAP_API_BASE"),
        "MAP_STORY_AI_ENDPOINT": ("MAP_STORY_AI_ENDPOINT", "STORY_MAP_AI_ENDPOINT"),
    }
    for canonical, aliases in canonical_map.items():
        value = _first_env(*aliases)
        if value:
            os.environ[canonical] = value


def project_root(from_file: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(from_file), "..", ".."))


def load_project_env(*, from_file: str, override: bool = False) -> None:
    local_env = os.path.join(os.path.dirname(from_file), ".env")
    try:
        load_dotenv(dotenv_path=local_env, override=override)
    except Exception as exc:
        logging.getLogger("story_map.env").debug("跳过本地 .env 加载: %s: %s", local_env, exc)
    root = project_root(from_file)
    env_candidates = [
        os.path.join(root, ".env"),
        os.path.join(root, "data", ".env"),
        os.path.join(root, "map_story_poster", ".env"),
        os.path.join(root, "external", "map_story_poster", ".env"),
        os.path.abspath(os.path.join(root, "..", ".env")),
        os.path.abspath(os.path.join(root, "..", "..", ".env")),
    ]
    for p in env_candidates:
        try:
            if p and os.path.isfile(p):
                load_dotenv(dotenv_path=p, override=override)
        except Exception as exc:
            logging.getLogger("story_map.env").debug("跳过备选 .env 加载: %s: %s", p, exc)
    apply_story_map_env_aliases()

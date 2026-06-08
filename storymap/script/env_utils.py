import os
from dotenv import load_dotenv


def project_root(from_file: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(from_file), "..", ".."))


def load_project_env(*, from_file: str, override: bool = False) -> None:
    local_env = os.path.join(os.path.dirname(from_file), ".env")
    try:
        load_dotenv(dotenv_path=local_env, override=override)
    except Exception:
        pass
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
        except Exception:
            pass

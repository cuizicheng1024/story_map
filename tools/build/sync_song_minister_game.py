from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ZIP_PATH = REPO_ROOT / "song-minister-game.zip"
TARGET_DIR = REPO_ROOT / "artifacts" / "story_map" / "song-minister-game"


def sync_song_minister_game(target_dir: Path | None = None) -> Path:
    if not ZIP_PATH.exists():
        raise FileNotFoundError(f"missing game archive: {ZIP_PATH}")

    resolved_target = Path(target_dir) if target_dir is not None else TARGET_DIR

    # Skip sync if target already exists and ZIP hasn't changed since last extraction.
    if resolved_target.exists():
        zip_mtime = ZIP_PATH.stat().st_mtime
        target_mtime = resolved_target.stat().st_mtime
        if target_mtime >= zip_mtime:
            return resolved_target

    extract_root = resolved_target.parent
    temp_root = extract_root / ".song-minister-game-sync"
    extracted_dir = temp_root / resolved_target.name

    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(ZIP_PATH) as archive:
        archive.extractall(temp_root)

    if not extracted_dir.exists():
        raise FileNotFoundError(f"archive missing extracted directory: {resolved_target.name}")

    if resolved_target.exists():
        shutil.rmtree(resolved_target)
    shutil.move(str(extracted_dir), str(resolved_target))
    shutil.rmtree(temp_root, ignore_errors=True)
    return resolved_target


if __name__ == "__main__":
    path = sync_song_minister_game()
    print(path)

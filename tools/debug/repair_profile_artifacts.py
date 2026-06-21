from __future__ import annotations

import re
from pathlib import Path


file_path = Path(__file__).resolve()
REPO_ROOT = file_path.parents[2] if file_path.parent.name == "debug" else file_path.parents[1]
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "story_map"

UNIQ_STRINGS_SNIPPET = """const uniqStrings = (items) => {
  const out = [];
  const seen = new Set();
  for (const item of (Array.isArray(items) ? items : [])) {
    const s = String(item || '').trim();
    if (s === '' || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
};

"""


def repair_artifact(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "uniqStrings(" not in text:
        return False

    marker = "const App = () => {"
    if marker not in text:
        return False

    if "const uniqStrings = (items) => {" in text:
        updated, count = re.subn(
            r"const uniqStrings = \(items\) => \{[\s\S]*?\};\n\nconst App = \(\) => \{",
            UNIQ_STRINGS_SNIPPET + marker,
            text,
            count=1,
        )
        if count == 0:
            return False
    else:
        updated = text.replace(marker, UNIQ_STRINGS_SNIPPET + marker, 1)

    if updated == text:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    changed = []
    for path in sorted(ARTIFACTS_DIR.glob("*.html")):
        try:
            if repair_artifact(path):
                changed.append(path.name)
        except Exception:
            continue

    print({"changed": len(changed), "sample": changed[:20]})


if __name__ == "__main__":
    main()

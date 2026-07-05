import json, re, os, sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(REPO_ROOT, "artifacts", "story_map")
fails = []

for name in ["曹操", "李白", "鲁迅", "爱因斯坦", "孔子"]:
    path = os.path.join(ARTIFACTS, f"{name}.html")
    if not os.path.exists(path):
        fails.append(f"{name}.html missing")
        continue
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    m = re.search(r'const data = (\{.*?\});\s*window\.__EXPORT_DATA__ = data;', raw, re.S)
    if not m:
        fails.append(f"{name}: cannot parse data block")
        continue
    d = json.loads(m.group(1))
    p = d.get("person", {})
    for key in ["name","dynasty","description","avatar","avatarSource"]:
        if not p.get(key):
            fails.append(f"{name}: missing {key}")
    if "tailwindcss.js" in raw: fails.append(f"{name}: has tailwindcss.js")
    if "tailwind.css" not in raw: fails.append(f"{name}: missing tailwind.css")
    if "preact-compat" not in raw: fails.append(f"{name}: missing preact-compat")
    if "react.production" in raw: fails.append(f"{name}: has react.production")
    print(f"  OK {name}  source={p.get('avatarSource')}  label={p.get('avatarSourceLabel','')}")

# landing / index (landing.html is hand-authored, may use inline styles)
for fname in ["index.html"]:
    path = os.path.join(ARTIFACTS, fname)
    if not os.path.exists(path):
        fails.append(f"{fname} missing")
        continue
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if "tailwind.css" not in raw: fails.append(f"{fname}: missing tailwind.css")
    if "tailwindcss.js" in raw: fails.append(f"{fname}: has tailwindcss.js")
    print(f"  OK {fname}")
# landing.html: only verify no stale references
lp = os.path.join(ARTIFACTS, "landing.html")
if os.path.exists(lp):
    with open(lp, encoding="utf-8") as f:
        lraw = f.read()
    if "tailwindcss.js" in lraw: fails.append("landing.html: has tailwindcss.js")
    print(f"  OK landing.html (standalone, no stale references)")
else:
    fails.append("landing.html missing")

# static assets
for p in ["static/profile-app.js","static/tailwind.css","static/design-tokens.css","sw.js","vendor/preact-compat.production.min.js"]:
    fp = os.path.join(ARTIFACTS, p)
    if not os.path.exists(fp): fails.append(f"Missing asset: {p}")
    else: print(f"  OK {p}")

# stellar_home_data.json
shd = os.path.join(ARTIFACTS, "stellar_home_data.json")
if os.path.exists(shd):
    with open(shd, encoding="utf-8") as f:
        shd_data = json.load(f)
    n = len(shd_data.get("nodes", []))
    if n != 523: fails.append(f"stellar_home_data: expected 523 nodes, got {n}")
    print(f"  OK stellar_home_data.json ({n} nodes)")
else:
    fails.append("stellar_home_data.json missing")

# multi person view
multi = os.path.join(ARTIFACTS, "多人物合并视图_a5a979d7.html")
if os.path.exists(multi):
    with open(multi, encoding="utf-8") as f:
        mraw = f.read()
    if "tailwind.css" not in mraw: fails.append("multi-view: missing tailwind.css")
    if "tailwindcss.js" in mraw: fails.append("multi-view: has tailwindcss.js")
    print("  OK multi-view")
else:
    fails.append("multi-view missing")

if fails:
    print(f"\nFAILED ({len(fails)}):")
    for f in fails:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"\nALL CHECKS PASSED")

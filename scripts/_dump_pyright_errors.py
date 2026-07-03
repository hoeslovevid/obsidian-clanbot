import json
import os
import sys

path = os.path.join(os.environ["TEMP"], "pyright2.json")
with open(path, encoding="utf-8-sig") as f:
    d = json.load(f)

targets = sys.argv[1:] or [
    "views/_core.py",
    "core/music_player.py",
    "commands/moderation/purge.py",
]
out_path = os.path.join(os.path.dirname(__file__), "pyright_errors.txt")
with open(out_path, "w", encoding="utf-8") as out:
    for target in targets:
        errs = [
            x
            for x in d["generalDiagnostics"]
            if x.get("severity") == "error" and x["file"].replace("\\", "/").endswith(target)
        ]
        out.write(f"FILE {target} {len(errs)}\n")
        for e in errs:
            line = e["range"]["start"]["line"] + 1
            msg = e["message"].encode("ascii", "replace").decode("ascii")
            out.write(f"  L{line}: [{e.get('rule')}] {msg[:140]}\n")
        out.write("\n")
print(f"Wrote {out_path}")

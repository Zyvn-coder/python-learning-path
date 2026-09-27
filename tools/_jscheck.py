# -*- coding: utf-8 -*-
"""从产物中抽出内联 JS，交给 node --check 做语法校验（对应验收单第 7 条坑）。

用法：python tools/_jscheck.py   （需要 PATH 里有 node，或用 NODE_PATH 指定）
"""
import json, os, re, shutil, subprocess, traceback
from pathlib import Path

B = Path(__file__).resolve().parent
SRC = B.parent / "python-学习工作台.html"
NODE = os.environ.get("NODE_PATH_BIN") or shutil.which("node") or "node"

res = {}
try:
    html = SRC.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    res["script_blocks"] = len(scripts)
    js = "\n".join(scripts)
    res["js_chars"] = len(js)
    res["has_stray_comment_end"] = "*/" in js.split("const COURSE =")[0][-200:]
    res["placeholder_left"] = "__COURSE_DATA__" in html
    jsfile = B / "_app.js"
    jsfile.write_text(js, encoding="utf-8")

    r = subprocess.run(
        [NODE, "--check", str(jsfile)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    res["node_exit"] = r.returncode
    res["node_err"] = (r.stderr or "").strip()[:1500]
    res["syntax_ok"] = r.returncode == 0
    # 顺带确认 COURSE 真的被注入了
    res["course_assigned"] = bool(re.search(r"const COURSE = \{\"stages\"", html))
except Exception:
    res["fatal"] = traceback.format_exc()

(B / "_jscheck.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

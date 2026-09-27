# -*- coding: utf-8 -*-
"""单独对每个场景的注入脚本做语法检查。

场景脚本是拼进 <script> 里的，一旦有语法错误整块都不会执行，
表现就是「探针一声不响」——比报错还难查。先在这里拦掉。

用法：python tools/_probecheck.py   （需要 PATH 里有 node）
"""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

B = Path(__file__).resolve().parent
NODE = os.environ.get("NODE_PATH_BIN") or shutil.which("node") or "node"

spec = importlib.util.spec_from_file_location("br", B / "_browser.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)

out = {}
for name, (_frag, _w, _h, ui) in br.SCEN.items():
    js = br.BASE + ui + br.TAIL
    p = B / ("_probe_%s.js" % name)
    p.write_text(js, encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(p)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out[name] = {"exit": r.returncode, "chars": len(js),
                 "err": (r.stderr or "").strip()[:600]}

(B / "_probecheck.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                    encoding="utf-8")

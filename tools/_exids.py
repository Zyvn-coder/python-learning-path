# -*- coding: utf-8 -*-
"""列出每课真实存在的例题 id（排除「运行效果」块），供验收种子挑 id 用。

用法：python tools/_exids.py
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = os.path.join(ROOT, "python-学习工作台.html")
html = open(H, encoding="utf-8").read()

m = re.search(r"const COURSE\s*=\s*(\{.*?\});\s*\n", html, re.S)
if not m:
    print("没找到 COURSE 常量")
    raise SystemExit(1)
course = json.loads(m.group(1))

total = 0
for st in course["stages"]:
    items = list(st["lessons"]) + ([st["project"]] if st.get("project") else [])
    for it in items:
        body = it.get("html") or ""
        cards = re.findall(r'<details class="answer([^"]*)"', body)
        ids = []
        n = 0
        for cls in cards:
            eid = "ex-%s-%d" % (it["id"], n)
            n += 1
            if "out" in cls:
                continue
            ids.append(eid)
        if ids:
            total += len(ids)
            print("%-10s %-2s %-26s %d  %s" % (it["id"], it.get("no") or "-", it.get("title", "")[:24], len(ids), " ".join(ids)))
print("\n合计真实例题：", total)

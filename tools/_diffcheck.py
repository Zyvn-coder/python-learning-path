# -*- coding: utf-8 -*-
"""核验对内容源的改动：逐行 diff，并把每一处改动（含上下文）完整打印。

动 .md 的风险从来不是"改了几行"，而是**改到了不该改的行**：例题标题的增删会让
前端按文档序算出的例题编号整体平移，用户已存的自评与复习档期就会挂到别的题上。
所以这里的核心断言不是"必须是纯插入"，而是：

    禁区行（例题标题 / 章节标题 / 代码围栏）既没被删除，也没被改写。

结构等价转换（比如把"分号句"拆成有序列表）是允许的——它不动禁区，也就不动编号。

用法：改 .md 之前把 4 份文件备份到 tools/_md_backup/，改完直接跑这个脚本。
"""
import io
import os
import re
import difflib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BK = os.path.join(ROOT, 'tools', '_md_backup')
OUT = io.open(os.path.join(ROOT, 'tools', '_diffcheck.txt'), 'w', encoding='utf-8')


def P(*a):
    print(*a)
    print(*a, file=OUT)


# 禁区：这些行被删/被改，前端的编号或分节就会平移
GUARD = [
    (re.compile(r'^\*\*例题'), '例题标题'),
    (re.compile(r'^#{2,4} '), '章节标题'),
    (re.compile(r'^\s*```'), '代码围栏'),
]

FILES = ['01-入门基础.md', '02-核心进阶.md', '03-高级应用.md', '04-方向拓展与毕业项目.md']

bad = 0
for fn in FILES:
    a = io.open(os.path.join(BK, fn), encoding='utf-8').read().split('\n')
    b = io.open(os.path.join(ROOT, fn), encoding='utf-8').read().split('\n')
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ins = dele = rep = 0
    blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'insert':
            ins += j2 - j1
        elif tag == 'delete':
            dele += i2 - i1
        else:
            rep += max(i2 - i1, j2 - j1)
        blocks.append((tag, i1, i2, j1, j2))

    P("%-22s 原 %d 行 → 新 %d 行 (%+d)  |  插入 %d, 删除 %d, 改写 %d  |  改动块 %d 处"
      % (fn, len(a), len(b), len(b) - len(a), ins, dele, rep, len(blocks)))

    for tag, i1, i2, j1, j2 in blocks:
        P("    ── %s @ 旧第 %d 行 / 新第 %d 行 ──" % (tag, i1 + 1, j1 + 1))
        if tag == 'insert':
            if i1 - 1 >= 0:
                P("      ·  " + a[i1 - 1])          # 上下文：插在这一行之后
        else:
            for ln in a[i1:i2]:
                P("      -  " + ln)
        for ln in b[j1:j2]:
            P("      +  " + ln)
        # 禁区检查：被删除/被改写的旧侧行不允许命中
        if tag in ('delete', 'replace'):
            for idx in range(i1, i2):
                for rx, name in GUARD:
                    if rx.match(a[idx]):
                        P("      !! 禁区行被改动（%s）：%s" % (name, a[idx]))
                        bad += 1

    if not blocks:
        P("    （无改动）")
    P()

P("结论：", "禁区行（例题标题 / 章节标题 / 代码围栏）均未被删改，编号不会平移"
   if bad == 0 else "存在禁区改动 %d 处，必须人工复核" % bad)
OUT.close()

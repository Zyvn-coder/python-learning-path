# -*- coding: utf-8 -*-
"""例题「题面完整度」度量 —— 配套模板里的 BARE_N 质量闸门。

口径（按**答案块**算题，不按标题算）：
  * 在一个 `### 💡 例题` 区内，`**例题 N：标题**` 开一道题；
  * 标题到第一个代码围栏之间的文字 = 「题面正文」；
  * 标题之下、下一个标题之前的每个 ```python 块 = 一道答案 → 一道题。

为什么按答案块而不是按标题：`s2-l12` 一个标题挂两个答案（utils.py + main.py），
按标题算会少一道（44 而不是 45）。

历史：2026-09-21 之前，阶段二 13/16、阶段三 13/13 的例题只有标题没有题面，
抽题自测抽到它们等于只印一个标题。补齐后本脚本应输出「只有标题 = 0」。
"""
import io, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [('阶段一', '01-入门基础.md'), ('阶段二', '02-核心进阶.md'),
         ('阶段三', '03-高级应用.md'), ('阶段四', '04-方向拓展与毕业项目.md')]
OUT = io.open(os.path.join(ROOT, 'tools', '_exbriefs.txt'), 'w', encoding='utf-8')


def P(*a):
    print(*a)
    print(*a, file=OUT)


TITLE = re.compile(r'^\*\*(例题\s*\d*\s*[：:]\s*)(.+?)\*\*\s*$')


def scan(fn):
    lines = io.open(os.path.join(ROOT, fn), encoding='utf-8').read().split('\n')
    in_ex = False
    in_fence = False
    cur = None
    items = []
    for ln in lines:
        s = ln.strip()
        if s.startswith('### '):
            if in_fence:
                continue
            in_ex = '例题' in s
            continue
        if not in_ex:
            continue
        if s.startswith('```'):
            if not in_fence:
                in_fence = True
                lang = s.strip('`').strip()
                if cur is not None and cur['seen_fence']:
                    pass
                if cur is not None and lang.startswith('python'):
                    cur['py'] += 1
                if cur is not None:
                    cur['seen_fence'] = True
            else:
                in_fence = False
            continue
        if in_fence:
            continue
        m = TITLE.match(s)
        if m:
            if cur:
                items.append(cur)
            cur = {'title': m.group(2).strip(), 'prose': '', 'py': 0, 'seen_fence': False}
            continue
        if cur is not None and not cur['seen_fence']:
            cur['prose'] += s + ' '
    if cur:
        items.append(cur)
    return items


agg = {}
for stage, fn in FILES:
    items = scan(fn)
    tot = sum(i['py'] for i in items)
    good = sum(i['py'] for i in items if len(i['prose'].strip()) >= 4)
    agg[stage] = (tot, good, tot - good, len(items))
    P("%s  题数=%d  有题面=%d  只有标题=%d  (标题数=%d)" % (stage, tot, good, tot - good, len(items)))

P()
P("合计  题数=%d  有题面=%d  只有标题=%d" % (
    sum(v[0] for v in agg.values()), sum(v[1] for v in agg.values()), sum(v[2] for v in agg.values())))
OUT.close()

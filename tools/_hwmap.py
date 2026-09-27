# -*- coding: utf-8 -*-
"""列出每个页面的 hw-list 计数（= 真正可勾的作业项），定位 142 的构成。

用法：python tools/_hwmap.py
"""
import io, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(io.open(os.path.join(ROOT, 'tools', '_content.json'), encoding='utf-8'))

lines, total = [], 0
for st in d['stages']:
    sub = 0
    for it in st['lessons']:
        n = it['counts'].get('hw', 0)
        raw_li = len(re.findall(r'<li', it['html']))
        sub += n
        lines.append('  %-16s %-10s hw=%-3d raw_li=%-3d  %s'
                     % (it['id'], it['kind'], n, raw_li, it['title'][:24]))
    p = st.get('project')
    pn = p['counts'].get('hw', 0) if p else 0
    praw = len(re.findall(r'<li', p['html'])) if p else 0
    sub += pn
    if p:
        lines.append('  %-16s %-10s hw=%-3d raw_li=%-3d  %s'
                     % (p['id'], p['kind'], pn, praw, p['title'][:24]))
    total += sub
    lines.append('  --- %s 小计 hw=%d ---' % (st['id'], sub))

lines.append('')
lines.append('TOTAL hw-list items = %d' % total)

out = io.open(os.path.join(ROOT, '.workbuddy', 'build', '_hwmap.txt'), 'w', encoding='utf-8')
out.write('\n'.join(lines) + '\n')
out.close()

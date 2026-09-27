"""临时冒烟：只看「选方向页就地展开」跑不跑得起来，不做断言。
跑法：python _smoke_pick.py"""
import json, subprocess, sys, uuid
from pathlib import Path

B = Path(__file__).resolve().parent
SRC = B.parent.parent / "python-学习工作台.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

UI = r"""
await P.ready('.pick-grid');
await P.wait(400);
var body = P.ob('#lessonBody');
P.p('BODY_KIDS', P.all(':scope > *', body).map(function(e){
  return e.tagName.toLowerCase()+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/\s+/)[0]:'')
}).join(' '));
P.p('IT_HTML_TOP', (function(){
  var d=document.createElement('div');
  d.innerHTML=__bench.items().filter(function(x){return x.id==='s4-dira'})[0].html;
  return P.all(':scope > *', d).map(function(e){
    return e.tagName.toLowerCase()+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/\s+/)[0]:'')
  }).join(' ');
})());
P.p('IT_HL_N', (function(){
  var d=document.createElement('div');
  d.innerHTML=__bench.items().filter(function(x){return x.id==='s4-dira'})[0].html;
  return P.all('.hl', d).length;
})());
var items = P.all('.pick-item', body);
P.p('ITEMS', items.length);
P.p('X_MOUNTS', P.all('.pick-x', body).length);
P.p('MORE', P.all('.pick-more', body).length);
var c0 = P.ob('.pick-card', items[0]);
P.p('ARIA0_BEFORE', c0.getAttribute('aria-expanded'));
P.p('MOUNT_HIDDEN', P.ob('.pick-x', items[0]).hidden);
P.click(c0);
await P.wait(420);
P.p('OPEN0', items[0].dataset.open);
P.p('ARIA0_AFTER', c0.getAttribute('aria-expanded'));
P.p('FIGURE', P.ob('.pick-x', items[0]).closest('.pick-item')===items[0]?'in':'out');
P.p('X_KIDS', P.all(':scope > *', P.ob('.pick-x', items[0])).map(function(e){
  return e.tagName.toLowerCase()+(e.className&&typeof e.className==='string'?'.'+e.className.trim().split(/\s+/)[0]:'')
}).join(' '));
P.p('H4_IN', P.all('.pick-x h4.mini-title', items[0]).map(function(h){return h.textContent}).join('|'));
P.p('HL_IN', P.all('.pick-x .hl', items[0]).length);
P.p('TICKS_IN', P.all('.pick-x .hw-tick', items[0]).length);
P.p('STUCK_IN', P.all('.pick-x .hw-stuck', items[0]).length);
P.p('LI_IDS', P.all('.pick-x ol.hw-list > li', items[0]).map(function(l){return l.id}).join(','));
P.p('PROG', (P.ob('.pick-x #pxProg', items[0])||{}).textContent||'');
P.p('OTHERS_HIDDEN', P.all('.pick-x', body).filter(function(x){return !x.hidden}).length);
P.p('OVF', P.ovf());
P.p('SMALL', P.small());
P.p('COLS', P.cs(P.ob('.pick-grid'),'gridTemplateColumns').split(' ').length);
// 勾一下展开区里的第一项
var box = P.ob('.pick-x .hw-tick input', items[0]);
if (box) { box.checked = true; box.dispatchEvent(new Event('change',{bubbles:true})); }
await P.wait(300);
P.p('STATE_AFTER', P.ob('.pick-x ol.hw-list > li', items[0]).dataset.state);
P.p('PROG_AFTER', (P.ob('.pick-x #pxProg', items[0])||{}).textContent||'');
P.p('STORED', JSON.stringify(__bench.getState().hw));
// 口令跳转
P.key('Escape');
await P.wait(200);
__bench.pickDir('c');
await P.wait(900);
P.p('JUMP_HASH', location.hash);
P.p('JUMP_OPEN', P.all('.pick-item[data-open="1"]', P.ob('#lessonBody')).length);
P.p('JUMP_OPEN_DIR', P.all('.pick-item[data-open="1"]', P.ob('#lessonBody')).map(function(x){return x.dataset.dir}).join(','));
P.p('PENDING', String(__bench.getPendingDir()));
P.p('__DONE',1);
"""

BASE = (B / "_browser.py").read_text(encoding="utf-8")
i = BASE.find("BASE = r\"\"\"")
j = BASE.find("TAIL = r\"\"\"")
base = BASE[i + len('BASE = r"""'):j].rstrip()[:-3]
k = BASE.find("TAIL = r\"\"\"")
tail = BASE[k + len('TAIL = r"""'):]
tail = tail[:tail.find('"""')]

tag = uuid.uuid4().hex[:6]
html = SRC.read_text(encoding="utf-8")
html = html.replace("</body>", "<script>" + base + UI + tail + "</script></body>", 1)
page = B / ("_smoke_pick-%s.html" % tag)
page.write_text(html, encoding="utf-8")
prof = B / ("_smp_%s" % tag)

cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
       "--no-default-browser-check", "--hide-scrollbars", "--disable-smooth-scrolling",
       "--force-device-scale-factor=1", "--allow-file-access-from-files",
       "--user-data-dir=" + str(prof), "--window-size=1440,1050",
       "--virtual-time-budget=150000", "--dump-dom",
       page.as_uri() + "#/s4-怎么选方向"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
dom = r.stdout or ""
import re
m = re.search(r"PROBE_BEGIN([A-Za-z0-9+/=]+)PROBE_END", dom)
if not m:
    print("NO PROBE", r.stderr[-800:]); sys.exit(1)
import base64
data = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
for k2, v in data.items():
    if k2 in ("__ERRS",):
        print(k2, "=", v)
    else:
        print(k2, "=", json.dumps(v, ensure_ascii=False))

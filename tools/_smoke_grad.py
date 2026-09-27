"""冒烟：「该毕业了」卡在三种情况下分别长什么样。
跑法：python _smoke_grad.py"""
import json, subprocess, sys, uuid, re, base64, datetime
from pathlib import Path

B = Path(__file__).resolve().parent
SRC = B.parent.parent / "python-学习工作台.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

UI = r"""
await P.ready('.today');
await P.wait(500);
var p = __bench.todayPlan();
var g = __bench.gradProgress();
P.p('GRAD_SHOW', g.show?'1':'0');
P.p('GRAD_N', g.n); P.p('GRAD_T', g.t); P.p('GRAD_FULL', g.full?'1':'0');
P.p('GRAD_STARTED', g.started?'1':'0');
P.p('GRAD_COURSE_DONE', g.courseDone?'1':'0');
P.p('GRAD_HREF', '#'+g.id);
P.p('CARD_KS', P.all('.today-card').map(function(c){return c.dataset.k}).join(','));
var gc = P.ob('.today-card[data-k="grad"]');
P.p('GCARD', gc?'present':'absent');
if (gc) {
  P.p('GC_HREF', gc.getAttribute('href'));
  P.p('GC_ON', gc.dataset.on);
  P.p('GC_DONE', gc.dataset.done||'');
  P.p('GC_N', gc.querySelector('.tc-n').textContent);
  P.p('GC_L', gc.querySelector('.tc-l').textContent);
  P.p('GC_NOTE', gc.querySelector('.tc-note').textContent);
  P.p('GC_GO_DISPLAY', P.cs(gc.querySelector('.tc-go'),'display'));
}
P.p('LEAD', p.lead);
P.p('PLAN_N', p.items.length);
P.p('OVF', P.ovf());
P.p('SMALL', P.small());
P.p('CT_SWEEP', P.contrastSweep());
P.p('NO_HSCROLL', document.documentElement.scrollWidth<=document.documentElement.clientWidth+1?'yes':'NO-BAD');
P.blur(); P.key('d'); await P.wait(400);
P.p('DARK_CT_SWEEP', P.contrastSweep());
P.p('DARK_GC_N', P.contrast('.today-card[data-k="grad"] .tc-n'));
P.p('DARK_GC_L', P.contrast('.today-card[data-k="grad"] .tc-l'));
P.p('DARK_GC_NOTE', P.contrast('.today-card[data-k="grad"] .tc-note'));
P.p('__DONE',1);
"""

txt = (B / "_browser.py").read_text(encoding="utf-8")
base = txt[txt.find('BASE = r"""') + len('BASE = r"""'): txt.find('TAIL = r"""')].rstrip()[:-3]
tl = txt[txt.find('TAIL = r"""') + len('TAIL = r"""'):]
tail = tl[:tl.find('"""')]


def seed(**over):
    s = {"done": {}, "hw": {}, "miles": {}, "ex": {}, "rev": {},
         "time": {}, "theme": None, "last": None}
    s.update(over)
    return s


CASES = {
    # 刚学第 3 课：不该出现这张卡
    "early": seed(done={"s1-l1": 1, "s1-l2": 1}),
    # 全课程走完、毕业项目一项没勾：该出现，且是"该做毕业项目了"
    "coursedone": seed(done={**{("s1-l%d" % i): 1 for i in range(1, 9)},
                             **{("s2-l%d" % i): 1 for i in range(9, 17)},
                             **{("s3-l%d" % i): 1 for i in range(17, 25)},
                             "s1-p": 1, "s2-p": 1, "s3-p": 1,
                             "s4-怎么选方向": 1,
                             "s4-dira": 1, "s4-dirb": 1, "s4-dirc": 1,
                             "s4-dird": 1, "s4-dire": 1},
                      hw={}),
    # 动手做了 2/9 项，有一项卡住
    "started": seed(done={"s4-dira": 1},
                    hw={"s4-毕业项目-三选一:0": 1, "s4-毕业项目-三选一:1": -1},
                    rev={"s4-毕业项目-三选一:1": {"l": 0, "due": "2026-09-27", "n": 0}}),
    # 三组全达成
    "full": seed(hw={("s4-毕业项目-三选一:%d" % i): 1 for i in range(9)}),
    # 只有一组的 3 项做完（另两组空着）：不该算达成
    "onegroup": seed(hw={("s4-毕业项目-三选一:%d" % i): 1 for i in range(3)}),
}

out = {}
for name, sd in CASES.items():
    tag = uuid.uuid4().hex[:6]
    html = SRC.read_text(encoding="utf-8")
    pre = ('<script>try{localStorage.setItem("py-path-v3",%s)}catch(e){}</script>'
           % json.dumps(json.dumps(sd, ensure_ascii=False)))
    html = html.replace("</head>", pre + "</head>", 1)
    html = html.replace("</body>", "<script>" + base + UI + tail + "</script></body>", 1)
    page = B / ("_smg_%s-%s.html" % (name, tag))
    page.write_text(html, encoding="utf-8")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
           "--disable-smooth-scrolling", "--force-device-scale-factor=1",
           "--allow-file-access-from-files", "--user-data-dir=" + str(B / ("_sgp_%s" % tag)),
           "--window-size=1440,1100", "--virtual-time-budget=150000", "--dump-dom",
           page.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"PROBE_BEGIN([A-Za-z0-9+/=]+)PROBE_END", r.stdout or "")
    if not m:
        print(name, "NO PROBE"); continue
    out[name] = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))

for name, d in out.items():
    print("=" * 8, name)
    for k in ['GRAD_SHOW','GRAD_N','GRAD_T','GRAD_FULL','GRAD_STARTED','GRAD_COURSE_DONE',
              'CARD_KS','GC_N','GC_L','GC_NOTE','GC_HREF','GC_DONE','GC_GO_DISPLAY',
              'PLAN_N','LEAD','OVF','SMALL','NO_HSCROLL','__ERRS_N',
              'DARK_GC_N','DARK_GC_L','DARK_GC_NOTE','DARK_CT_SWEEP','CT_SWEEP']:
        print("  ", k, "=", json.dumps(d.get(k), ensure_ascii=False))

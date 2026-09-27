# -*- coding: utf-8 -*-
"""截图取证。滚动在无头下不可靠，改用负 margin 把目标顶到首屏。

用法（在仓库根目录下）：
    python tools/_shots.py                 # 全部
    python tools/_shots.py 01-home-light   # 只拍某几张

支持两件额外的事：
  seed —— 在应用启动前预写 localStorage，让错题本/热力图有真实数据可拍；
  act  —— 就绪后执行一段 JS，用来打开帮助面板之类的浮层。
"""
import json, os, struct, subprocess, sys, uuid
from pathlib import Path

B = Path(__file__).resolve().parent
SRC = B.parent / "python-学习工作台.html"
CHROME = os.environ.get("CHROME_PATH") or next(
    (p for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ) if os.path.exists(p)),
    "chrome",
)

# 造一批像样的历史数据：近 60 天里断断续续的学习时长
SEED_TIME = {}
import datetime as _dt
_base = _dt.date.today()          # 跟着今天走，热力图才不会停在昨天
_pat = [0, 45, 70, 25, 0, 0, 90, 120, 60, 0, 35, 80, 100, 0, 0,
        55, 130, 95, 40, 0, 0, 110, 65, 0, 85, 150, 75, 30, 0, 0,
        125, 90, 45, 60, 0, 0, 140, 100, 70, 0, 55, 35, 0, 0,
        160, 120, 85, 50, 0, 0, 95, 145, 105, 65, 0, 0, 130, 88, 42, 60]
for i, mins in enumerate(_pat):
    if mins:
        d = _base - _dt.timedelta(days=(len(_pat) - 1 - i))
        SEED_TIME[d.isoformat()] = mins * 60
SEED_TIME[_base.isoformat()] = 71 * 60


def _d(n):
    return (_base + _dt.timedelta(days=n)).isoformat()


SEED = {
    # 课号与 id 的对应：1-8 在 s1，9-16 在 s2，17-24 在 s3。
    # 写错前缀就成了"幽灵 id"——界面上静默不计数，截图里的数字会对不上真值。
    "done": {"s1-l1": 1, "s1-l2": 1, "s1-l3": 1, "s1-l4": 1, "s1-l5": 1, "s2-l9": 1},
    # 1＝已完成；-1＝卡住（会进错题本与复习档期）；缺省＝还没动
    "hw": {
        "s1-l1:0": 1, "s1-l2:0": 1, "s2-l9:0": 1,
        "s1-l2:1": -1, "s2-l9:1": -1, "s1-l3:0": -1,
    },
    "miles": {"0": 1},
    "ex": {
        "ex-s1-l3-1": -1, "ex-s1-l5-0": -1, "ex-s1-l8-0": -1,
        "ex-s2-l11-1": -1, "ex-s2-l15-0": -1, "ex-s3-l17-0": -1,
        "ex-s1-l2-0": 1, "ex-s1-l7-1": 1, "ex-s2-l14-0": 1,
    },
    # 六道错题分别压在不同档位：四道到期待复习，两道排在后面
    "rev": {
        "ex-s1-l3-1": {"l": 3, "due": _d(-1), "n": 3},    # 欠了 1 天
        "ex-s1-l5-0": {"l": 1, "due": _d(0), "n": 1},     # 今天
        "ex-s1-l8-0": {"l": 2, "due": _d(0), "n": 2},     # 今天
        "ex-s2-l11-1": {"l": 0, "due": _d(0), "n": 1},    # 今天（还没过第一关）
        "ex-s2-l15-0": {"l": 2, "due": _d(5), "n": 3},    # 5 天后
        "ex-s3-l17-0": {"l": 4, "due": _d(20), "n": 4},   # 21 天那一关
        # 卡住的作业和例题共用同一张档期表
        "s1-l2:1": {"l": 1, "due": _d(0), "n": 2},        # 今天
        "s2-l9:1": {"l": 2, "due": _d(-2), "n": 3},       # 欠了 2 天
        "s1-l3:0": {"l": 0, "due": _d(4), "n": 1},        # 4 天后
    },
    "time": SEED_TIME,
    "theme": None,
    "last": "s3-l17",
}


def _quiz_shot_seed():
    """自测截图专用：把 s1 的例题全标成「已掌握」。

    这样抽出来的一定带着「你标过『会了』」的徽章——自测的核心卖点就是
    回头检验这些题，截图里看不到它就白拍了。另外三道留作错题，
    免得「该复习」那一栏在别的截图里变空。

    例题 id 要写真值：s1-l1 的第 0 个块是「运行效果」，占号但不是题，
    所以那节课是 -1 / -2，其余课是 -0 / -1。
    """
    s = json.loads(json.dumps(SEED))
    for l in range(1, 9):
        base = "ex-s1-l%d-" % l
        for k in (["1", "2"] if l == 1 else ["0", "1"]):
            s["ex"][base + k] = 1
    for k in ("ex-s1-l3-1", "ex-s1-l5-0", "ex-s1-l8-0"):
        s["ex"][k] = -1
    return s


SEED_QUIZ = _quiz_shot_seed()


def _grad_shot_seed():
    """毕业项目截图专用：三个项目各留一种状态。

    刻意让 data-full 的两种取值**同页出现**——① 2/3 未达成、② 只标了「卡住」、
    ③ 3/3 已达成。全填满或全空的话，把 data-full 写死成单个值也能蒙混过关。
    ② 里那一条「卡住」同时让页头的「卡住」计数非零，一张图验两件事。

    验收标准的 id 是 <页面 id>:<全局序号>——① 占 0-2、② 占 3-5、③ 占 6-8。
    """
    s = json.loads(json.dumps(SEED))
    s["hw"].update({
        "s4-毕业项目-三选一:0": 1,
        "s4-毕业项目-三选一:1": 1,
        "s4-毕业项目-三选一:3": -1,     # 卡住：进错题本，今天就该复习
        "s4-毕业项目-三选一:6": 1,
        "s4-毕业项目-三选一:7": 1,
        "s4-毕业项目-三选一:8": 1,
    })
    s["rev"]["s4-毕业项目-三选一:3"] = {"l": 0, "due": _d(0), "n": 0}
    s["last"] = "s4-毕业项目-三选一"
    return s


SEED_GRAD = _grad_shot_seed()


def _pick_shot_seed():
    """选方向页截图专用：把方向 A 的练习题铺成三种态。

    展开区里"勾过 / 卡住 / 没表态"同时出现，图上一眼就能看出
    「已做 x / n」的数是从哪儿来的、卡住那条为什么不打勾。
    id 形状与课时页一致：<方向页 id>:<本页第几项>。
    """
    s = json.loads(json.dumps(SEED))
    s["hw"].update({"s4-dira:0": 1, "s4-dira:1": -1})
    s["rev"]["s4-dira:1"] = {"l": 0, "due": _d(0), "n": 0}
    s["last"] = "s4-怎么选方向"
    return s


SEED_PICK = _pick_shot_seed()


def _gradplan_shot_seed(full):
    """「该毕业了」截图种子：课程走完 + 毕业项目做到某个程度。

    full=True 时把九项验收全勾上（三组各三），图上是「已达成」那版；
    否则只勾前一组的三项，图上是「进行中 · 还差 6 项验收」。
    **只勾，不写死"第几题是什么"**——id 形状与课程页一致。
    """
    s = json.loads(json.dumps(SEED))
    for i in range(1, 9):
        s["done"]["s1-l%d" % i] = 1
    for i in range(9, 17):
        s["done"]["s2-l%d" % i] = 1
    for i in range(17, 25):
        s["done"]["s3-l%d" % i] = 1
    s["done"].update({"s1-p": 1, "s2-p": 1, "s3-p": 1})
    rng = range(9) if full else range(3)
    for i in rng:
        s["hw"]["s4-毕业项目-三选一:%d" % i] = 1
    s["last"] = "s4-毕业项目-三选一"
    return s


SEED_GRADPLAN = _gradplan_shot_seed(False)
SEED_GRADPLAN_FULL = _gradplan_shot_seed(True)

SHOTS = {
    "01-home-light": ("", "light", None, 1440, 940, None, None),
    "02-home-dark": ("", "dark", None, 1440, 940, None, None),
    "03-lesson-tools": ("#/s1-l6", "light", ".ex-title", 1440, 940, None, None),
    "04-lesson-answer": ("#/s3-l17", "light", "details.answer", 1440, 940, None, None),
    "05-lesson-dark": ("#/s3-l17", "dark", ".hl", 1440, 940, None, None),
    "06-mobile-light": ("", "light", None, 430, 940, None, None),
    "07-home-readme": ("", "light", ".doc h2", 1440, 940, None, None),
    # 自评后的参考答案（琥珀色"待复习"态）——走真实点击，不手改 DOM
    "08-answer-marked": ("#/s3-l17", "light", "details.answer", 1440, 940, None, "MARKBAD"),
    # 错题本（今天该复习）
    "09-review-todo": ("#/review", "light", ".tabs", 1440, 940, SEED, None),
    # 错题本（全部未自评例题）
    "10-review-fresh": ("#/review", "light", None, 1440, 940, SEED, "TABFRESH"),
    # 学习记录（时长统计 + 热力图 + 复习阶梯）
    "11-records": ("#/records", "light", ".rec-grid", 1440, 1100, SEED, None),
    # 学习记录（深色 + 热力图细节）
    "12-records-dark": ("#/records", "dark", ".hm-card", 1440, 1100, SEED, None),
    # 帮助面板
    "13-help": ("", "light", None, 1440, 940, None, "HELP"),
    # 窄屏错题本
    "14-review-mobile": ("#/review", "light", ".tabs", 430, 940, SEED, None),
    # 第 1 课的例题——参考答案一进来就展开；无语言代码块是「运行效果」，不算一道题
    "15-lesson-answers": ("#/s1-l1", "light", ".ex-title", 1440, 1100, None, None),
    # 间隔复习：阶梯分布 + 开复习按钮
    "16-review-ladder": ("#/review", "light", ".rv-ladder", 1440, 1040, SEED, None),
    # 间隔复习：真的开一轮，拍会话栏 + 自动定位高亮的那道题
    "17-review-session": ("#/review", "light", "details.answer.is-flash", 1440, 1040, SEED, "SESSION"),
    # 窄屏的阶梯与开复习
    "18-review-ladder-mobile": ("#/review", "light", ".rv-ladder", 430, 1040, SEED, None),
    # 作业三态：已完成 / 卡住 / 未做，同一页上三种样子
    "19-hw-stuck": ("#/s1-l2", "light", "ol.hw-list", 1440, 1040, SEED, None),
    # 错题本里例题与作业混排，各带来源徽章
    "20-review-mixed": ("#/review", "light", ".rv-list", 1440, 1040, SEED, None),
    # 抽题自测：设置页（范围/题量/题源 + 「会了却没复核」的真实道数）
    "21-quiz-setup": ("#/quiz", "light", ".qz-setup", 1440, 1040, SEED_QUIZ, None),
    # 抽题自测：出题时答案必须是遮住的
    "22-quiz-question": ("#/quiz", "light", ".qz-card", 1440, 1040, SEED_QUIZ, "QUIZSTART"),
    # 抽题自测：揭示答案后才出现自评那一排
    "23-quiz-answer": ("#/quiz", "light", ".qz-ans", 1440, 1040, SEED_QUIZ, "QUIZREVEAL"),
    # 抽题自测：成绩单（答错/答对/跳过三种结局）
    "24-quiz-result": ("#/quiz", "light", ".qz-score", 1440, 1040, SEED_QUIZ, "QUIZRESULT"),
    # 抽题自测：窄屏
    "25-quiz-mobile": ("#/quiz", "light", ".qz-card", 430, 1040, SEED_QUIZ, "QUIZSTART"),
    # 阶段三的例题——这 13 道以前标题下面直接就是答案（无题面），2026-09-21 补齐
    "26-lesson-s3-brief": ("#/s3-l20", "light", ".ex-title", 1440, 1040, None, None),
    # 抽题自测抽到阶段三：题面完整，不再是一个光秃秃的标题
    "27-quiz-s3-question": ("#/quiz", "light", ".qz-card", 1440, 1040, SEED_QUIZ, "QUIZS3"),

    # 今日计划：空态（一台刚打开的工作台）与真实数据态各拍一张。
    # 空态那张是刻意的——四张卡全 off 才是这个组件最容易翻车的样子。
    "28-plan-empty": ("", "light", ".hero-stats", 1440, 1040, None, None),
    "29-plan-active": ("", "light", ".hero-stats", 1440, 1040, SEED, None),
    "30-plan-mobile": ("", "light", ".today", 430, 1040, SEED, None),

    # 阶段四闭环：毕业项目三选一（三组验收标准各自记账）与「按目标选方向」的卡片
    "31-grad-project": ("#/s4-毕业项目-三选一", "light", ".grad-pill", 1440, 1100, SEED_GRAD, None),
    "32-grad-done": ("#/s4-毕业项目-三选一", "dark", ".grad-pill", 1440, 1100, SEED_GRAD, None),
    "33-grad-mobile": ("#/s4-毕业项目-三选一", "light", "ol.hw-list", 430, 1100, SEED_GRAD, None),
    "34-picker": ("#/s4-怎么选方向", "light", ".pick-grid", 1440, 1000, None, None),
    "35-picker-mobile": ("#/s4-怎么选方向", "light", ".pick-grid", 430, 1000, None, None),
    # 就地展开：宽屏看"只把本行撑高、邻居不动"，窄屏看"单列长高"，
    # 深色那张只为把代码块与"已做 x / n"的对比度留成图证
    "36-picker-open": ("#/s4-怎么选方向", "light", ".pick-item[data-open='1']",
                       1440, 1180, SEED_PICK, "PICKOPEN"),
    "37-picker-open-mobile": ("#/s4-怎么选方向", "light", ".pick-x",
                              430, 1400, SEED_PICK, "PICKOPEN"),
    "38-picker-open-dark": ("#/s4-怎么选方向", "dark", ".pick-x-h",
                            1440, 1180, SEED_PICK, "PICKOPEN"),

    # 「该毕业了」：同一张卡三种态里的两种（未开工那版是"卡压根不在"，
    # 由 today 场景的负向断言守着，截图拍不出"少了一张卡"）。
    "39-gradplan": ("", "light", ".today", 1440, 1040, SEED_GRADPLAN, None),
    "40-gradplan-full": ("", "light", ".today", 1440, 1040, SEED_GRADPLAN_FULL, None),
    "41-gradplan-dark": ("", "dark", ".today", 1440, 1040, SEED_GRADPLAN, None),
}

TMPL = """<script>
(function(){
  var TH="__TH__", SEL="__SEL__", ACT="__ACT__", SEEDJ=__SEED__;
  var n=0, t=setInterval(function(){
    n++;
    if(document.querySelector('.hero, .lesson-body')){
      clearInterval(t);
      setTimeout(run, 160);
    }
    if(n>200){ clearInterval(t); setTimeout(run, 160); }
  }, 60);

  function run(){
    // 打字机在无头下被节流，直接补齐内容再截图
    var term=document.querySelector('#heroTerm');
    if(term && !term.querySelector('span')){
      term.innerHTML = '<div class="ln"><span class="tk-c"># 你的 Python 学习工作台</span></div>'
        +'<div class="ln"><span class="tk-k">print</span><span class="tk-p">(</span><span class="tk-s">"Hello, World!"</span><span class="tk-p">)</span></div>'
        +'<div class="ln"><span class="tk-n">goal</span><span class="tk-p"> = </span><span class="tk-s">"24 节课后写出能跑的程序"</span></div>'
        +'<div class="ln"><span class="tk-k">for</span><span class="tk-n"> week</span><span class="tk-k"> in</span><span class="tk-b">range</span><span class="tk-p">(1, 25):</span></div>'
        +'<div class="ln"><span class="tk-p">    </span><span class="tk-b">print</span><span class="tk-p">(</span><span class="tk-s">f"第 {week} 周 · 慢慢来，比较快"</span><span class="tk-p">)</span></div>'
        +'<div class="ln"><span class="tk-n">progress</span><span class="tk-p"> → </span><span class="tk-s">"持续 > 强度"</span><span class="caret"></span></div>';
    }
    var ans=document.querySelector('details.answer');
    if(ACT==='MARKBAD'){
      // 走真实点击，别手改 DOM——不然拍到的不是应用真的会呈现的样子
      if(ans){
        ans.open=true;
        var mb=ans.querySelector('.rate-btn[data-m="-1"]');
        if(mb) mb.click();
      }
    }
    // 真的开一轮复习：拍会话栏 + 自动定位高亮的那道题
    if(ACT==='SESSION'){
      // scrollIntoView 的平滑滚动在无头下不可靠，先把它变成空操作，
      // 定位交给下面的负 margin，和别的截图用同一套办法
      Element.prototype.scrollIntoView = function(){};
      var sb=document.querySelector('#rvStart');
      if(sb) sb.click();
    }
    // 拍"全部未自评"这一页
    if(ACT==='TABFRESH'){
      var tb=document.querySelector('.tab[data-tab="fresh"]');
      if(tb) tb.click();
    }
    // 自测：真开一组，拍"答案还没揭开"的样子
    if(ACT==='QUIZSTART'){
      window.__readyDelay = 700;
      __bench.setQzSetup({scope:'s1',size:5,source:'ex'});
      __bench.startQuiz();
    }
    // 自测：专抽阶段三。这 13 道以前标题下面直接就是答案，2026-09-21 补齐了
    // 任务描述——这一张就是"补完之后抽到阶段三到底长什么样"的证据。
    if(ACT==='QUIZS3'){
      window.__readyDelay = 700;
      __bench.setQzSetup({scope:'s3',size:5,source:'ex'});
      __bench.startQuiz();
    }
    // 自测：揭开答案，拍自评那一排
    if(ACT==='QUIZREVEAL'){
      window.__readyDelay = 1100;
      __bench.setQzSetup({scope:'s1',size:5,source:'ex'});
      __bench.startQuiz();
      setTimeout(function(){ __bench.qzReveal(); }, 400);
    }
    // 自测：答错一道 + 答对一道 + 结束，拍成绩单。
    // qzRate 内部留了 650ms 让人看清变化，所以整流程序要等够久才 READY
    if(ACT==='QUIZRESULT'){
      window.__readyDelay = 2700;
      __bench.setQzSetup({scope:'s1',size:5,source:'ex'});
      __bench.startQuiz();
      setTimeout(function(){ __bench.qzReveal(); __bench.qzRate(false); }, 350);
      setTimeout(function(){ __bench.qzReveal(); __bench.qzRate(true); }, 1150);
      setTimeout(function(){ __bench.qzQuit(); }, 2050);
    }
    // 选方向页：点开第一张卡，拍"就地展开"的样子。
    // 走真实点击，别手改 data-open——否则拍到的是我以为的样子，不是应用真的样子。
    if(ACT==='PICKOPEN'){
      window.__readyDelay = 600;
      var pc=document.querySelector('.pick-card');
      if(pc) pc.click();
    }
    if(ACT==='HELP'){
      // 帮助面板没有触发按钮，只有 ? 快捷键；两条路都试一下
      try{ window.dispatchEvent(new KeyboardEvent('keydown',{key:'?',bubbles:true})); }catch(e){}
      try{ if(typeof window.openHelp==='function') window.openHelp(); }catch(e){}
    }
    var kill=document.createElement('style');
    kill.textContent='*{transition:none!important;animation:none!important;scroll-behavior:auto!important}';
    document.head.appendChild(kill);
    setTimeout(function(){
      if(ACT==='HELP'){
        var ov=document.querySelector('#helpOverlay');
        if(ov && ov.dataset.open!=='1'){
          try{ if(typeof window.openHelp==='function') window.openHelp(); }catch(e){}
        }
      }
      if(SEL){
        var tg=document.querySelector(SEL);
        if(tg){
          var y=tg.getBoundingClientRect().top + window.scrollY - 130;
          if(y>0) document.body.style.marginTop = (-y)+'px';
        }
      }
      document.documentElement.dataset.theme = TH;
      document.title='READY';
    }, window.__readyDelay || 300);
  }
})();
</script>
"""

if __name__ == "__main__":
    only = sys.argv[1:] or list(SHOTS.keys())
    log = []
    for name in only:
        frag, theme, sel, w, h, seed, act = SHOTS[name]
        tag = uuid.uuid4().hex[:6]
        html = SRC.read_text(encoding="utf-8")
        # 预置状态必须早于应用自身的启动脚本。
        # 键名跟着版本的常量走，别写死——应用升级换代时这里最容易悄悄失效。
        if seed is not None:
            pre = ('<script>try{localStorage.setItem("py-path-v3",%s)}catch(e){}</script>'
                   % json.dumps(json.dumps(seed, ensure_ascii=False)))
            html = html.replace("</head>", pre + "</head>", 1)
        inj = (TMPL.replace("__TH__", theme)
                   .replace("__SEL__", sel or "NONE")
                   .replace("__ACT__", act or "NONE")
                   .replace("__SEED__", "null"))
        html = html.replace("</body>", inj + "</body>", 1)
        page = B / ("_shot_%s_%s.html" % (name, tag))
        page.write_text(html, encoding="utf-8")
        png = B / ("shot_%s.png" % name)
        prof = B / ("_sp_%s" % tag)
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
               "--no-default-browser-check", "--hide-scrollbars",
               "--disable-smooth-scrolling", "--force-device-scale-factor=1",
               "--allow-file-access-from-files",
               "--user-data-dir=" + str(prof),
               "--window-size=%d,%d" % (w, h), "--virtual-time-budget=25000",
               "--screenshot=" + str(png)]
        if "-mobile" in name or name.endswith("mobile-light"):
            # Chrome 窗口最小宽度被钳到 500px，所以套一层 iframe 才能真正按 430px 渲染。
            # 注意 iframe 的 src 必须带上路由 hash，否则会渲染成首页。
            wrap = B / ("_shotwrap_%s.html" % tag)
            wrap.write_text(
                '<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<style>html,body{margin:0;background:#EDE9E0}iframe{border:0;display:block}</style></head>'
                '<body><iframe src="%s%s" width="%d" height="%d"></iframe></body></html>'
                % (page.name, frag, w, h), encoding="utf-8")
            cmd.append(wrap.as_uri())
        else:
            cmd.append(page.as_uri() + frag)
        r = subprocess.run(cmd, capture_output=True)
        size = png.stat().st_size if png.exists() else 0
        px = None
        if png.exists() and size > 32:
            data = png.read_bytes()
            px = struct.unpack(">II", data[16:24])
        log.append({"name": name, "png": png.name, "bytes": size, "px": px})
    (B / "_shots.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

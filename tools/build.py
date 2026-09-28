# -*- coding: utf-8 -*-
"""把四份 Markdown 课程编译为单文件离线学习工作台。

用法（在仓库根目录下）：
    python tools/build.py

产物：
    python-学习工作台.html  —— 本地双击用（原始名字）
    index.html               —— 同一份内容，给 GitHub Pages 当站点首页
    两份由同一次构建写出，内容完全一致。
中间产物：tools/_content.json（便于排错复核）

依赖：Python 3.9+，以及 `pip install markdown pygments`
（pygments 是 codehilite 代码高亮用的，markdown 自动会装上）。
"""
import json
import re
from pathlib import Path

import markdown

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parent
# 兼容早期的开发位置 `.workbuddy/build/`：那时 BUILD 的上一级是 `.workbuddy`，
# 再上一级才是仓库根。加这一句，同一个脚本在两个位置都跑得对，
# 也就不存在「两份 build.py 各自漂移」的问题（真踩过：改了一份，另一份是旧的）。
if ROOT.name == ".workbuddy":
    ROOT = ROOT.parent
TPL = BUILD / "template.html"
OUT = ROOT / "python-学习工作台.html"
INDEX = ROOT / "index.html"

# README 里**只给 GitHub 页面看**、不进工作台首页的章节。
# 工作台首页是把 README 的 `##` 章节拼起来渲染的，所以默认全都进；
# 下面这几个是例外，理由各不相同，逐条写清楚免得以后有人以为漏了：
#
#   · 界面预览 —— 是外链图片。工作台是**单文件离线**的，图片没被打包进去，
#     放进首页只会是一排碎图；何况正在用工作台的人，也不需要看它长什么样。
#   · 里程碑自测 —— 工作台自己有一份**可勾选**的同款清单（模板里 .mile 那几张卡）。
#     把 README 这份纯文本版再塞进首页，就是同一件事说两遍。
#   · 许可 —— 指向 LICENSE 文件，单文件里点不开；离线看课程的人也不关心。
HOME_SKIP = ("📸 界面预览", "✅ 里程碑自测", "📄 许可")

# ---------------------------------------------------------------- 阶段元信息
STAGES = [
    {
        "id": "s1",
        "label": "阶段一",
        "name": "入门基础",
        "range": "第 1–8 课",
        "goal": "零基础 → 独立写出 150 行以内的命令行小程序",
        "note": "每周 2 课，约 4–5 周",
        "accent": "teal",
        "file": "01-入门基础.md",
    },
    {
        "id": "s2",
        "label": "阶段二",
        "name": "核心进阶",
        "range": "第 9–16 课",
        "goal": "从「能跑就行」到「结构清晰」——函数化 + 面向对象 + 文件持久化 + 异常处理",
        "note": "每周 1–2 课，约 5–6 周",
        "accent": "indigo",
        "file": "02-核心进阶.md",
    },
    {
        "id": "s3",
        "label": "阶段三",
        "name": "高级应用",
        "range": "第 17–24 课",
        "goal": "从「会写代码」到「会写工程」——装饰器、并发、网络、数据库、测试",
        "note": "每周 1 课 + 1 次复习，约 6–8 周",
        "accent": "amber",
        "file": "03-高级应用.md",
    },
    {
        "id": "s4",
        "label": "阶段四",
        "name": "方向拓展与毕业项目",
        "range": "5 个方向任选其一",
        "goal": "按目标选 1 条主线深入，做出可展示、放 GitHub 的毕业项目",
        "note": "4–8 周，贪多嚼不烂",
        "accent": "rose",
        "file": "04-方向拓展与毕业项目.md",
    },
]

MD_EXT = ["fenced_code", "codehilite", "tables", "sane_lists", "attr_list"]
MD_CFG = {
    "codehilite": {
        "guess_lang": False,
        "css_class": "hl",
        "linenums": False,
        "use_pygments": True,
    }
}

LESSON_RE = re.compile(r"^第\s*(\d+)\s*课\s*[·・]\s*(.+)$")
TIME_RE = re.compile(r"^\*\*⏱️\s*用时：(.+?)\*\*\s*$", re.M)
DIRECTION_RE = re.compile(r"^方向\s*([A-E])\s*[·・]\s*(.+)$")
PROJECT_RE = re.compile(r"^🏁\s*(.+)$")
GRAD_RE = re.compile(r"^🎓\s*(.+)$")


# ---------------------------------------------------------------- 工具函数
def fence_langs(text: str):
    """按顺序抽出围栏代码块的语言名（codehilite 会丢掉语言标记，需补回）。"""
    langs, in_fence = [], False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            if not in_fence:
                lang = s[3:].strip()
                langs.append(lang if lang else "text")
                in_fence = True
            else:
                in_fence = False
    return langs


# 「**小标题**」「**小标题**：」「**小标题**（补充说明）：」——都是引出下面内容的
# 引导行。它后面紧跟列表、中间却没空行时，Python-Markdown 会把整个列表并进同一
# 段落，列表结构直接消失（s3-p 的「技术要求」6 条就是这样渲染没的）。
BOLD_HEAD_RE = re.compile(r"\*\*[^*\n]{1,24}\*\*(?:[（(][^）)\n]{0,24}[）)])?[：:]$")
LIST_LINE_RE = re.compile(r"^(?:\d+[.)]|[-*+])\s+\S")
STANDALONE_BOLD_RE = re.compile(r"\*\*[^*\n]{1,24}\*\*")


def normalize_source(text: str) -> str:
    """三个源码级修补，让 Markdown 正确分块。

    1. 缩进围栏：Python-Markdown 的 fenced_code 要求围栏顶格，列表内缩进的
       ``` 会被当普通文字漏出来。这里转成缩进代码块（保留图形相对缩进）。
    2. 独立粗体行：`**核心知识点**` 紧跟列表时会被并进同一段落，导致列表
       结构丢失。补一个空行，使其独立成块。
    3. 带尾巴的粗体引导行：`**技术要求**（每一项都对应一课）：` 形态同上，
       但它不是"纯粗体"，规则 2 够不着。**只在下一行真的是列表项时**才补
       空行——否则会把正文里以粗体开头的句子硬切成两段。
    """
    text = _fix_indented_fences(text)

    lines = text.split("\n")
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        s = ln.strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if not nxt:
            continue
        if STANDALONE_BOLD_RE.fullmatch(s):
            out.append("")
        elif BOLD_HEAD_RE.fullmatch(s) and LIST_LINE_RE.match(nxt):
            out.append("")
    return "\n".join(out)


def _fix_indented_fences(text: str) -> str:
    """把列表内缩进的围栏提升到顶格。

    Python-Markdown 的 fenced_code 只认顶格的 ```，列表里缩进 3 格的围栏
    会被当成普通文字漏进正文。提升到顶格后能被正常识别为代码块；列表会被
    打断，但 sane_lists 会用 start 属性续上编号。
    """
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        m = re.match(r"^(?P<ind>[ \t]+)(?P<fence>```|~~~)(?P<lang>[^\n`]*)$", lines[i])
        if m:
            fence = m.group("fence")
            body, j, closed = [], i + 1, False
            while j < len(lines):
                if lines[j].strip().startswith(fence):
                    closed = True
                    break
                body.append(lines[j])
                j += 1
            if closed and any(b.strip() for b in body):
                indents = [len(b) - len(b.lstrip()) for b in body if b.strip()]
                shift = min(indents) if indents else 0
                out.append((fence + m.group("lang")).rstrip())
                for b in body:
                    out.append(b[shift:].rstrip() if b.strip() else "")
                out.append(fence)
                if j + 1 < len(lines) and lines[j + 1].strip():
                    out.append("")
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def to_html(text: str) -> str:
    text = normalize_source(text)
    langs = fence_langs(text)
    html = markdown.markdown(text, extensions=MD_EXT, extension_configs=MD_CFG)
    counter = {"i": 0}

    def _stamp(m):
        i = counter["i"]
        counter["i"] += 1
        lang = langs[i] if i < len(langs) else "text"
        return '<div class="hl" data-lang="%s"><pre><code>' % lang

    html = re.sub(r'<div class="hl"><pre><span></span><code>', _stamp, html)
    # 缩进代码块（codehilite 不走 fenced_code 分支）统一标为纯文本
    html = html.replace(
        '<div class="hl"><pre><code>', '<div class="hl" data-lang="text"><pre><code>'
    )
    return html


def strip_fences_edges(body: str) -> str:
    """去掉正文两端孤立的 --- 分隔线。"""
    lines = body.split("\n")
    while lines and lines[0].strip() in ("", "---", "***"):
        lines.pop(0)
    while lines and lines[-1].strip() in ("", "---", "***"):
        lines.pop()
    return "\n".join(lines)


def split_sections(text: str):
    """按二级标题切分，返回 [{'title':..., 'body':...}]，第一项可能是前言。"""
    out, cur, in_fence = [], None, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            if cur:
                out.append(cur)
            cur = {"title": line[3:].strip(), "body": []}
        elif not in_fence and line.startswith("# "):
            continue
        else:
            if cur is None:
                cur = {"title": None, "body": []}
            cur["body"].append(line)
    if cur:
        out.append(cur)
    return out


def polish(html: str, hw_class: str = "hw-list", tasks: bool = False) -> str:
    """把通用 HTML 打磨成课程语义化结构。

    ``tasks=True``（阶段项目的交付要求页、毕业项目的验收标准页）：页面里每一个
    顶层有序列表都是"要做的事"，统一挂上 ``hw_class``。它们于是和作业共用同一套
    三态（未做 / 卡住 / 已做）、同一张 hw 表、同一个错题本与复习节奏——不用为
    "项目任务"再造一套追踪，也就不会多出一处需求漂移。
    """
    # 例题标题：**例题 1：xxx** 后面常紧跟一行说明，同属一个 <p>
    def _ex(m):
        title, rest = m.group(1), (m.group(2) or "").strip()
        head = f'<h4 class="ex-title">{title}</h4>'
        return head + (f"<p>{rest}</p>" if rest else "")

    html = re.sub(
        r"<p><strong>(例题\s*\d*\s*[：:][^<]*?)</strong>(.*?)</p>",
        _ex,
        html,
        flags=re.S,
    )

    # 「解析：」独立成带标签的说明块
    html = re.sub(
        r"<p>解析：",
        '<p class="parse"><span class="parse-tag">解析</span>',
        html,
    )

    # 方向页 / 项目页的小标题（兼容「独立成段」与「后接正文」两种形态）
    def _mini(m):
        title, rest = m.group(1), (m.group(2) or "").strip()
        head = f'<h4 class="mini-title">{title}</h4>'
        return head + (f"<p>{rest}</p>" if rest else "")

    html = re.sub(
        r"<p><strong>(核心知识点|练习题|路线|示例：[^<]*?|验收标准)</strong>[:：]?(.*?)</p>",
        _mini,
        html,
        flags=re.S,
    )

    # 作业难度徽章
    for tag, cls in (("基础", "b-base"), ("进阶", "b-adv"), ("挑战", "b-chal")):
        html = html.replace(
            "【%s】" % tag, '<span class="badge %s">%s</span>' % (cls, tag)
        )

    # 作业/练习列表加钩子类
    html = re.sub(
        r'(<h3[^>]*>\s*✏️\s*作业\s*</h3>\s*)<ol>', r'\1<ol class="%s">' % hw_class, html
    )
    html = re.sub(
        r'(<h4 class="mini-title">练习题</h4>\s*)<ol>',
        r'\1<ol class="%s">' % hw_class,
        html,
    )

    # 项目页 / 毕业项目页：剩下的顶层有序列表都是"交付要求"，一并纳入追踪。
    # 负向前瞻保证已经挂过类的列表不会被重复处理（否则会出现两个 class 属性）。
    # 替换串**不带收尾的 `>`**：模式只吃掉 `<ol`，原标签的 `>` 得留着，
    # 否则会拼出 `<ol class="hw-list">>`，页面上多一个游离的尖括号。
    # 不带 `>` 收尾也顺带兼容 sane_lists 生成的 `<ol start="3">`。
    if tasks:
        html = re.sub(
            r"<ol(?![^>]*\bclass=)", '<ol class="%s"' % hw_class, html
        )

    # 清理 codehilite 生成的多余空 span
    html = html.replace("<pre><span></span><code>", "<pre><code>")
    return html


def answer_card(m: re.Match) -> str:
    """把例题区里的一个代码块包成卡片。

    两条约定（与课程源文件的写法一致）：

    * ``python`` 块＝**参考答案**。默认展开——例题是示范，答案本身就是
      教学内容，藏起来等于把课文上了锁；想自测时点标题即可收起。
    * 其余语言（``text`` / ``bash`` …）＝**运行效果**，属于题面的一部分
      （"打印出如下效果"指的就是它）。加 ``out`` 类：默认展开，且前端
      不把它当成一道题——不给自评按钮、不计入自评进度与错题本。

    摘要行预留 ans-state（自评状态）与 ans-hint（展开提示）两个槽位，
    前端据此把掌握度写进容器，扫一眼列表就知道哪些题要回看。
    """
    lang = m.group(2) or "python"
    body = m.group(3)
    if lang in ("python", "py"):
        return (
            '<details class="answer" open data-mark="0"><summary>'
            '<span class="ans-dot"></span>'
            '<span class="ans-label">参考答案</span>'
            '<span class="ans-state"></span>'
            '<span class="ans-hint" aria-hidden="true"></span>'
            "</summary>"
            '<div class="hl" data-lang="%s">%s</div>'
            "</details>" % (lang, body)
        )
    return (
        '<details class="answer out" open><summary>'
        '<span class="ans-dot"></span>'
        '<span class="ans-label">运行效果</span>'
        '<span class="ans-hint" aria-hidden="true"></span>'
        "</summary>"
        '<div class="hl" data-lang="%s">%s</div>'
        "</details>" % (lang, body)
    )


def collapse_answers(html: str) -> str:
    """例题区内的代码块统一包成卡片（见 answer_card 的两条约定）。"""
    parts = re.split(r"(<h3[^>]*>.*?</h3>)", html)
    out = []
    for i, seg in enumerate(parts):
        if i > 0 and "💡" in parts[i - 1] and "例题" in parts[i - 1]:
            seg = re.sub(
                r'<div class="hl"( data-lang="([^"]*)")?>(.*?)</div>',
                answer_card,
                seg,
                flags=re.S,
            )
        out.append(seg)
    return "".join(out)


def plain_text(html: str) -> str:
    txt = re.sub(r"<pre.*?</pre>", " ", html, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def measure(html: str) -> dict:
    """从最终 HTML 统一统计各页的条目数量，供导航与卡片展示。"""

    def li_in(pattern, flags=re.S):
        return sum(
            len(re.findall(r"<li>", m)) for m in re.findall(pattern, html, flags)
        )

    kp = re.search(r"<h3[^>]*>\s*📚\s*知识点\s*</h3>(.*?)(?=<h3|$)", html, re.S)
    return {
        "kp": len(re.findall(r"<li>", kp.group(1))) if kp else 0,
        "ex": len(re.findall(r'class="ex-title"', html)),
        "hw": li_in(r'<ol class="hw-list">(.*?)</ol>'),
        "points": li_in(r'<h4 class="mini-title">核心知识点</h4>\s*<ol>(.*?)</ol>'),
        "codes": len(re.findall(r'<div class="hl"', html)),
        # 注意别写成 '<details class="answer">'：折叠块现在带 data-mark 属性。
        # 「运行效果」块写的是 class="answer out"，这里的引号紧贴 answer，
        # 天然匹配不上——正好只数真正的例题。
        "answers": len(re.findall(r'<details class="answer"', html)),
    }


# ---------------------------------------------------------------- 阶段解析
def build_stage(meta: dict) -> dict:
    raw = (ROOT / meta["file"]).read_text(encoding="utf-8")
    sections = split_sections(raw)
    lessons, project = [], None

    for sec in sections:
        title = sec["title"]
        body = strip_fences_edges("\n".join(sec["body"]))
        if title is None:
            continue

        # ---- 阶段项目 ----
        pm = PROJECT_RE.match(title)
        if pm:
            html = polish(to_html(body), tasks=True)
            project = {
                "id": meta["id"] + "-p",
                "kind": "project",
                "title": pm.group(1).strip(),
                "no": "",
                "time": "",
                "html": html,
                "counts": measure(html),
                "text": plain_text(html),
            }
            continue

        # ---- 方向页（阶段四）----
        dm = DIRECTION_RE.match(title)
        if dm:
            html = polish(collapse_answers(to_html(body)))
            lessons.append(
                {
                    "id": f'{meta["id"]}-dir{dm.group(1).lower()}',
                    "kind": "direction",
                    "no": dm.group(1),
                    "title": dm.group(2).strip(),
                    "time": "",
                    "html": html,
                    "counts": measure(html),
                    "text": plain_text(html),
                }
            )
            continue

        # ---- 毕业项目 / 选方向 / 附录 ----
        # 这三页原本挤在同一个 extra 里，前端只能靠"标题里有没有'毕业项目'"去猜。
        # 拆成独立 kind，前端的文案与专属交互就能按 kind 派发，不必硬编码 slug。
        gm = GRAD_RE.match(title)
        if gm or title.startswith("附录") or title.startswith("怎么选方向"):
            if gm:
                kind = "grad"
            elif title.startswith("怎么选方向"):
                kind = "picker"
            else:
                kind = "extra"
            html = polish(
                collapse_answers(to_html(body)), tasks=(kind == "grad")
            )
            lessons.append(
                {
                    "id": f'{meta["id"]}-{_slug(title)}',
                    "kind": kind,
                    "no": "",
                    "title": title,
                    "time": "",
                    "html": html,
                    "counts": measure(html),
                    "text": plain_text(html),
                }
            )
            continue

        # ---- 正课 ----
        lm = LESSON_RE.match(title)
        if not lm:
            continue
        no, name = int(lm.group(1)), lm.group(2).strip()
        tm = TIME_RE.search(body)
        times = tm.group(1).strip() if tm else ""
        if tm:
            body = TIME_RE.sub("", body, count=1)
        html = polish(collapse_answers(to_html(body)))
        lessons.append(
            {
                "id": f'{meta["id"]}-l{no}',
                "kind": "lesson",
                "no": no,
                "title": name,
                "time": times,
                "html": html,
                "counts": measure(html),
                "text": plain_text(html),
            }
        )

    return {
        "id": meta["id"],
        "label": meta["label"],
        "name": meta["name"],
        "range": meta["range"],
        "goal": meta["goal"],
        "note": meta["note"],
        "accent": meta["accent"],
        "lessons": lessons,
        "project": project,
    }


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", s).strip("-")
    return s[:24] or "x"


def faqify(html: str) -> str:
    """README 的 Q/A 折叠成 </details>，长问答不占版面。"""

    def _mk(m):
        return (
            f'<details class="faq"><summary>{m.group(1)}</summary>'
            f"<p>{m.group(2).strip()}</p></details>"
        )

    # 形态一：Q 独立成段，答案在下一段（源码规范化后是这种）
    html = re.sub(
        r"<p><strong>(Q：[^<]*?)</strong></p>\s*<p>(.+?)</p>", _mk, html, flags=re.S
    )
    # 形态二：Q 与答案挤在同一个段落里
    html = re.sub(
        r"<p><strong>(Q：[^<]*?)</strong>\s*(.+?)</p>", _mk, html, flags=re.S
    )
    return html


# ---------------------------------------------------------------- README 首页
def build_home():
    """把 README 编译成工作台首页的说明区，返回 (进了首页的章节, 被跳过的章节标题)。

    只取二级标题及其正文：
      · `# ...` 主标题，以及**第一个二级标题之前**的内容（项目简介、在线地址等），
        属于 GitHub 页面专用，不进首页——首页已经有自己的英雄区了；
      · HOME_SKIP 里的章节也跳过，理由见那里的注释。

    返回值里带上"跳过了哪些"，是为了写进构建报告：万一哪天想确认某个章节
    到底进没进首页，看一眼报告就知道，不用去翻产物。
    """
    raw = (ROOT / "README.md").read_text(encoding="utf-8")
    sections = split_sections(raw)

    keep, skipped = [], []
    for sec in sections:
        if sec["title"] is None:
            continue
        if sec["title"] in HOME_SKIP:
            skipped.append(sec["title"])
            continue
        keep.append((sec["title"], strip_fences_edges("\n".join(sec["body"]))))

    chunks = []
    for title, body in keep:
        html = to_html(body)
        html = faqify(html)
        html = polish(html)
        # 文件链接 → 站内导航
        html = html.replace('href="01-入门基础.md"', 'href="#/s1"')
        html = html.replace('href="02-核心进阶.md"', 'href="#/s2"')
        html = html.replace('href="03-高级应用.md"', 'href="#/s3"')
        html = html.replace('href="04-方向拓展与毕业项目.md"', 'href="#/s4"')
        chunks.append({"title": title, "html": html})
    return chunks, skipped


# ---------------------------------------------------------------- 主流程
def main() -> None:
    stages = [build_stage(m) for m in STAGES]
    home, home_skipped = build_home()
    data = {"stages": stages, "home": home}

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    # 「单文件、离线、零外部依赖」这条承诺的底线检查：产物里不该有 <img>。
    # 模板自己一个图片标签都没有，所以只要冒出图片，必然是 README 新加了图片章节
    # 却忘了加进 HOME_SKIP——离线打开时那就是一排碎图。
    # 直接让构建失败，比等用户在离线环境里发现要好。
    #
    # ⚠️ 必须查在下面那行 `<` → `\u003c` 转义**之前**。第一版查的是转义后的
    #    最终 HTML，于是 `<img` 早已变成 `\u003cimg`，`count("<img")` 恒为 0——
    #    守卫生效与否全看运气，负向对照一测就露馅了。
    n_img = payload.count("<img")
    if n_img:
        raise SystemExit(
            "构建失败：注入内容里有 %d 个 <img>，会破坏「单文件离线」。\n"
            "  这些图片来自 README——把对应章节加进 build.py 的 HOME_SKIP 即可。\n"
            "  （在线的 GitHub 页面照常显示，只是不进工作台首页。）" % n_img
        )

    payload = payload.replace("<", "\\u003c")

    tpl = TPL.read_text(encoding="utf-8")
    html = tpl.replace("/*__COURSE_DATA__*/null", payload)

    # 同一份内容写两个地方：
    #   * python-学习工作台.html —— 本地双击用的原始名字，README 里引的也是它；
    #   * index.html              —— GitHub Pages 只认它作站点首页，URL 才干净。
    # 由构建脚本一次性写出两份，所以不存在"改完忘同步"的问题。
    OUT.write_text(html, encoding="utf-8")
    INDEX.write_text(html, encoding="utf-8")
    (BUILD / "_content.json").write_text(payload, encoding="utf-8")

    total_lessons = sum(len(s["lessons"]) for s in stages)
    report = {
        "output": str(OUT),
        "index": str(INDEX),
        "bytes": OUT.stat().st_size,
        "stages": [
            {
                "id": s["id"],
                "lessons": len(s["lessons"]),
                "project": bool(s["project"]),
            }
            for s in stages
        ],
        "total_sections": total_lessons,
        "home_sections": [h["title"] for h in home],
        "home_skipped": home_skipped,
    }
    (BUILD / "_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

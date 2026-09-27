# tools/ —— 构建与验收

这套课程是**用 Markdown 写成、编译成单文件 HTML** 的。仓库根目录那四份 `.md` 是
唯一的内容源；`python-学习工作台.html` 是产物。本目录放编译器和验收工具。

> 只想读课程的话，**直接双击 `python-学习工作台.html`** 就行——它自带全部内容，
> 离线可用、零外部依赖，不需要装任何东西。本目录是给想改内容或复核实现的人用的。

## 1. 装依赖

```bash
python -m pip install markdown pygments
```

- `markdown`：把 `.md` 编译成 HTML。
- `pygments`：代码高亮（`codehilite` 扩展用它）。缺了会报错，务必一起装。

Python 3.9+ 即可。

## 2. 重新构建

```bash
python tools/build.py
```

会在仓库根目录覆盖写出 `python-学习工作台.html`，同时生成中间产物
`tools/_content.json`（每页的 HTML 与条目计数，排错用）。

构建脚本里集中放了几条内容约定，改 `template.html` 之前值得先读一遍
`build.py` 的注释：

- **例题区的 `python` 块 = 参考答案**（默认展开）；**其余语言块 = 运行效果**，
  属于题面，前端不把它当一道题（不给自评、不计入进度）。
- **题数按「答案块」算，不按标题算**。有一课一个标题挂两个答案块。
- 项目页/毕业页的顶层有序列表会被自动挂上 `hw-list`，于是和作业共用同一套
  三态追踪（未做 / 卡住 / 已做）——不必为"项目任务"再造一套。

## 3. 跑验收

验收是**无头 Chrome 注入探针 → 读运行时数值 → 断言**，不是肉眼看。

```bash
# 全部 17 个场景
python tools/_browser.py home lesson exopen review spaced quiz today \
    gradplan gradplanFull grad picker grad430 hwstuck records exstale \
    narrow430 narrow768

# 把结果压成通过/失败清单
python tools/_report.py
```

结果落在 `tools/_browser_<场景>.json`，汇总打印形如
`断言总数 640，失败 0`。

`_report.py` 里还做**跨场景一致性**检查（比逐场景断言更狠）：比如
"首页计划卡上的数字 = 侧栏徽章 = 底层统计"三处必须同数，毕业页两组状态的
卡序必须逐字相同——这类断言能抓住"两套渲染分支各写一遍、迟早会漂"的问题。

需要环境变量时可覆盖：

| 变量 | 用途 |
|---|---|
| `CHROME_PATH` | 指定 Chrome/Chromium 可执行文件（默认自动探测常见路径） |
| `NODE_PATH_BIN` | 指定 `node`（只在 `_jscheck.py` / `_probecheck.py` 用到） |

## 4. 截图取证（可选）

```bash
python tools/_shots.py                    # 全部
python tools/_shots.py 01-home-light      # 只拍某几张
```

输出 `tools/shot_<名称>.png`，默认**不入库**（约 31MB）。想在 README 里当视觉
文档发布，就把 `.gitignore` 里 `tools/shot_*.png` 那行删掉。

## 5. 改课程内容的规矩

改那四份 `.md` 时有三条硬规矩，原因都写进 `build.py` 与 `_diffcheck.py` 注释了：

1. **先备份**到 `tools/_md_backup/`。
2. **只插不改**：新增段落，绝不动既有的 `<details class="answer">` 结构——
   前端按文档序算例题编号，动了顺序，用户已存的自评与复习档期会挂到别的题上。
   例题标题、章节标题、代码围栏都是「禁区行」。
3. 改完跑 `python tools/_diffcheck.py` 核验**行级 diff**：它断言禁区行既没被删、
   也没被改写。结构等价转换（比如把分号句拆成有序列表）是允许的。

## 6. 目录里的脚本

| 脚本 | 作用 |
|---|---|
| `build.py` | 主编译器：4 份 `.md` + `template.html` → 单文件 HTML |
| `template.html` | 前端模板：样式、交互、状态层全部在这里（占位符 `/*__COURSE_DATA__*/null`） |
| `_browser.py` | 无头浏览器注入探针、跑场景、回传运行时数值 |
| `_report.py` | 把 17 个场景的结果压成通过/失败清单 + 跨场景一致性检查 |
| `_shots.py` | 截图取证 |
| `_smoke_grad.py` / `_smoke_pick.py` | 单个功能的冒烟探针（比全套快得多，改功能时先用） |
| `_probecheck.py` / `_jscheck.py` | 探针脚本 / 产物内联 JS 的语法预检 |
| `_exids.py` / `_hwmap.py` / `_exbriefs.py` | 内容盘点：例题 id、每页作业数、题面完整度 |
| `_inject.py` | 批量往裸例题标题下补题面（一次性工具，保留备查） |
| `_diffcheck.py` | `.md` 改动核验 |
| `_ct.py` | 对比度计算（半透明叠加的精确复现） |

# -*- coding: utf-8 -*-
"""把 28 条「任务描述」插到裸例题的标题行下面。

约定（与 00 阶段一已有写法一致）：
    标题行
    任务描述          ← 本次插入
    <空行>            ← 本次插入
    ```python
不变式：
    * 只做插入，不删不改任何既有行；
    * 不碰任何 ``` 围栏与 <details> 相关结构 → 例题编号 / 自评序号不会平移。
"""
import io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = io.open(os.path.join(ROOT, 'tools', '_inject.txt'), 'w', encoding='utf-8')


def P(*a):
    print(*a)
    print(*a, file=OUT)


JOBS = {
    '01-入门基础.md': [
        ('找出隐藏的 bug', '下面这段代码一运行就会报错。先自己找是哪一行、为什么，再看解析。'),
        ('九九乘法表', '用两层循环打印 1–9 的乘法表，第 i 行就排 i 个式子。'),
    ],
    '02-核心进阶.md': [
        ('素数判断函数', '写 `is_prime(n)` 判断整数是否为素数，再用它打印 2–30 之间的所有素数。'),
        ('温度转换 + 多返回值', '写两个函数：`c_to_f(c)` 摄氏转华氏；`analyze(scores)` 返回 `(平均分, 及格人数)`。'),
        ('万能统计函数', '写 `describe(*nums, precision=2)`，接收任意个数字，返回 `(个数, 总和, 平均值)`。'),
        ('递归斐波那契与其代价', '用递归写 `fib(n)` 并打印前 10 项；再试着算 `fib(35)`，感受一下它为什么卡住。'),
        ('安全输入函数（以后每个项目都会用）', '写 `ask_int(prompt, low=None, high=None)`：反复询问直到拿到合法整数，格式错和越界都要给提示。'),
        ('银行账户', '写 `BankAccount` 类，实现 `deposit` 和 `withdraw`：金额不合法或余额不足时拒绝并返回 `False`。'),
        ('统计造了几个实例', '用一个类属性记录一共造过多少个实例——造 3 个之后 `Counter.count` 应该是 3。'),
        ('向量类（运算符重载）', '让 `Vector(x, y)` 支持 `v1 + v2`、`v1 == v2` 和直接 `print(v)`，想想各要重载什么。'),
        ('员工工资体系', '写 `Employee` 和继承它的 `Manager`（底薪 + 奖金），再用一个循环算出所有人的工资总和。'),
        ('数据清洗三连', '把 `["  92 ", "absent", "88", "  45", "", "77"]` 里能转数字的筛出来转成 `int`，再用 `zip` 绑上姓名做成字典，全程用推导式。'),
        ('大文件惰性处理', '写生成器 `error_lines(path)`：只产出含 `ERROR` 的行、不把整个文件读进内存，再用一行代码数出有多少行。'),
        ('随机点名器', '用 `random` 做四件事：抽 1 个值日生、抽 3 个不重复的人组队、原地打乱名单、取一个随机整数。'),
        ('生日倒计时', '写 `days_until_birthday(month, day)`：算今天距离下一个生日还有多少天，今年过了就翻到明年。'),
    ],
    '03-高级应用.md': [
        ('缓存装饰器', '写 `memoize` 装饰器把返回值按参数缓存起来，用它装饰第 10 课的递归 `fib`，看 `fib(100)` 是否秒出。'),
        ('带参数的重试装饰器', '写 `retry(times, delay=1)`：失败就重试，间隔 delay 秒，重试用尽抛 `RuntimeError`。'),
        ('让 mypy 替你抓 bug', '下面代码里的类型错误运行时不会立刻报错。先自己找，再用 `mypy bugs.py` 让它替你指出来。'),
        ('解析日志行', '用命名分组正则从日志行里取出日期、时间、级别、状态码，打印 level 和 code。'),
        ('密码强度校验', '写 `check_password(pwd)` 检查长度 ≥8、含大写、含数字三条规则，返回所有不满足的说明。'),
        ('线程池并发', '用 `ThreadPoolExecutor` 并发「请求」5 个 URL（`sleep(1)` 模拟），对比串行 5 秒、并发几秒。'),
        ('多进程算 CPU 密集任务', '用 `ProcessPoolExecutor` 把 4 个 CPU 密集任务真正分到多个核，注意 Windows 的 `__main__` 护身符。'),
        ('信号量限流', '用 `asyncio.Semaphore(3)` 给 10 个并发任务限流，同时最多只跑 3 个。'),
        ('带超时的调用', '用一个要 5 秒的调用配上 2 秒超时，超时就走兜底逻辑，别让程序卡死。'),
        ('带重试与退避的健壮请求', '写 `robust_get(url, retries=3)`：失败就重试，间隔用指数退避（2s、4s、8s），用尽后抛异常。'),
        ('免 key 天气查询', '调 open-meteo 拿当前天气，传经纬度，返回温度和风速。别忘了 `timeout` 和 `raise_for_status()`。'),
        ('迷你学生库', '用 `sqlite3` 建 student 表并写增、改、查三个函数，全程参数化查询；UPDATE 后检查 `rowcount`。'),
        ('函数写测试', '用 `pytest` + `monkeypatch` 给 `ask_int` 写三个测试：正常输入、先错后对、永远不合法。'),
    ],
}

total_ok = 0
fail = []
for fn, jobs in JOBS.items():
    path = os.path.join(ROOT, fn)
    lines = io.open(path, encoding='utf-8').read().split('\n')
    hits = []
    for key, desc in jobs:
        found = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith('**例题') and key in s:
                found = i
                break
        if found is None:
            fail.append('%s :: 找不到标题 <%s>' % (fn, key))
            continue
        nxt = lines[found + 1].strip() if found + 1 < len(lines) else ''
        if not nxt.startswith('```'):
            fail.append('%s :: <%s> 下一行不是代码围栏（已是 %r），跳过' % (fn, key, nxt[:30]))
            continue
        hits.append((found, key, desc))

    for i, key, desc in sorted(hits, reverse=True):
        lines[i + 1:i + 1] = [desc, '']

    io.open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    P('%-20s 插入 %d 条' % (fn, len(hits)))
    total_ok += len(hits)

P()
P('成功插入合计 =', total_ok)
if fail:
    P('!! 未处理：')
    for f in fail:
        P('   ', f)
else:
    P('无未处理项。')
OUT.close()
sys.exit(1 if (fail or total_ok != 28) else 0)

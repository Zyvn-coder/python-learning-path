"""把 18 个场景的探测结果压缩成一张通过/失败清单。"""
import datetime
import json, os, glob, re

D = os.path.dirname(os.path.abspath(__file__))
# ⚠️ 场景数 ≠ 页面数。套件只跑这里列出的路由，所以"0 控制台错误"这句话的
# 分母是**场景覆盖到的路由**，不是全部 34 个页面。曾经因为漏了 stage，
# 阶段页上的 TypeError 躲了很久——加场景时请对照 KIND 清单数一遍。
ORDER = ['home', 'lesson', 'exopen', 'review', 'spaced', 'quiz', 'today',
         'gradplan', 'gradplanFull',
         'grad', 'picker', 'grad430', 'hwstuck', 'records', 'exstale',
         'stage',
         'narrow430', 'narrow768']

# 可勾的练习项总数 = 课内作业 120 + 方向练习题 22 + 阶段项目交付要求 18 + 毕业验收 9。
# 这是个**内容事实**（跟着 4 份 .md 走），不是实现细节——阶段项目和毕业项目的
# 交付要求现在也进同一张 hw 表，所以口径从 142 涨到 169。
# 写成一个常量而不是撒在各处：改内容时只动这一行，断言之间的关系仍然成立。
HW_TOTAL = 169
EX_TOTAL = 45


def _d(n):
    """相对今天的日期。档期断言不能写死字符串，否则隔天就红。"""
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


def rev(l, n, off):
    """档期记录断言：档位 l、练过 n 次、到期日＝今天+off 天。"""
    def chk(s):
        return (isinstance(s, str) and ('"l":%d' % l) in s
                and ('"n":%d' % n) in s and ('"due":"%s"' % _d(off)) in s)
    chk.__doc__ = '档位 %d · 练过 %d 次 · %s 到期' % (l, n, _d(off))
    return chk


def nonempty(s):
    """只要求非空——文案会改，句式不该被断言焊死。"""
    return isinstance(s, str) and len(s.strip()) > 0
nonempty.__doc__ = '非空'


def site_link(s):
    """形如 #/<课时 id> 的站内链接。

    不能写死具体课时——自测是随机抽题的，"回课文"指向哪一课每次都不一样。
    真正要断言的是「它指向当前这道题所属的课时」，那件事在浏览器里算好、
    由 FOOT_ITEM_OK 回答；这里只管形状。"""
    return isinstance(s, str) and s.startswith('#/') and len(s) > 2 and ' ' not in s
site_link.__doc__ = '形如 #/<课时 id> 的站内链接'


def export_name(s):
    """导出文件名：python学习记录-<今天>.json"""
    return s == 'python学习记录-%s.json' % _d(0)
export_name.__doc__ = '文件名含今天的日期'


def cards_contain(*frags):
    """卡片数对得上，且每张卡片的文案都能找到——顺序无关，改排版不会假红。"""
    def chk(s):
        if not isinstance(s, str) or '|' not in s:
            return False
        n, _, body = s.partition('|')
        if n != str(len(frags)):
            return False
        return all(f in body for f in frags)
    chk.__doc__ = '%d 张卡片：%s' % (len(frags), ' / '.join(frags))
    return chk


def at_least(x):
    """数值下限。用在对比度上：具体值会随主题微调，但 4.5:1 这条线不能让。"""
    def chk(v):
        try:
            return float(v) >= x
        except Exception:
            return False
    chk.__doc__ = '>= %g' % x
    return chk


def one_day_time(sec):
    """时长表里只有今天这一条，累计 sec 秒。"""
    def chk(v):
        try:
            return json.loads(v) == {_d(0): sec}
        except Exception:
            return False
    chk.__doc__ = '今天累计 %d 秒' % sec
    return chk


def exp_time(s):
    """导出的每日时长：今天 3600、昨天 900、前天 1200。"""
    try:
        return json.loads(s) == {_d(0): 3600, _d(-1): 900, _d(-2): 1200}
    except Exception:
        return False
exp_time.__doc__ = '今天 3600 / 昨天 900 / 前天 1200'


def stat_week():
    """本周累计＝周一至今天的时长之和（与应用 sumThisWeek/fmtDur 同口径）。

    这条以前写死了「1 时 35 分」——只在周三之后成立，周一跑就会红。
    """
    dow = datetime.date.today().weekday()          # 0 = 周一
    sec = 3600 + (900 if dow >= 1 else 0) + (1200 if dow >= 2 else 0)
    h, m = sec // 3600, round(sec % 3600 / 60)
    want = ('%d 时 %d 分' % (h, m)) if (h and m) else ('%d 小时' % h if h else '%d 分' % m)

    def chk(s):
        return s == want
    chk.__doc__ = '本周累计应为 %s' % want
    return chk

# 每个场景里必须满足的断言：(路径, 期望值, 说明)
ASSERT = {
    'home': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        ('metrics.CT_SWEEP_DARK', [], '深色对比度全部达标'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        # 首页说明区的标题大纲。缺陷史：readme 只拼 html、把 title 丢掉，
        # 7 个 `##` 标题全不渲染，其 `###` 子节以 h3 挂在「四个阶段」底下。
        # 期望值由探针从 COURSE.home 里现推（不写死标题文字），逐字比对。
        ('metrics.DOC_H2_MATCH', True, 'README 各章节标题都在，且次序与数据一致'),
        ('metrics.DOC_FIRST_HEAD_IS_H2', True, '说明区的第一个标题是段标题，不是子节'),
        ('metrics.DOC_H2_BEFORE_H3', 0, '没有子节跑在所属段标题前面'),
        ('metrics.HOME_H1_N', 1, '整页只有一个 h1'),
        ('metrics.HOME_SKIP', '', '标题层级不跳档'),
        ('metrics.HELP_OPEN', '1', '帮助面板可打开'),
        ('metrics.HELP_BODY_LOCK', 'hidden', '帮助面板锁滚动'),
        ('metrics.HELP_CLOSED', '0', '帮助面板可关闭'),
        ('metrics.SEARCH_BY_SLASH', '1', '"/" 唤起搜索'),
        ('metrics.FOCUS_IS_INPUT', True, '焦点进入输入框'),
        ('metrics.FOCUS_BACK', True, '关闭后焦点归位'),
        ('metrics.SEARCH_CLOSED', '0', '搜索可关闭'),
        ('metrics.SEARCH_UNLOCK', 'yes', '搜索关闭后滚动解锁'),
        ('metrics.THEME_TOGGLE', 'light->dark', '主题切换'),
        ('metrics.THEME_STORED', 'dark', '主题已持久化'),
        ('metrics.THEME_BACK', 'yes', '主题可切回'),
        ('metrics.TYPING_GUARD', 'ok', '输入时不误触发快捷键'),
        ('metrics.BG_NOT_WHITE', 'ok', '背景非纯白'),
        ('metrics.BG_GRADIENT', 'yes', '背景有渐变'),
        ('metrics.BG_NOISE', 'yes', '背景有噪点质感'),
        # 今日计划：空工作台的形态。四张卡都在，但只该有「下一个知识点」亮着——
        # 没活可干却挂着箭头，等于骗人点进去
        ('metrics.PLAN_CARDS', 4, '今日计划四张行动卡'),
        ('metrics.PLAN_ONLY_NEXT', 'yes', '空状态下只有「下一个知识点」是活的'),
        ('metrics.PLAN_ARROW_MATCH', 'yes', '箭头只出现在有活可干的卡上（与 data-on 成对）'),
        ('metrics.PLAN_EMPTY_NOTE', 'yes', '空错题本说的是"空着"，不是"0 道"'),
    ],
    'lesson': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        ('metrics.ANSWERS_N', 2, '折叠答案数量'),
        ('metrics.EX_GAUGE_BEFORE', '0/2', '自评计数初始值'),
        ('metrics.MARK_AFTER_BAD', '-1', '标记"没写出来"'),
        ('metrics.STATE_TXT_BAD', '待复习', '状态文案'),
        ('metrics.EX_GAUGE_AFTER', '1/2', '自评计数递增'),
        ('metrics.BADGE_AFTER_BAD', '1', '侧栏徽章 +1'),
        ('metrics.STORED_EX', '{"ex-s3-l17-0":-1}', '状态已持久化'),
        ('metrics.MARK_AFTER_GOOD', '1', '标记"写对了"'),
        ('metrics.STATE_TXT_GOOD', '已掌握', '状态文案'),
        ('metrics.BADGE_AFTER_GOOD', '0', '徽章归零'),
        ('metrics.MARK_AFTER_UNDO', '0', '可撤销标记'),
        ('metrics.STORED_EX_AFTER_UNDO', '{}', '撤销后已清空'),
        ('metrics.DONE_PRESSED', 'true', '标记本课完成'),
        ('metrics.DONE_TXT', '已完成', '完成态文案'),
        ('metrics.HW_ID', 'ok', 'li 的 id 与作业 id 一致'),
        ('metrics.HW_STUCK_BTN', 'present', '每道作业都配了「卡住」按钮'),
        ('metrics.HW_STATE0', 'todo', '作业初始是未做'),
        ('metrics.HW_STATE1', 'done', '勾选后变成已完成'),
        ('metrics.HW_TXT', '1/5', '作业计数跟着走'),
        ('metrics.HW_STATE2', 'stuck', '点「卡住」翻成卡住态'),
        ('metrics.HW_STUCK_PRESSED', 'true', '卡住按钮呈按下态'),
        ('metrics.HW_STUCK_CHIP', '1', '题头卡住计数 +1'),
        ('metrics.HW_TXT_STUCK', '0/5', '卡住不算已完成'),
        ('metrics.HW_STORED', '{"s3-l17:0":-1}', '卡住的作业按 -1 落盘'),
        ('metrics.HW_REV_DUE_TODAY', 'today', '卡住当场排进「今天该复习」'),
        ('metrics.HW_POOLHW', 1, '卡住的作业进了错题池'),
        ('metrics.HW_HWTODO', HW_TOTAL - 1, '其余作业仍是未做'),
        ('metrics.HW_STATE3', 'todo', '再点一次＝取消卡住'),
        ('metrics.HW_REV_AFTER', 0, '取消后档期一并清掉，不留孤儿'),
        ('metrics.HW_POOLHW_AFTER', 0, '作业退出错题池'),
        ('metrics.HW_CONSERVE', '%d/%d' % (EX_TOTAL, HW_TOTAL),
         '例题 %d 道 / 作业 %d 项' % (EX_TOTAL, HW_TOTAL)),
    ],
    # 例题是示范：参考答案必须一进来就看得见；「运行效果」是题面的一部分，不算一道题
    'exopen': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '对比度全部达标'),
        ('metrics.CARDS_N', 3, '第 1 课共 3 个卡片'),
        ('metrics.OPEN_N', 3, '全部默认展开，没有需要点开的答案'),
        ('metrics.ANSWER_LABEL', '参考答案', '答案卡片标题'),
        ('metrics.ANS_TXT_HAS_PRINT', 'yes', '答案代码进来就可见'),
        ('metrics.OUT_N', 1, '识别出 1 个运行效果块'),
        ('metrics.OUT_LABEL', '运行效果', '效果块不再冒充参考答案'),
        ('metrics.OUT_OPEN', True, '效果块默认展开'),
        ('metrics.OUT_TXT_HAS_NAME', 'yes', '效果内容进来就可见'),
        ('metrics.OUT_HAS_RATE', 0, '效果块不给自评按钮'),
        ('metrics.OUT_HAS_ID', '', '效果块不占例题编号'),
        ('metrics.RATE_BARS', 2, '自评条 2 条＝2 道例题'),
        ('metrics.EX_GAUGE', '0/2', '自评分母是例题数，不是代码块数'),
        ('metrics.EX_CHIP_N', '2', '题头例题计数'),
        ('metrics.EXPAND_BTN', '收起全部答案', '按钮初始文案与默认展开一致'),
        ('metrics.BTN_AFTER_COLLAPSE', '展开全部答案', '收起后文案跟着变'),
        ('metrics.OPEN_N_COLLAPSED', 0, '可一键收起'),
        ('metrics.BTN_AFTER_REOPEN', '收起全部答案', '再点恢复'),
        ('metrics.OPEN_N_REOPENED', 3, '可一键展开'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动'),
    ],
    'review': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        ('metrics.TABS', 'due later fresh done', '四栏：该复习/稍后/未评价/已掌握'),
        ('metrics.TAB_COUNTS', '0/0/45/0', '空错题本时的分栏计数'),
        ('metrics.PANEL_ROLE', 'tabpanel', '分页无障碍角色'),
        ('metrics.START_BTN_EMPTY', 'absent', '没到期就不摆「开始复习」按钮'),
        ('metrics.DUE_EMPTY_TXT', '今天的复习做完了', '「该复习」空态文案'),
        ('metrics.FRESH_N', 45, '未自评例题数（2 个"运行效果"块不算题）'),
        ('metrics.FRESH_NO_DUE_TAG', 'clean', '未评价的题不挂到期标签'),
        ('metrics.FRESH_FIRST_LESSON', nonempty, '条目上的课程出处'),
        ('metrics.JUMP_HREF', '#/s1-l1', '跳转链接正确'),
        # 新标错的题当天就到期，所以会立刻出现在「该复习」
        ('metrics.DUE_COUNT_AFTER', '1', '新错题计入该复习'),
        ('metrics.BADGE_AFTER', '1', '侧栏徽章同步'),
        ('metrics.STORED_EX', '{"ex-s1-l1-1":-1}', '标记已持久化'),
        ('metrics.STORED_REV_KEYS', 1, '同时建了一条档期记录'),
        ('metrics.STORED_REV_DUE', 'today', '新错题的首次复习就在今天'),
        ('metrics.DUE_CARDS', 1, '该复习栏 1 条'),
        ('metrics.DUE_TAG_NOW', '今天到期', '到期标签'),
        ('metrics.START_BTN_NOW', '开始复习 1 道', '开复习按钮带上题量'),
        # 答案默认展开，所以先手动收起，再验证跳转确实会重新展开它
        ('metrics.PRE_COLLAPSED', 'true', '跳转前目标答案已被收起'),
        ('metrics.JUMPED_OPEN', True, '跳转后答案自动展开'),
        ('metrics.JUMPED_FLASH', True, '跳转后有高亮提示'),
        ('metrics.JUMPED_MARK', '-1', '跳转后标记保留'),
        ('metrics.JUMP_VISIBLE', 'yes', '跳转目标在视口内'),
        ('metrics.RATE_IN_JUMPED', 2, '跳转后可就地重评'),
        ('metrics.ANS_STATE_TXT', '待复习', '参考答案摘要行上的状态'),
    ],
    # 间隔复习：分栏 → 开一轮 → 答错回档 / 答对升档 / 走完全程毕业
    'spaced': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '对比度全部达标'),
        ('metrics.TABS', 'due later fresh done', '四栏：该复习/稍后/未评价/已掌握'),
        ('metrics.TAB_COUNTS', '3/1/41/0', '按到期日分栏，计数正确'),
        ('metrics.BADGE', '3', '徽章＝今天该复习数，不是错题总数'),
        ('metrics.DUE_CARDS', 3, '该复习栏 3 条'),
        ('metrics.DUE_FIRST_ID', 'ex-s1-l1-1', '欠得最久的排在最前'),
        ('metrics.OVERDUE_TAG', '欠了 2 天', '逾期时长标注'),
        ('metrics.NOW_TAGS', 2, '今天到期标注 2 条'),
        ('metrics.LADDER', '0/2/1/0/1', '阶梯五档分布'),
        ('metrics.LADDER_LABELS', '今天重做/1 天后/3 天后/7 天后/21 天后', '阶梯档位文案'),
        ('metrics.LATER_N', 1, '未到期的题落在「稍后」'),
        ('metrics.LATER_NO_OVERDUE', 'yes', '「稍后」里没有到期或逾期的题'),
        ('metrics.START_TXT', '开始复习 3 道', '开复习按钮带上题量'),
        ('metrics.BAR_IDLE', '0', '没复习时不显示会话栏'),
        ('metrics.BAR_ON', '1', '开复习后会话栏出现'),
        ('metrics.BAR_N', '1 / 3', '会话栏进度'),
        ('metrics.S1_HASH', '#/s1-l1', '跳到第一道所在的课'),
        ('metrics.S1_IDS', '["ex-s1-l1-1","ex-s1-l1-2","ex-s1-l3-0"]', '队列按到期先后排'),
        ('metrics.S1_FLASH_ID', 'ex-s1-l1-1', '定位到正确的那道题'),
        ('metrics.S1_OPEN', True, '自动展开答案'),
        # 答错 → 退回第一档，明天再来
        ('metrics.R1_REV', rev(0, 3, 1), '答错退回第一档，改到明天'),
        ('metrics.R1_MARK', '-1', '答错仍留在错题本里'),
        ('metrics.R1_MSG', '没关系 · 明天再来一次', '答错有明确反馈'),
        ('metrics.R1_DONE', '1', '会话推进一道'),
        # 答对 → 升一档
        ('metrics.S2_FLASH_ID', 'ex-s1-l1-2', '同一课内自动推进'),
        ('metrics.R2_REV', rev(3, 4, 7), '答对升一档，间隔拉到 7 天'),
        ('metrics.R2_MSG', '过关 · 7 天后再练一次', '升档有明确反馈'),
        ('metrics.R2_HASH', '#/s1-l3', '跨课推进到下一道'),
        # 过最后一关 → 毕业
        ('metrics.S3_FLASH_ID', 'ex-s1-l3-0', '定位到最后一关'),
        ('metrics.R3_HAS_REV', 'no', '毕业后档期记录清掉'),
        ('metrics.R3_MARK', '1', '毕业后转入已掌握'),
        ('metrics.R3_MSG', '这轮过了 3 道 · 全部清完', '收尾提示'),
        ('metrics.BAR_END', '0', '结束后收起会话栏'),
        ('metrics.SESSION_END', 'cleared', '会话状态已清'),
        ('metrics.BADGE_AFTER', '0', '复习完徽章归零'),
        ('metrics.TAB_AFTER', '0/3/41/1', '复习完各处计数一致'),
        ('metrics.STILL_DUE_SAME_DAY', 0, '同一天不会重复到期（连点也毕不了业）'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动'),
    ],
    'records': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '对比度全部达标'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.REC_CARDS', 4, '四张时长统计卡片'),
        ('metrics.PROG_CARDS', 8, '八张进度卡片（含作业三态）'),
        ('metrics.PROG_TXT', cards_contain('课程条目已完成', '今天该复习', '错题排队中',
                                          '例题已掌握', '例题未评价', '作业已完成',
                                          '作业还卡着', '作业还没动'),
         '进度卡片的八项口径齐全'),
        ('metrics.HM_CELLS', 126, '热力图 18 周 x 7 天'),
        ('metrics.HM_ROWS', 7, '热力图七行'),
        ('metrics.HM_TODAY', True, '今天有格子'),
        # 真实计时：只有可见且未闲置时累计
        ('metrics.VIS', 'visible', '页面可见'),
        ('metrics.TIME_AFTER_TICK', one_day_time(10), '10 秒心跳真实入账'),
        ('metrics.TICK_COUNTED', True, '计时被计数'),
        ('metrics.HM_TODAY_L_AFTER', '4', '热力图等级随时长变化'),
        ('metrics.STAT_TODAY_AFTER', '1 小时', '今日时长文案'),
        ('metrics.STAT_WEEK', stat_week(), '本周时长聚合'),
        ('metrics.STREAK_AFTER', '3天', '连续学习天数'),
        ('metrics.FMT', '1 小时|15 分|不到 1 分', '时长人性化格式'),
        # 复习阶梯小结：没错题不占地方，有错题才出现
        ('metrics.REC_NOTE_BEFORE', 'absent', '没有错题时不摆复习阶梯'),
        ('metrics.REC_NOTE_AFTER', 'present', '有错题后出现复习阶梯'),
        ('metrics.REC_NOTE_STEPS', '今天重做1/1天后0/3天后0/7天后0/21天后0', '阶梯小结的档位分布'),
        ('metrics.REC_DUE_CARD', '1道今天该复习', '进度卡片改为到期口径'),
        # 导出
        ('metrics.EXPORT_CLICKED', True, '导出可点击'),
        ('metrics.EXPORT_NAME', export_name, '导出文件名含日期'),
        ('metrics.EXPORT_TOAST', '学习记录已导出', '导出提示'),
        ('metrics.EXP_APP', 'python-learning-path', '导出内容标记来源'),
        ('metrics.EXP_VER', 4, '导出内容带版本号'),
        ('metrics.EXP_STATE_KEYS', 'done,ex,hw,last,miles,rev,theme,time', '导出包含全部状态'),
        ('metrics.EXP_REV', rev(0, 1, 0), '导出带上复习档期'),
        ('metrics.EXP_TIME', exp_time, '导出保留每日时长'),
        # 导入：并集合并
        ('metrics.IMPORT_DONE', 1, '导入完成进度'),
        ('metrics.IMPORT_HW', 1, '导入作业进度'),
        ('metrics.IMPORT_MILES', 1, '导入里程碑'),
        ('metrics.IMPORT_EX', 1, '导入错题标记'),
        ('metrics.IMPORT_TIME', 1200, '时长取最大值而非相加'),
        ('metrics.IMPORT_TOAST', '导入完成 · 合并新增 4 项进度', '导入提示含合并项数'),
        ('metrics.IMPORT_RERENDERED', True, '导入后界面刷新'),
        # 幂等：重复导入不翻倍
        ('metrics.IMPORT_TWICE_TIME', 1200, '重复导入时长不累加'),
        ('metrics.IMPORT_TWICE_TOAST', '导入完成 · 没有新内容需要合并', '重复导入提示'),
        ('metrics.IMPORT_TWICE_DONE', 1, '重复导入进度不变'),
        # 坏文件：安全中止
        ('metrics.IMPORT_BAD_TOAST', '导入失败：这个文件不是学习记录', '坏文件有明确报错'),
        ('metrics.IMPORT_BAD_SAFE', 'yes', '坏文件不改动现有数据'),
        # 清空：两段式确认
        ('metrics.CLR_ARMED', '1', '首次点击进入待确认态'),
        ('metrics.CLR_ARMED_TXT', '再点一次确认清空', '待确认文案'),
        ('metrics.CLR_STATE_INTACT', 1, '首次点击不清数据'),
        ('metrics.CLR_DONE_STATE', '{}', '二次点击才清空'),
        ('metrics.CLR_TOAST', '已清空全部学习记录', '清空提示'),
        ('metrics.CLR_BADGE_AFTER', '0', '清空后徽章归零'),
    ],
    'narrow430': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.GRID_COLS', '500px', '栅格塌缩为单列'),
        ('metrics.STAGE_COLS', 1, '课程卡片塌缩为单列'),
        ('metrics.SIDEBAR_POS', 'fixed', '侧栏转为抽屉'),
        ('metrics.MENU_BTN', 'grid', '汉堡按钮出现'),
        ('metrics.DRAWER_OPEN', '1', '抽屉可打开'),
        ('metrics.SCRIM_OPEN', '1', '遮罩层出现'),
        ('metrics.BODY_LOCKED', 'hidden', '抽屉锁滚动'),
        ('metrics.DRAWER_CLOSED', '0', '抽屉可关闭'),
        ('metrics.NO_HSCROLL_HOME', 'yes', '首页无横向滚动'),
        ('metrics.OVF_HOME', [], '首页无溢出'),
        ('metrics.SMALL_HOME', [], '首页触摸目标达标'),
        ('metrics.NO_HSCROLL_RV', 'yes', '错题本无横向滚动'),
        ('metrics.OVF_RV', [], '错题本无溢出'),
        ('metrics.SMALL_RV', [], '错题本触摸目标达标'),
        ('metrics.RV_CARD_DIR', 'column', '错题卡片转为纵向'),
        ('metrics.NO_HSCROLL_REC', 'yes', '学习记录无横向滚动'),
        ('metrics.OVF_REC', [], '学习记录无溢出'),
        ('metrics.SMALL_REC', [], '学习记录触摸目标达标'),
        ('metrics.HM_OVERFLOW_X', 'auto', '热力图可横向滚动'),
        ('metrics.RATE_H', 44, '自评按钮高 44px'),
        ('metrics.HINT_HIDDEN', 'none', '窄屏隐藏提示文案'),
        ('metrics.NO_HSCROLL_LESSON', 'yes', '课文页无横向滚动'),
        ('metrics.OVF_LESSON', [], '课文页无溢出'),
        ('metrics.SMALL_LESSON', [], '课文页触摸目标达标'),
        ('metrics.CT_SWEEP', [], '窄屏对比度全部达标'),
    ],
    'narrow768': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.SIDEBAR_POS', 'fixed', '侧栏转为抽屉'),
        ('metrics.DRAWER_OPEN', '1', '抽屉可打开'),
        ('metrics.DRAWER_CLOSED', '0', '抽屉可关闭'),
        ('metrics.NO_HSCROLL_HOME', 'yes', '首页无横向滚动'),
        ('metrics.OVF_HOME', [], '首页无溢出'),
        ('metrics.SMALL_HOME', [], '首页触摸目标达标'),
        ('metrics.NO_HSCROLL_RV', 'yes', '错题本无横向滚动'),
        ('metrics.OVF_RV', [], '错题本无溢出'),
        ('metrics.SMALL_RV', [], '错题本触摸目标达标'),
        ('metrics.NO_HSCROLL_REC', 'yes', '学习记录无横向滚动'),
        ('metrics.OVF_REC', [], '学习记录无溢出'),
        ('metrics.SMALL_REC', [], '学习记录触摸目标达标'),
        ('metrics.NO_HSCROLL_LESSON', 'yes', '课文页无横向滚动'),
        ('metrics.OVF_LESSON', [], '课文页无溢出'),
        ('metrics.SMALL_LESSON', [], '课文页触摸目标达标'),
        ('metrics.CT_SWEEP', [], '窄屏对比度全部达标'),
    ],
    # 状态里混入"内容改版后残留"的幽灵题目 id 时，各处计数必须一致
    'exstale': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '对比度全部达标'),
        ('metrics.BADGE_ZERO', '0', '徽章处于显示态'),
        ('metrics.BADGE', '2', '只有 2 条真实错题'),
        ('metrics.TAB_DUE_CNT', '2', '页签计数与徽章一致'),
        ('metrics.DUE_CARDS', 2, '卡片数与计数一致'),
        ('metrics.DUE_TAB_ARIA', 'true', '默认落在该复习页'),
        # v2 老数据升上来：没有档期记录的错题要立刻到期，不能被新功能吞掉
        ('metrics.KEY_UPGRADED', 'yes', '已写入 v3 存储键'),
        ('metrics.MIGRATED_DUE', 'yes', '老错题迁移后今天就能复习'),
    ],
    # 作业入复习闭环：卡住的作业和例题共用一套档期，但说法与判定语义要各自正确
    'hwstuck': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '对比度全部达标'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动'),
        # 两类欠债混排在同一个队列，各带来源徽章
        ('metrics.KINDS', 'ex hw', '例题与作业同队列'),
        ('metrics.BADGES', '作业 例题', '各带来源徽章'),
        ('metrics.HW_LABELS', '做出来了|还是卡住', '作业用作业的说法'),
        ('metrics.EX_LABELS', '写对了|没写出来', '例题用例题的说法'),
        ('metrics.HW_GO_TXT', '去重做', '作业是「去重做」不是「去复习」'),
        ('metrics.HW_LATE', 1, '欠着的作业带逾期标记'),
        # 两条守恒式各自成立
        ('metrics.EX_CONSERVE', '1+44+0=45', '例题口径守恒'),
        ('metrics.HW_CONSERVE', '1+0+%d=%d' % (HW_TOTAL - 1, HW_TOTAL), '作业口径守恒'),
        ('metrics.POOL', '1/1', '两边各一条欠债'),
        ('metrics.TAB_COUNTS', '2/0/44/0', '四栏计数'),
        # 「去重做」回到那一课并高亮那条作业
        ('metrics.HASH', '#/s1-l1', '跳回所属课时'),
        ('metrics.TARGET_TAG', 'LI', '目标是一条 li，不是折叠块'),
        ('metrics.TARGET_FLASH', True, '目标被点亮'),
        ('metrics.TARGET_STATE', 'stuck', '目标呈现卡住态'),
        ('metrics.TARGET_STUCK_PRESSED', 'true', '卡住按钮呈按下态'),
        ('metrics.TARGET_TICK', 'false', '卡住不等于已完成'),
        # 判定语义：连对 4 次再答对一次＝毕业，而且必须留下"已做"这条记录
        ('metrics.TOAST', '练了 6 次 · 这道题毕业了，已移出错题本', '毕业提示'),
        ('metrics.MARK_AFTER', 1, '判定型评分留下 1，而不是把标记抹掉'),
        ('metrics.HW_DONE', 1, '作业计入已完成'),
        ('metrics.HW_POOL_AFTER', 0, '毕业后退出错题池'),
        ('metrics.HW_GONE', 0, '卡住卡片消失'),
        ('metrics.HW_CONSERVE_AFTER', '0+1+%d=%d' % (HW_TOTAL - 1, HW_TOTAL),
         '毕业后作业口径仍守恒'),
    ],
    'quiz': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.CT_SWEEP', [], '对比度全部达标（作答页）'),
        ('metrics.CT_SWEEP_SETUP', [], '对比度全部达标（设置页）'),
        ('metrics.CT_SWEEP_RES', [], '对比度全部达标（成绩单）'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动'),
        # 抽题索引的口径必须和错题本一字不差——对不上，自测判的错就落不到错题本上
        ('metrics.QUIZ_N', 45, '抽题索引覆盖全部 45 道例题'),
        ('metrics.EX_N', 45, '与错题本的例题口径一致'),
        ('metrics.IDS_MATCH', 'yes', '两套索引的 id 集合完全相同'),
        ('metrics.Q_EMPTY', 0, '每道题都有题面'),
        ('metrics.A_EMPTY', 0, '每道题都有参考答案'),
        ('metrics.LEAK', 0, '题面里不含答案（一标题多答案的那两道最容易犯）'),
        ('metrics.MULTI_TITLE', 2, '同标题的两道答案各自标了 (1/2)(2/2)'),
        # 内容质量闸门：2026-09-21 之前阶段二/三有 28 道例题只挂标题、没有题面，
        # 抽题自测抽到它们等于印个标题给你猜。已全部补齐，此后谁新增例题却忘了写
        # 任务描述，这条断言会直接把他拦下来。
        ('metrics.BARE_N', 0, '没有「只有标题」的例题——45 道题面齐全'),
        ('metrics.BARE_HINT_MATCH', 'yes', '「只有标题」的提示与当前这道题的实际相符（0 道裸题时=两边都空）'),
        ('metrics.FOOT_HREF', site_link, '卡片上有回课文的链接（具体指向随机）'),
        ('metrics.FOOT_ITEM_OK', 'yes', '链接指向当前这道题所属的课时'),
        # 分层抽样：会了 → 0，没表态 → 1，错题本里 → 2
        ('metrics.TIER_MASTERED', 0, '标过「已掌握」的排在最前'),
        ('metrics.TIER_FRESH', 1, '没表过态的排第二'),
        ('metrics.TIER_POOL', 2, '已在错题本循环里的排最后'),
        ('metrics.COLD_CHIP', '16', '设置页如实报出"自评会了却没复核"的道数'),
        ('metrics.SCOPE_OPTS', 6, '范围可选：已学过 / 全部 + 4 个阶段'),
        ('metrics.SEG_SIZES', '5 题/10 题/20 题', '题量档位'),
        ('metrics.SEG_SRC', '混合/只例题/只作业', '题源档位'),
        # 组卷结果：这个种子里 s1 的 16 道全是 T0，所以抽出来的必然全是 T0
        ('metrics.HASH', '#/quiz', '自测在独立页面里进行'),
        ('metrics.QZ_N', 5, '按设定抽了 5 道'),
        ('metrics.ROW_TIERS', '00000', '五道全是"最久没被检验"的那一层'),
        ('metrics.ROW_KINDS', 'ex,ex,ex,ex,ex', '题源=只例题时不会混进作业'),
        ('metrics.ROW_HAS_A', 5, '每道都带着参考答案'),
        # 出题时答案必须是遮住的——这是自测成立的前提
        ('metrics.ANS_HIDDEN', 'yes', '答案初始不可见'),
        ('metrics.ANS_DISPLAY', 'none', '答案的计算样式确实是 display:none'),
        ('metrics.RATE_HIDDEN', 'yes', '自评按钮也要等揭示后才出现'),
        ('metrics.RATE_DISPLAY', 'none', '自评按钮的计算样式确实是 display:none'),
        ('metrics.ACT_SHOWN', 'yes', '先看到的是「看参考答案」'),
        ('metrics.REVEAL_TXT', '看参考答案', '例题按钮文案'),
        ('metrics.COUNT_TXT', '1 / 5', '进度计数'),
        ('metrics.WARN_BADGE', '你标过「会了」', '标记出"这道是你自认为会的"'),
        # 揭示
        ('metrics.ANS_AFTER', 'visible', '点过之后答案才出现'),
        ('metrics.ANS_DISPLAY_AFTER', 'block', '计算样式同步变为可见'),
        ('metrics.RATE_AFTER', 'visible', '自评按钮随之出现'),
        ('metrics.ACT_AFTER', 'hidden', '揭示按钮随即收起'),
        ('metrics.ANS_CODE', 1, '答案里有代码块'),
        ('metrics.ANS_TOUCH', 'ok,ok', '自评按钮触摸目标达标'),
        # 核心机制：答错一道「已掌握」的题 → 退回错题本、今天重做
        ('metrics.W_MARK', '-1', '从已掌握退回错题本'),
        ('metrics.W_DUE_NOW', 'yes', '退回后今天就到期'),
        ('metrics.W_MSG', '本来在「已掌握」里 · 已退回错题本，今天就重做', '说清发生了什么'),
        ('metrics.W_IDX', '1', '评完自动推进下一道'),
        ('metrics.W_NEXT_HIDDEN', 'yes', '下一道的答案重新遮住'),
        # 答对：复核通过，状态不动
        ('metrics.R2_MARK', '1', '答对后仍在已掌握'),
        ('metrics.R2_MSG', '复核通过 · 确实会了', '答对的提示'),
        # 跳过：一动不能动
        ('metrics.SKIP_MARK', '1', '跳过不改状态'),
        ('metrics.SKIP_IDX', '3', '跳过也会推进'),
        # 成绩单
        ('metrics.RES_SHOWN', 'yes', '成绩单出来了'),
        ('metrics.RES_SCORE', '1/2', '只统计答过的题，跳过的分母不算'),
        ('metrics.RES_ROWS', 3, '三行记录：错 / 对 / 跳过'),
        ('metrics.RES_MARKS', 'no,ok,skip', '三种结局各自标出来'),
        ('metrics.OVF_RES', [], '成绩单页无横向溢出'),
        ('metrics.SMALL_RES', [], '成绩单页触摸目标达标'),
        # 再来一组
        ('metrics.AGAIN_N', '5', '同一设置重新抽 5 道'),
        ('metrics.AGAIN_IDX', '0', '回到第一题'),
        ('metrics.AGAIN_CARD', 'yes', '直接进入作答页'),
        # 收尾：三种结局落到错题本/已掌握的正确栏位
        ('metrics.DUE_HAS_DEMOTED', 1, '答错的落在"该复习"里'),
        ('metrics.DONE_HAS_OK', 1, '答对的留在"已掌握"里'),
        ('metrics.DONE_HAS_SKIP', 1, '跳过的原地不动'),
        ('metrics.POOL_TOTAL', 3, '错题池 = 退回的 1 道 + 种子里原有的 2 道'),
    ],
    # 首页「今日计划」。种子刻意让前三张卡有活、第四张没有——data-on 的两种
    # 取值同页出现，「箭头与开关成对」才有区分度；全亮的话把 data-on 写死成
    # "1" 也能蒙混过关。
    'today': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.PLAN_CARDS', 4, '四张行动卡'),
        ('metrics.PLAN_KEYS', 'due,next,quiz,time', '身份与顺序固定：欠债 → 推进 → 复核 → 节奏'),
        ('metrics.PLAN_HREFS', '#/review #/s1-l5 #/quiz #/records', '各自指向该去的地方'),
        ('metrics.PLAN_LABELS', '今天该复习/条件判断/标了「已掌握」/连续学习', '标题：动作 / 内容 / 状态 / 节奏'),
        ('metrics.PLAN_DATE', nonempty, '有日期'),
        ('metrics.PLAN_LEAD', nonempty, '有导语'),
        # 开关与箭头：属性写了、样式没跟上，两种错都要拦
        ('metrics.CARD_ON', '1,1,1,0', '前三张有活、第四张没有（离线态也覆盖到了）'),
        ('metrics.ARROW_MATCH', 'yes', '箭头与 data-on 成对，没活的卡不挂箭头'),
        # 卡上的数字不许是另算的一份，必须落回底层口径
        ('metrics.DUE_MATCH', 'yes', '「该复习」＝ revStats().due'),
        ('metrics.QUIZ_MATCH', 'yes', '「已掌握」＝ revStats().doneEx'),
        ('metrics.NEXT_MATCH', 'yes', '「下一个知识点」＝课程顺序里第一个没完成的条目'),
        ('metrics.TRIO_DUE', '2,2,2', '侧栏徽章 / 计划卡 / revStats 三处同数'),
        ('metrics.PLAN_VS_BENCH', 'yes', '四张卡完全由 todayPlan() 派生，渲染层没二次加工'),
        # 毕业卡在这种状态下**不该出现**：课程没走完、毕业项目也没开工。
        # 这条是负向对照——只验"该出现时出现"不算数，还得验"不该出现时不出现"。
        ('metrics.GRAD_SHOW_MATCH', 'yes', '毕业卡的有无与 gradProgress().show 一致'),
        ('metrics.GRAD_CARD', 'absent-ok', '课程未走完且未开工 → 不催毕业'),
        # 点得到
        ('metrics.CLICK_HASH', '#/review', '点「该复习」落到错题本'),
        ('metrics.CLICK_PAGE', 'review', '落地页真的是错题本'),
        # 布局与无障碍
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        ('metrics.DARK_CT_SWEEP', [], '深色对比度全部达标'),
        ('metrics.CT_LEAD', at_least(4.5), '导语对比度'),
        ('metrics.CT_L', at_least(4.5), '卡片标题对比度'),
        ('metrics.CT_NOTE', at_least(4.5), '卡片副行（本页最小字号）对比度'),
        ('metrics.DARK_CT_NOTE', at_least(4.5), '深色下副行对比度'),
    ],
    # 「该毕业了」提示（课程走完、毕业项目一项没勾）。
    # 这是个**派生视图**：不新增状态表，全部由 gradProgress() 从既有 hw 表算出来。
    # 断言的重点不是那几句话写得对不对，而是**卡上的每个数都回到 gradProgress**。
    'gradplan': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.COURSE_DONE', '1', '正课 + 阶段项目全完成'),
        ('metrics.STARTED', '0', '毕业项目还没开工'),
        ('metrics.SHOW', '1', '条件成立 → 该催了'),
        ('metrics.T', 9, '整页口径：三组各 3 项'),
        ('metrics.N', 0, '一项没勾'),
        ('metrics.FULL', '0', '离达成还远'),
        ('metrics.CARD', 'present', '卡片出现了'),
        ('metrics.CARD_N', 5, '五张卡（比平时多一张）'),
        ('metrics.KEYS', 'due,next,grad,quiz,time', '它是里程碑卡，插在「推进」与「复核」之间'),
        ('metrics.GRAD_BEFORE_QUIZ', 'yes', '卡序：排在推进之后、复核之前'),
        ('metrics.CARD_LABEL', '该做毕业项目了', '未开工时的语气是"该做"，不是"进行中"'),
        ('metrics.CARD_NOTE', nonempty, '有引导文案'),
        ('metrics.CARD_HREF', '#/s4-毕业项目-三选一', '指向毕业项目页'),
        ('metrics.CARD_DONE', '0', '没达成就不挂完成态'),
        ('metrics.CARD_ON', '1', '这张卡是活的'),
        # 数字不许是另算的一份
        ('metrics.N_MATCH', 'yes', '卡上数字 ＝ gradProgress().n/t'),
        ('metrics.DONE_MATCH', 'yes', 'data-done 与 gradProgress().full 成对'),
        ('metrics.LEAD', nonempty, '有导语'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        ('metrics.DARK_CT_SWEEP', [], '深色对比度全部达标'),
        ('metrics.CT_N', at_least(4.5), '卡片数字对比度'),
        ('metrics.CT_L', at_least(4.5), '卡片标题对比度'),
        ('metrics.CT_NOTE', at_least(4.5), '卡片副行（本页最小字号）对比度'),
        ('metrics.DARK_CT_NOTE', at_least(4.5), '深色下副行对比度'),
        # 从首页点过去要真的落到毕业项目页，不是"挂个 href 就算"
        ('metrics.CLICK_HASH', '#/s4-%E6%AF%95%E4%B8%9A%E9%A1%B9%E7%9B%AE-%E4%B8%89%E9%80%89%E4%B8%80',
         '点卡片落到毕业项目页'),
        ('metrics.CLICK_PILLS', 3, '落地页真的是毕业页（三枚进度芯片在）'),
    ],
    # 九项验收全过 → 同一张卡翻成「已达成」，文案与完成态都要换。
    # 和 gradplan 共用一份探针，差别只在种子；两条一起看才说明"三种态互相区分"。
    'gradplanFull': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.N', 9, '九项全过'),
        ('metrics.T', 9, '分母没变'),
        ('metrics.LEFT', 0, '不欠了'),
        ('metrics.STUCK', 0, '没有卡住的'),
        ('metrics.FULL', '1', '整页口径满格'),
        ('metrics.SHOW', '1', '达成后仍然在（是成绩单，不是催促）'),
        ('metrics.CARD', 'present', '卡片在'),
        ('metrics.CARD_LABEL', '毕业项目已达成', '语气从催办翻成收尾'),
        ('metrics.CARD_DONE', '1', '挂上完成态'),
        ('metrics.N_MATCH', 'yes', '数字仍与 gradProgress 同源'),
        ('metrics.DONE_MATCH', 'yes', '完成态与 gradProgress().full 成对'),
        # 与 gradplan 成对：两页的 KEYS 必须一模一样，否则"卡序固定"是句空话
        ('metrics.KEYS', 'due,next,grad,quiz,time', '卡序不随状态变'),
        ('metrics.GRAD_BEFORE_QUIZ', 'yes', '仍排在复核之前'),
        # 达成态是渐变底 + 强调色描边，是最容易把对比度做塌的地方
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        ('metrics.DARK_CT_SWEEP', [], '深色对比度全部达标'),
        ('metrics.CT_N', at_least(4.5), '达成态数字对比度'),
        ('metrics.CT_L', at_least(4.5), '达成态标题对比度'),
        ('metrics.CT_NOTE', at_least(4.5), '达成态副行对比度'),
        ('metrics.DARK_CT_NOTE', at_least(4.5), '深色下达成态副行对比度'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.CLICK_PILLS', 3, '点过去仍是毕业页'),
    ],
    # 毕业项目：三组验收标准并排，各自记账。这是全课程唯一决定"能不能毕业"
    # 的东西，也是唯一一个页面里挂着多张清单的地方。
    'grad': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        # 页面身份按 kind 认，不按 slug 猜
        ('metrics.GRAD_EXISTS', True, '存在 kind=grad 的页面'),
        ('metrics.GRAD_LABEL', '毕业项目', '页面类型的叫法'),
        ('metrics.GRAD_NOUN', '验收', '这一页说的是「验收」，不是「作业」'),
        # 一页三张清单
        ('metrics.LISTS', 3, '三个项目各一组验收标准'),
        ('metrics.ITEMS', 9, '3 组 × 3 条'),
        ('metrics.PER_LIST', '3,3,3', '每组的条数'),
        ('metrics.COUNTER_RESET', 'hw 0,hw 0,hw 0', '视觉编号按清单各自从 01 起'),
        # id 必须全页唯一，且与作业索引逐一对上——按清单内序号编就会撞车
        ('metrics.IDS_N', 9, '九条都有 id'),
        ('metrics.IDS_UNIQUE', 9, 'id 全页唯一（否则勾一组等于勾三组）'),
        ('metrics.IDS_SEQ', 'yes', 'id 是 <页面 id>:0..8 的连续序号'),
        ('metrics.IDS_DOM_EQ_INDEX', 'yes', 'DOM 写的 id 与作业索引逐一对上'),
        # 回归：tasks 规则曾拼出 `<ol class="hw-list">>`，页面会多一个游离的 '>'
        ('metrics.STRAY_GT', 0, '列表里没有游离的尖括号残留'),
        # 三组进度芯片
        ('metrics.PILLS', 3, '三组各一枚进度芯片'),
        ('metrics.PILL_N', '2,0,3', '各组达成条数'),
        ('metrics.PILL_T', '3,3,3', '各组总数'),
        ('metrics.PILL_FULL', '0,0,1', 'data-full 两种取值同页出现，写死一个值蒙混不过去'),
        ('metrics.PILL_TXT', '2 / 3|0 / 3|🎓 已达成', '未达成报分数、达成报「已达成」'),
        ('metrics.PILL_IN_H3', 3, '芯片挂在项目标题里，不是浮在别处'),
        ('metrics.PILL_GROUP', 'g0,g1,g2', '每组芯片认得自己那张清单'),
        # 页头口径
        ('metrics.HW_TXT', '5/9', '本页已完成 5 条'),
        ('metrics.HW_STUCK', '1', '卡住那条被计入'),
        ('metrics.HW_GAUGE_LABEL', '验收', '进度条的标题也随页面语义走'),
        ('metrics.EXPAND_BTN', 'absent', '这页没有答案，就不该挂「展开全部答案」'),
        ('metrics.DONE_BTN', 'present', '整页「标记为已完成」仍在'),
        ('metrics.CRUMB', '毕业项目', '面包屑用新的类型名'),
        # 勾一条：只有它所属的那一组该变
        ('metrics.AFTER_N', '3,0,3', '第一组被勾满'),
        ('metrics.AFTER_FULL', '1,0,1', '只有第一组变成已达成'),
        ('metrics.AFTER_TXT', '🎓 已达成', '满格文案'),
        ('metrics.AFTER_OTHERS_TXT', '0 / 3|🎓 已达成', '另外两组不受影响'),
        ('metrics.AFTER_HWTXT', '6/9', '整页计数跟着走'),
        ('metrics.AFTER_STORED', '1', '标记落进 hw 表'),
        # 再点一次＝记录型，可撤销
        ('metrics.UNDO_FULL', '0,0,1', '撤销后回到未达成'),
        ('metrics.UNDO_TXT', '2 / 3', '文案退回分数'),
        ('metrics.UNDO_STORED', '0', '撤销后标记被清掉'),
        ('metrics.HW_TOTAL', HW_TOTAL, '项目交付要求也算进作业总数'),
        ('metrics.CONSERVE', '1+5+%d' % (HW_TOTAL - 6), '两条标记两条口径都守恒'),
        # 芯片两种状态的对比度，浅色深色各自扫一遍
        ('metrics.CT_PILL', at_least(4.5), '未达成芯片对比度'),
        ('metrics.CT_PILL_FULL', at_least(4.5), '已达成芯片对比度'),
        ('metrics.CT_HW', at_least(4.5), '验收条目正文对比度'),
        ('metrics.DARK_CT_PILL', at_least(4.5), '深色下未达成芯片对比度'),
        ('metrics.DARK_CT_PILL_FULL', at_least(4.5), '深色下已达成芯片对比度'),
        ('metrics.DARK_CT_SWEEP', [], '深色对比度全部达标'),
        ('metrics.THEME_BACK', 'yes', '主题可切回'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
    ],
    # 阶段页（#/s1…#/s4）。补这个场景的直接原因：原来的 17 个场景**从不访问阶段页**，
    # 于是 refreshProgress 里那个 TypeError 一直没被守住。断言刻意"成对"：
    # 既要确认修好了（无报错、焦点归位），也要确认没修过头
    # （课时卡没被写上阶段合计）。
    'stage': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        # 场景 hash 就落在 #/s2，所以这一条能抓住「启动期渲染」抛的错
        ('metrics.__HASH', '#/s2', '场景确实停在阶段页上'),
        ('metrics.__BOOT_ERR', [], '启动期渲染无 JS 报错（修复前这里是 TypeError）'),
        ('metrics.__ERRS_N', 0, '四页走完累计 0 报错'),
        ('metrics.__ERRS_AFTER_WALK', 0, '换页过程中没有新增报错'),
        ('metrics.STAGE_N', 4, '四个阶段页都走到了'),
        ('metrics.STAGE_H1_MATCH', True, '每页标题 = 该阶段名称（没悄悄回落首页）'),
        ('metrics.STAGE_NO_HOME_FALLBACK', True, '阶段页不渲染首页的阶段网格'),
        ('metrics.STAGE_CARDS_POS', True, '每页都列出了本阶段内容'),
        # 反方向：课时卡的状态只该是「已完成 / 未开始」，出现 "n / m"
        # 就说明阶段合计被写到课时卡上了（修过头）
        ('metrics.STAGE_NO_TOTAL_ON_CARD', True, '课时卡没被写上阶段合计'),
        ('metrics.STAGE_FOCUS',
         'MAIN#contentRoot,MAIN#contentRoot,MAIN#contentRoot,MAIN#contentRoot',
         '换页后焦点都落到正文'),
        ('metrics.STAGE_FOCUS_OK', True, '焦点归位契约成立'),
        # 阶段页也一并纳入几何与对比度的常规扫描（四页合并上报）
        ('metrics.OVF', [], '四页均无横向溢出'),
        ('metrics.SMALL', [], '四页触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '四页均无横向滚动条'),
        ('metrics.CT_SWEEP', [], '四页浅色对比度全部达标'),
    ],
    # 窄屏版：只验"有没有塌成单列、有没有把页面撑破"。
    # 功能态由 grad 场景在宽屏下验，两边不重复数数。
    'grad430': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.LISTS', 3, '三组清单都在'),
        ('metrics.ITEMS', 9, '九条都渲染了'),
        ('metrics.PILLS', 3, '三枚芯片都在'),
        ('metrics.TICK_W', 44, '勾选框触摸目标 44px'),
        ('metrics.STUCK_H', 44, '「卡住」按钮触摸目标 44px'),
        ('metrics.H3_WRAP', 'inside', '芯片没从项目标题里挤出去'),
        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.CT_SWEEP', [], '对比度全部达标'),
    ],
    # 「按目标选方向」：静态对照表 → 可点的卡片。
    # 重点不是卡片长什么样，而是**内容真的来自那张表**、**链接真的指向方向页**。
    'picker': [
        ('has_probe', True, '探针注入成功'),
        ('metrics.__ALIVE', 1, '脚本未崩'),
        ('metrics.__DONE', 1, '流程跑完'),
        ('metrics.__ERRS_N', 0, '无 JS 报错'),
        ('metrics.GRID', 'present', '卡片网格已渲染'),
        ('metrics.TABLE_LEFT', 0, '表格被卡片取代，不是两样并存'),
        ('metrics.CARDS', 5, '五个目标各一张卡'),
        ('metrics.DIRS', 'a,b,c,d,e', '每张卡认得自己那条方向'),
        ('metrics.LETTERS', 'A,B,C,D,E', '字母徽章'),
        ('metrics.NAMES', '数据分析|Web 开发|自动化办公|爬虫|AI 应用开发', '方向名取自表格'),
        ('metrics.WHY_N', 5, '每张卡都有一句理由'),
        # 「看知识点」是展开的**入口暗示**：五张卡都得有，否则用户不知道卡片还能点开
        ('metrics.GO_TXT', ('去看这个方向 →看知识点|去看这个方向 →看知识点|'
                            '去看这个方向 →看知识点|去看这个方向 →看知识点|'
                            '去看这个方向 →看知识点'), '出口文案 + 展开暗示'),
        # 卡片必须留在正文最前：原来是表格的位置
        ('metrics.GRID_FIRST', 'yes', '卡片网格占据原表格的位置'),
        # 链接必须真的落到存在的方向页上，不是"随便挂个 href"
        ('metrics.HREF_N', 5, '五个去处互不重复'),
        ('metrics.HREF_KINDS', 'direction,direction,direction,direction,direction',
         '去处都真的是方向页'),
        ('metrics.HREF_LETTERS', 'a,b,c,d,e', '字母与去处一一对应'),
        ('metrics.TITLE', '怎么选方向', '页面标题'),
        ('metrics.LABEL', '选方向', '页面类型的叫法'),
        ('metrics.COLS', at_least(2), '宽屏下多列（手机端塌成单列另有截图）'),
        # 这一页没有答案也没有作业，那两个控件不该出现
        ('metrics.EXPAND_BTN', 'absent', '没有答案就不挂「展开全部答案」'),
        ('metrics.HW_GAUGE', 'absent', '没有作业就不挂进度条'),
        ('metrics.DONE_BTN', 'present', '整页「标记为已完成」仍在'),

        # ---- 就地展开：点卡片不跳页，而是在它自己下方长出那块内容 ----
        # 初态：一格都不展开，展开区是**空壳**（不是没建，是建了但空着且 hidden）
        ('metrics.X_OPEN0', 0, '初始没有一格是展开的'),
        ('metrics.X_VISIBLE0', 0, '初始没有一块展开区是可见的'),
        ('metrics.X_EMPTY0', 5, '初始五块展开区都是空的（内容懒建）'),
        ('metrics.ARIA0', 5, '五张卡都写着 aria-expanded=false'),
        # 展开区必须挂在卡片自己那一格里，否则宽屏下会把整行重排
        ('metrics.X_IN_ITEM', 'yes', '展开区挂在卡片自身的格子里'),
        # 宽屏多列时展开区不许压到邻格上——量矩形相交，不靠肉眼。
        # grid 子项默认 min-width:auto，卡片里那行较长的目标文案会把它的最小宽度
        # 顶到几百像素，于是卡片比自己的格子还宽、展开区跟着压上邻居（真踩过）。
        ('metrics.X_NO_COVER', 0, '展开区没有压在邻格上'),
        ('metrics.X_WITHIN_ITEM', 'yes', '展开区不超出自己那一格'),
        ('metrics.X_ROW_ALIGNED', 'yes', '同排邻居顶边齐平（只撑高本行）'),
        ('metrics.OPEN1', '1', '点一下卡片就展开'),
        ('metrics.CARD_OPEN1', '1', '卡片自己也记着展开态'),
        # 数据 + 派生属性成对
        ('metrics.ARIA1', 'true', 'aria-expanded 跟着变成 true'),
        ('metrics.X_SHOWN1', 'yes', '展开区真的显示出来了'),
        ('metrics.STAY_HASH', 'yes', '路由没动——是就地展开，不是跳页'),
        ('metrics.ONLY_ONE_OPEN', 1, '一次只展开一格'),
        # 展开区里必须是真的「课文那几节」，不是一段随便的文字
        ('metrics.X_H4', '路线|核心知识点|示例：groupby 聚合|练习题', '四节小标题齐备'),
        ('metrics.X_CODE', at_least(1), '示例代码块跟着一起进来了'),
        ('metrics.X_CODEBAR', at_least(1), '代码块的语言标签/复制条也重新挂上了'),
        ('metrics.X_TICKS', 4, '练习题可以就地勾选'),
        ('metrics.X_STUCK', 4, '练习题也能就地标「卡住」'),
        ('metrics.X_LI', 4, '四道练习题都在'),
        ('metrics.X_LINK', '#/s4-dira', '右上角仍能跳去完整方向页'),
        # id 与全局索引必须对得上，否则勾了不进错题本/自测
        ('metrics.X_IDS_IN_INDEX', 'yes', '展开区的作业 id 全在全局索引里'),
        ('metrics.X_IDS_UNIQUE', 0, '每个 id 在索引里只登记一次'),
        ('metrics.X_ID_DOM_DUP', 0, '展开区没有与页面别处撞的 id'),
        ('metrics.HW_TOTAL_STABLE', HW_TOTAL, '展开不改变全局作业口径'),

        # ---- 就地勾选：与课时页同一张表、同一个口径 ----
        ('metrics.SEED_STATES', 'done,stuck,todo,todo', '种子预置的三种态渲染正确'),
        ('metrics.SEED_CHECKED', '1,0,0,0', '勾选框只跟着「搞定」走，「卡住」不勾'),
        ('metrics.SEED_STUCK_ARIA', 'false,true,false,false', 'aria-pressed 与卡住成对'),
        ('metrics.SEED_PROG', '已做 1 / 4', '「已做 x / n」初值'),
        ('metrics.SEED_PROG_MATCH', 'yes', '进度数字就是从 li 状态数出来的'),
        ('metrics.X3_STATE', 'done', '就地勾选生效'),
        ('metrics.X_STATES3', 'done,stuck,done,todo', '三种态可同页并存'),
        ('metrics.X_PROG_DONE', '已做 2 / 4', '勾完进度立刻更新'),
        ('metrics.X_HWDONE', 2, '底层 hw 表同步'),
        # 点第二次＝改主意，不是把题删了——见 rateEx 的注释
        ('metrics.UNSTUCK_BEFORE', 'stuck', '先确认那条本来就是「卡住」'),
        ('metrics.UNSTUCK_STATE', 'todo', '再点一次卡住＝撤销，退回未表态'),
        ('metrics.UNSTUCK_ARIA', 'false', 'aria-pressed 同步撤销'),

        # ---- 收起的三个入口 ----
        ('metrics.ESC_NAV_WORKS', 'yes', '展开区可聚焦（否则 Esc 是空放）'),
        ('metrics.ESC_CLOSED', '0', 'Esc 收起'),
        ('metrics.ESC_HIDDEN', 'yes', 'Esc 之后展开区真的藏了'),
        ('metrics.ESC_ARIA', 'false', '收起时 aria-expanded 也回退'),
        ('metrics.ESC_TXT', '去看这个方向 →', '收起后提示文案还原'),
        # 反复开合不许把内容越堆越多，也不许把勾选清掉
        ('metrics.REOPEN_N', 5, '反复开合没有多长出展开区'),
        ('metrics.REOPEN_H4', 4, '反复开合小标题没重复'),
        ('metrics.REOPEN_TICKS', 4, '反复开合勾选框没重复'),
        ('metrics.REOPEN_MARK_KEPT', 2, '收起再打开，已有勾选不丢'),

        # ---- 一次性口令：从别处跳过来并就地展开 ----
        ('metrics.PENDING0', 'null', '没有待办口令时不预展开'),
        ('metrics.JUMP_OPEN', 1, '口令跳转后恰好展开一格'),
        ('metrics.JUMP_DIR', 'c', '展开的正是口令指的那条方向'),
        ('metrics.JUMP_CONSUMED', 'null', '口令用完即清'),
        ('metrics.JUMP_TICKS', at_least(1), '口令展开的格子里作业也装饰好了'),
        # 不清的话，下次进本页会莫名其妙展开一格
        ('metrics.JUMP_NOT_LATCHED', 0, '重渲染后不会残留展开态'),

        ('metrics.OVF', [], '无横向溢出'),
        ('metrics.SMALL', [], '触摸目标均 >=44px'),
        ('metrics.NO_HSCROLL', 'yes', '无横向滚动条'),
        ('metrics.CT_GOAL', at_least(4.5), '目标标题对比度'),
        ('metrics.CT_DIR', at_least(4.5), '方向名对比度'),
        ('metrics.CT_WHY', at_least(4.5), '理由对比度'),
        ('metrics.CT_GO', at_least(4.5), '出口文案（本页最小字号）对比度'),
        ('metrics.CT_SWEEP', [], '浅色对比度全部达标'),
        # 深色下展开区必须有一格开着才量得到——空扫会假装通过
        ('metrics.DARK_THEME', 'dark', '深色确实切过去了'),
        ('metrics.DARK_X_BUILT', at_least(1), '深色扫描时展开区真的开着'),
        ('metrics.CT_X_H', at_least(4.5), '深色：展开区标题对比度'),
        ('metrics.CT_X_PROG', at_least(4.5), '深色：已做 x / n 对比度'),
        ('metrics.CT_X_MT', at_least(4.5), '深色：小结标题对比度'),
        ('metrics.CT_X_LINK', at_least(4.5), '深色：完整页链接对比度'),
        ('metrics.CT_X_CODE', at_least(4.5), '深色：展开区代码对比度'),
        ('metrics.DARK_CT_SWEEP', [], '深色对比度全部达标'),
    ],
}


def dig(obj, path):
    cur = obj
    for seg in path.split('.'):
        if isinstance(cur, dict):
            if seg not in cur:
                return '<缺失>'
            cur = cur[seg]
        else:
            return '<缺失>'
    return cur


def fmt(v):
    if isinstance(v, list):
        return '[]' if not v else json.dumps(v, ensure_ascii=False)
    if callable(v):
        return getattr(v, '__doc__', None) or '<自定义条件>'
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v


total = fail = 0
RESULTS = {}   # 场景 -> 原始结果，供**跨场景**一致性检查取用（跨场景的对照见 gradplanFull）
for sc in ORDER:
    p = os.path.join(D, f'_browser_{sc}.json')
    print('=' * 66)
    if not os.path.exists(p):
        print(f'场景 {sc}: 结果文件缺失 -> 视为失败')
        fail += 1
        continue
    try:
        data = json.load(open(p, encoding='utf-8'))
    except Exception as e:
        print(f'场景 {sc}: 结果解析失败 {e}')
        fail += 1
        continue
    RESULTS[sc] = data
    m = data.get('metrics', {})
    print(f'场景 {sc}  viewport={data.get("viewport")}  DOM={data.get("dom_kb")}KB  '
          f'探针来源={data.get("source")}')
    bad = []
    for path, want, desc in ASSERT.get(sc, []):
        got = dig(data, path)
        total += 1
        ok = want(got) if callable(want) else (got == want)
        if not ok:
            bad.append((desc, path, want, got))
            fail += 1
    if bad:
        for desc, path, want, got in bad:
            print(f'   FAIL  {desc}')
            print(f'         期望 {path} = {fmt(want)}')
            print(f'         实际 = {fmt(got)}')
    else:
        print('   全部断言通过')

    # 跨字段一致性：这几处必须报同一个数
    if sc == 'exstale':
        badge = m.get('BADGE')
        tabcnt = m.get('TAB_DUE_CNT')
        cards = m.get('DUE_CARDS')
        hero = m.get('HERO_REVIEW') or ''
        checks = [
            ('侧栏徽章 vs 错题本页签计数', badge, tabcnt),
            ('错题本页签计数 vs 实际卡片数', str(cards), tabcnt),
        ]
        for label, a, b in checks:
            total += 1
            if a == b:
                print(f'   一致  {label}: {a}')
            else:
                fail += 1
                print(f'   FAIL  {label}: {a} != {b}')
        total += 1
        nm = re.search(r'(\d+)', hero)
        if badge and nm and nm.group(1) == str(badge):
            print(f'   一致  首页英雄区 vs 侧栏徽章: {badge}  ({hero})')
        else:
            fail += 1
            print(f'   FAIL  首页英雄区 vs 侧栏徽章: {hero!r} vs {badge!r}')
        # 埋了 6 条 -1：2 条是真题，另外 3 条幽灵 id + 1 条指向「运行效果」块，
        # 后 4 条都必须被排除，最后只能报 2
        total += 1
        if badge == '2':
            print(f'   正确  幽灵/非题目 id 已被排除: 埋入 6 条，计数 {badge}')
        else:
            fail += 1
            print(f'   FAIL  应只数 2 条真题（埋入 6 条）: {badge!r}')

    # 错题本四栏加起来必须正好等于全部例题数——口径漏掉一条就会露馅
    if sc in ('review', 'spaced'):
        cnt = [int(x) for x in (m.get('TAB_COUNTS') or '0/0/0/0').split('/')]
        total += 1
        if sum(cnt) == 45:
            print(f'   一致  四栏相加 = {sum(cnt)} = 全部例题数')
        else:
            fail += 1
            print(f'   FAIL  四栏相加 {sum(cnt)} != 45  ({m.get("TAB_COUNTS")})')

    # 间隔复习：徽章、页签、卡片、阶梯必须互相咬合，不许各算一遍
    if sc == 'spaced':
        due_tab = (m.get('TAB_COUNTS') or '').split('/')[0]
        checks = [
            ('侧栏徽章 vs 该复习页签', m.get('BADGE'), due_tab),
            ('该复习页签 vs 实际卡片数', str(m.get('DUE_CARDS')), due_tab),
            ('复习后徽章归零', m.get('BADGE_AFTER'), '0'),
            ('复习后该复习页签归零', (m.get('TAB_AFTER') or '').split('/')[0], '0'),
        ]
        for label, a, b in checks:
            total += 1
            if a == b:
                print(f'   一致  {label}: {a}')
            else:
                fail += 1
                print(f'   FAIL  {label}: {a!r} != {b!r}')
        # 阶梯五档压着的题数，应当正好是「该复习 + 稍后」
        lad = [int(x) for x in (m.get('LADDER') or '0/0/0/0/0').split('/')]
        pool = int(due_tab or 0) + int(m.get('LATER_N') or 0)
        total += 1
        if sum(lad) == pool:
            print(f'   一致  阶梯五档合计 = {sum(lad)} = 该复习 {due_tab} + 稍后 {m.get("LATER_N")}')
        else:
            fail += 1
            print(f'   FAIL  阶梯五档合计 {sum(lad)} != 池中题数 {pool}')

    # 自测的题库必须和错题本认的是同一批题——不是"数量碰巧一样"，
    # 而是两套索引的 id 集合逐一对上（那条在浏览器里由 IDS_MATCH 回答）。
    if sc == 'quiz':
        total += 1
        if m.get('QUIZ_N') == m.get('EX_N'):
            print(f'   一致  自测题库与错题本口径: {m.get("QUIZ_N")} 道')
        else:
            fail += 1
            print(f'   FAIL  自测题库 {m.get("QUIZ_N")} != 错题本 {m.get("EX_N")}')
        # 三种结局必须落到三个不同的栏位：答错进"该复习"、答对留在"已掌握"、
        # 跳过原地不动。任何一条串了，都说明 judging 又退回了 toggle 语义。
        total += 1
        trio = (m.get('DUE_HAS_DEMOTED'), m.get('DONE_HAS_OK'), m.get('DONE_HAS_SKIP'))
        if trio == (1, 1, 1):
            print('   一致  答错→该复习 / 答对→已掌握 / 跳过→原地不动，三条路径互不串')
        else:
            fail += 1
            print(f'   FAIL  三种结局的落位不对（期望 1,1,1）: {trio}')

    # 毕业项目：三组芯片的"总数"加起来必须正好是本页的条目数——少算一组就会露馅
    if sc == 'grad':
        tot = [int(x) for x in str(m.get('PILL_T') or '0').split(',')]
        items = m.get('ITEMS')
        total += 1
        if sum(tot) == items:
            print(f'   一致  三组芯片总数合计 = {sum(tot)} = 本页条目数')
        else:
            fail += 1
            print(f'   FAIL  芯片总数合计 {sum(tot)} != 本页条目数 {items}')
        total += 1
        if m.get('HW_TOTAL') == HW_TOTAL:
            print(f'   一致  全局作业口径 = {HW_TOTAL}（项目交付要求比原来多了 {HW_TOTAL - 142} 项）')
        else:
            fail += 1
            print(f'   FAIL  全局作业口径 {m.get("HW_TOTAL")} != {HW_TOTAL}')

    # 选方向：五张卡必须对应五个**不重复**的去处，多一个少一个都是映射错了。
    # 外加一条跨口径检查：就地展开让用户"在选方向页也能勾作业"，
    # 那几道题的 id 必须真的落在全局那 169 项里——否则勾了白勾（不进错题本、不进自测）。
    if sc == 'picker':
        total += 1
        if m.get('HREF_N') == m.get('CARDS'):
            print(f'   一致  卡片数 = 去处数 = {m.get("CARDS")}')
        else:
            fail += 1
            print(f'   FAIL  卡片 {m.get("CARDS")} != 不重复去处 {m.get("HREF_N")}')
        total += 1
        xids = [s for s in str(m.get('X_IDS') or '').split(',') if s]
        allids = {h['id'] for h in (m.get('_hwids') or [])}
        if xids and allids and set(xids) <= allids:
            print(f'   一致  就地展开的 {len(xids)} 道作业都在全局 {len(allids)} 项里'
                  f'（{m.get("HW_TOTAL_STABLE")} 项）')
        elif not allids:
            print('   （跳过：探针未回传全局作业 id 清单）')
        else:
            fail += 1
            print(f'   FAIL  就地展开的作业 id 不在全局索引里：'
                  f'{sorted(set(xids) - allids)}')

    # 该毕业了：两份种子只差"毕业项目做了多少"，所以**除了进度相关的字段以外，
    # 其余一切必须逐字相同**。这比分别断言两边更狠——它同时证明
    # ① 卡片的有无只由 gradProgress 决定，② 卡序没被状态偷偷改掉，
    # ③ 两张卡不是两套渲染分支各写一遍（那样文案与顺序迟早会漂）。
    if sc == 'gradplanFull':
        other = RESULTS.get('gradplan') or {}
        om = other.get('metrics') or {}
        total += 1
        if om and m.get('KEYS') == om.get('KEYS'):
            print(f'   一致  两态卡序相同（{m.get("KEYS")}），没被状态改掉')
        elif not om:
            print('   （跳过：未加载 gradplan 场景）')
        else:
            fail += 1
            print(f'   FAIL  卡序随状态变了：{om.get("KEYS")} vs {m.get("KEYS")}')
        total += 1
        a, b = m.get('CARD_HREF'), om.get('CARD_HREF')
        if om and a == b:
            print(f'   一致  两态的出口都是 {a}')
        elif not om:
            print('   （跳过：未加载 gradplan 场景）')
        else:
            fail += 1
            print(f'   FAIL  两态出口不一致：{b} vs {a}')
        total += 1
        if om and m.get('T') == om.get('T') and m.get('FULL') == '1':
            print(f'   一致  分母不变（{m.get("T")}）而分子涨到满格 → 达成判定是算出来的')
        elif not om:
            print('   （跳过：未加载 gradplan 场景）')
        else:
            fail += 1
            print(f'   FAIL  达成态的分母/满格标记不对：T={m.get("T")} FULL={m.get("FULL")}')

    # 附带展示关键观测值
    for k in ['VW', 'NO_HSCROLL', 'HASH', 'TAB_COUNTS', 'TAB_AFTER', 'LADDER',
              'STORED_EX', 'STORED_REV_DUE', 'BAR_N', 'R1_MSG', 'R2_MSG', 'R3_MSG',
              'TIME_AFTER', 'HEAT_LEVELS', 'EXPORT_BYTES', 'IMPORT_TOAST', 'BAD_TOAST',
              'DRAWER_OPEN', 'HINT_HIDDEN', 'RATE_BOX', 'CT_LEDE', 'REC_NOTE_STEPS']:
        if k in m:
            print(f'   {k} = {fmt(m[k])}')
    if data.get('stderr_tail'):
        print(f'   stderr: {data["stderr_tail"][:300]}')

print('=' * 66)
print(f'断言总数 {total}，失败 {fail}')

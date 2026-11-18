"""Backend messages in the interface language.

The app sets PERSONAL_OS_LANGUAGE to "en" when macOS prefers English. Messages
are written in Chinese and looked up here; anything missing stays Chinese, and
tests/test_i18n.py fails when a Chinese string has no entry.
"""
from functools import lru_cache
import json
import os
from pathlib import Path


def english():
    return os.environ.get('PERSONAL_OS_LANGUAGE', '').startswith('en')


def _(text):
    return EN.get(text, text) if english() else text


def profile_items(profile):
    yield ('profile', profile.get('profile_id')), profile
    for group in ('categories', 'goals', 'task_templates'):
        for item in profile.get(group, []):
            yield (group, item['id']), item


@lru_cache(maxsize=1)
def default_items():
    profile = json.loads(Path(__file__).with_name('initial_profile.json').read_text(encoding='utf-8'))
    return dict(profile_items(profile))


def plan_text(identity, field, value):
    original = default_items().get(identity, {}).get(field)
    if original is not None and value in (original, EN.get(original)):
        return _(original)
    return value


def translate_item(identity, item):
    for field in ('name', 'description'):
        if field in item:
            item[field] = plan_text(identity, field, item[field])


def restore_profile_labels(profile, previous):
    """Keep the stored spelling when an editor sends back a translated default."""
    originals = dict(profile_items(previous))
    for identity, item in profile_items(profile):
        prior = originals.get(identity, {})
        for field in ('name', 'description'):
            if field in item and field in prior and item[field] == plan_text(identity, field, prior[field]):
                item[field] = prior[field]


def translate_snapshot(snapshot):
    def translate_statistics(statistics):
        for group, key in (('goals', 'goals'), ('categories', 'category_totals')):
            for item in statistics.get(key, []):
                translate_item((group, item['id']), item)

    for identity, item in profile_items(snapshot['profile']):
        translate_item(identity, item)
    translate_statistics(snapshot['statistics'])
    for task in snapshot['tasks']:
        identity = ('task_templates', task['template_id'])
        translate_item(identity, task)
        translate_item(identity, task['template'])
    for review in snapshot['reviews']:
        for identity, item in profile_items(review['profile']):
            translate_item(identity, item)
        translate_statistics(review['statistics'])
    return snapshot


EN = {
    # Field names used inside the messages below.
    '日期': 'Date',
    '名称': 'Name',
    '活动日期': 'Activity date',
    '活动秒数': 'Activity seconds',
    '类别 ID': 'Category ID',
    '类别名称': 'Category name',
    '目标 ID': 'Goal ID',
    '目标名称': 'Goal name',
    '最低投入秒数': 'Minimum seconds',
    '最高投入秒数': 'Maximum seconds',
    '有效天数': 'Number of days',
    '有效日最低秒数': 'Minimum seconds per day',
    '任务 ID': 'Task ID',
    '任务名称': 'Task name',
    '任务开始日期': 'Task start date',
    '显示窗口天数': 'Reminder days',
    '试运行开始日期': 'Trial start date',
    '试运行周数': 'Trial weeks',

    # Validation.
    '{field}须为 YYYY-MM-DD 日期': '{field} must be a YYYY-MM-DD date',
    '{field}须为范围内的整数': '{field} must be a whole number within range',
    '{field}须以小写字母开头，仅允许小写字母、数字、下划线和连字符，长度 1–64':
        '{field} must start with a lowercase letter and use only lowercase letters, digits, underscores and hyphens (1–64 characters)',
    '{field}不能为空且须不超过 512 字符': '{field} cannot be empty or longer than 512 characters',
    '{field}不能包含换行、制表符或控制字符': '{field} cannot contain line breaks, tabs or control characters',
    '%s 必须是 YYYY-MM-DD 日期': '%s must be a YYYY-MM-DD date',
    '%s 必须是有效的 YYYY-MM-DD 日期': '%s must be a valid YYYY-MM-DD date',
    '配置须为对象': 'The settings must be an object',
    '不支持此配置版本': 'This settings version is not supported',
    '时区名称无效': 'Invalid time zone name',
    '每周起始日无效': 'Invalid first day of the week',
    '至少需要一个时间类别': 'At least one category is needed',
    '类别须为对象': 'Each category must be an object',
    '类别 ID 重复': 'Duplicate category ID',
    '状态栏名称须为一个英文单词：字母开头，最多 16 个字母或数字':
        'The status bar name must be one English word: starting with a letter, up to 16 letters or digits',
    '类别 {flag} 须为布尔值': 'Category {flag} must be true or false',
    '目标须为列表': 'Goals must be a list',
    '目标须为对象': 'Each goal must be an object',
    '目标 ID 重复': 'Duplicate goal ID',
    '当前仅支持每周投入目标': 'Only weekly goals are supported for now',
    '目标类型或强度无效': 'Invalid goal type or strength',
    '目标筛选须为对象': 'The goal filter must be an object',
    '目标引用了不存在的类别': 'A goal refers to a category that does not exist',
    '目标工作筛选须为布尔值': 'The goal work filter must be true or false',
    '投入范围的下限不能高于上限': 'The lower limit cannot be above the upper limit',
    '周期任务须为列表': 'Recurring tasks must be a list',
    '周期任务须为对象': 'Each recurring task must be an object',
    '任务 ID 重复': 'Duplicate task ID',
    '任务 enabled 须为布尔值': 'Task enabled must be true or false',
    '不支持的周期规则': 'Unsupported repeat rule',
    '周期任务星期无效': 'Invalid weekday for the recurring task',
    '显示窗口须为对象': 'The reminder setting must be an object',
    '试运行配置须为对象': 'The trial setting must be an object',
    '已有类别不能删除或更改 ID，请改为归档': 'Existing categories cannot be deleted or have their ID changed; archive them instead',
    '配置已被其他窗口更新，请刷新后重试': 'The settings were changed in another window; refresh and try again',
    '活动须为对象': 'The activity must be an object',
    '请选择有效且未归档的类别': 'Choose a valid category that is not archived',
    '活动关联了不存在的目标': 'The activity refers to a goal that does not exist',
    '只能删除应用内补记的活动': 'Only time added in the app can be deleted',
    '补记活动不存在': 'That added time no longer exists',
    '统计日期范围无效': 'Invalid date range',
    '活动类别无效': 'Invalid activity category',
    '数据库来自较新版本，请升级 Personal OS 后再打开': 'This database is from a newer version; update Personal OS to open it',
    '不能把原计时数据库作为 Personal OS 配置库': 'The timer database cannot be used as the Personal OS database',

    # Recurring tasks and reviews.
    '周期任务必须是对象': 'Each recurring task must be an object',
    '周期任务 %s 不能为空': 'Recurring task %s cannot be empty',
    '任务描述必须是文字': 'The task description must be text',
    '任务 enabled 必须是布尔值': 'Task enabled must be true or false',
    '请设置周期规则 recurrence': 'Set a repeat rule (recurrence)',
    '周期只支持 weekly/monthly/quarterly/yearly': 'Repeats can only be weekly, monthly, quarterly or yearly',
    'weekday 必须是英文星期名称或 0–6': 'weekday must be an English weekday name or 0–6',
    'day 必须为 last 或 1–31；短月按最后一天截止': 'day must be last or 1–31; short months end on their last day',
    'yearly month 必须为 1–12': 'yearly month must be 1–12',
    '请设置显示窗口 visibility': 'Set when the reminder starts (visibility)',
    '显示窗口只支持截止日之前的自然日': 'Reminders can only start a number of days before the due date',
    '显示窗口 days 必须为 1–366': 'Reminder days must be 1–366',
    '截止规则只支持 recurrence_date_end': 'The only supported due rule is recurrence_date_end',
    'task_templates 必须是列表': 'task_templates must be a list',
    '周期任务 ID 不能重复': 'Recurring task IDs must be unique',
    '周期日期超出支持范围': 'The date is outside the supported range',
    '待补齐的周期超过 10,000 期，请缩短 starts_on 范围': 'More than 10,000 periods would be created; choose a later start date',
    '任务状态必须为 pending/completed/skipped': 'The task status must be pending, completed or skipped',
    '复盘内容必须为文字': 'The review must be text',
    '找不到这期任务': 'This task period was not found',
    '复盘内容必须是文字，completed 必须是布尔值': 'The review must be text and completed must be true or false',
    '复盘统计和配置快照必须为对象': 'The review statistics and settings snapshot must be objects',
    '周复盘必须与配置中的周起点一致，并覆盖完整七天': 'A weekly review must start on the configured first day and cover seven days',

    # Timer.
    '计时状态格式无效': 'The timer state is invalid',
    '未知计时操作': 'Unknown timer action',
    '请先保存这个活动类别': 'Save this category first',
    '已有活动，请使用继续或切换活动': 'A timer is already running; resume it or switch category',
    '请选择要切换的活动': 'Choose the category to switch to',
    '不能开始已归档的类别': 'Archived categories cannot be started',
    '这条计时记录不存在': 'This timer record no longer exists',
    '旧日志里的记录不能在应用里删除': 'Records from the old log files cannot be deleted in the app',
    '请先使用项目提供的备份与安装步骤升级共享计时插件，避免新类别与旧菜单栏不兼容。':
        'Update the shared timer plugin with the provided backup and install steps first, so new categories work with the status bar.',
    '请先升级共享计时插件再修改类别；原数据仍可查看。': 'Update the shared timer plugin before changing categories; your data can still be viewed.',

    # Requests, history and backups.
    '所选日期须与配置的每周起始日一致': 'The chosen date must match the configured first day of the week',
    '请求格式无效': 'Invalid request',
    '未知操作': 'Unknown action',
    '请先保存或丢弃当前计时，再恢复备份': 'Save or discard the current timer before restoring a backup',
    '%s 第 %s 行未识别，原文件已保留。': '%s line %s was not recognized; the original file is kept.',
    '无法读取 %s：%s': 'Cannot read %s: %s',
    '数据库备份完整性检查失败': 'The database backup failed its integrity check',
    '备份来源目录不存在': 'The folder to back up does not exist',
    '备份必须使用来源目录之外的新位置': 'Save the backup to a new location outside the folder being backed up',
    '请把备份保存到计时数据目录之外': 'Save the backup outside the timer data folder',
    '备份位置是文件夹，请选择文件名': 'The backup location is a folder; choose a file name',
    '备份文件已存在，请换一个文件名': 'A backup with this name already exists; choose another name',
    '恢复必须使用新目录': 'Restoring needs a new folder',
    '不是支持的 Personal OS 备份版本': 'This is not a supported Personal OS backup version',
    '备份来源清单无效': 'The backup file list is invalid',
    '备份包含无效文件名': 'The backup contains an invalid file name',
    '备份包含不支持的来源文件': 'The backup contains an unsupported file',
    '备份数据库损坏': 'The backup database is damaged',
    '备份缺少应用数据表或初始配置': 'The backup is missing app data or settings',

    # The default plan a new user starts from (personal_os/initial_profile.json).
    '我的每周计划': 'My weekly plan',
    '科研': 'Research',
    '课程学习': 'Coursework',
    '行政与杂务': 'Admin',
    '其他工作': 'Other work',
    '阅读': 'Reading',
    '未分类': 'Untagged',
    '总工作投入': 'Total work',
    '科研投入': 'Research time',
    '科研天数': 'Research days',
    '行政与杂务上限': 'Admin limit',
    '其他工作记录': 'Other work log',
    '阅读天数': 'Reading days',
    '每周时间复盘': 'Weekly time review',
    '比较投入时长与有效天数，写下本周偏差及下周调整。': 'Compare hours and days against your goals; note what went off plan and what to change next week.',
    '月度复盘': 'Monthly review',
    '回看这个月的投入，写下值得保留和需要调整的地方。': 'Look back over the month: what to keep and what to change.',
    '季度复盘': 'Quarterly review',
    '回看这一季度的投入和产出，调整下一阶段的重点。': 'Look back over the quarter’s time and results, and set the focus for the next one.',
}

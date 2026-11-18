"""Calendar-based recurring tasks and durable review snapshots.

This module owns only its three tables. It does not read or modify the legacy
timer database and does not change the application's schema version.
"""
import calendar
import datetime as dt
import json
import sqlite3
import uuid
from personal_os.i18n import _


WEEKDAYS = {name: index for index, name in enumerate(
    ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'))}
MAX_PERIODS = 10000


def _date(value, field='date'):
    if not isinstance(value, str):
        raise ValueError(_('%s 必须是 YYYY-MM-DD 日期') % field)
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(_('%s 必须是有效的 YYYY-MM-DD 日期') % field) from None
    if parsed.isoformat() != value:
        raise ValueError(_('%s 必须是 YYYY-MM-DD 日期') % field)
    return parsed


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def _rows(cursor):
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def initialize(db):
    """Create this module's schema without touching timer data or PRAGMA versions."""
    with db:
        db.execute('''CREATE TABLE IF NOT EXISTS task_template_state (
            template_id TEXT PRIMARY KEY,
            activated_on TEXT NOT NULL,
            effective_on TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            template_json TEXT NOT NULL
        )''')
        # Compatibility for an early development database created before rule versions.
        columns = {row[1] for row in db.execute('PRAGMA table_info(task_template_state)')}
        if 'effective_on' not in columns:
            db.execute('ALTER TABLE task_template_state ADD COLUMN effective_on TEXT')
            db.execute('UPDATE task_template_state SET effective_on=activated_on')
        db.execute('''CREATE TABLE IF NOT EXISTS task_occurrences (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            period_key TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            visible_from TEXT NOT NULL,
            due_on TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'completed', 'skipped')),
            completed_at TEXT,
            review_text TEXT NOT NULL DEFAULT '',
            template_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(template_id, period_key),
            CHECK(visible_from <= due_on)
        )''')
        db.execute('''CREATE INDEX IF NOT EXISTS idx_task_occurrences_due
            ON task_occurrences(due_on, status)''')
        db.execute('''CREATE TABLE IF NOT EXISTS weekly_reviews (
            id TEXT PRIMARY KEY,
            week_start TEXT NOT NULL UNIQUE,
            week_end TEXT NOT NULL,
            text TEXT NOT NULL,
            completed INTEGER NOT NULL,
            statistics_json TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(week_start <= week_end)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS task_sync_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            signature TEXT NOT NULL
        )''')


def _validate_template(template):
    if not isinstance(template, dict):
        raise ValueError(_('周期任务必须是对象'))
    for field in ('id', 'name'):
        if not isinstance(template.get(field), str) or not template[field].strip():
            raise ValueError(_('周期任务 %s 不能为空') % field)
    if not isinstance(template.get('description', ''), str):
        raise ValueError(_('任务描述必须是文字'))
    if not isinstance(template.get('enabled', True), bool):
        raise ValueError(_('任务 enabled 必须是布尔值'))
    if template.get('starts_on') is not None:
        _date(template['starts_on'], 'starts_on')
    recurrence = template.get('recurrence')
    if not isinstance(recurrence, dict):
        raise ValueError(_('请设置周期规则 recurrence'))
    kind = recurrence.get('kind')
    if kind not in ('weekly', 'monthly', 'quarterly', 'yearly'):
        raise ValueError(_('周期只支持 weekly/monthly/quarterly/yearly'))
    if kind == 'weekly':
        weekday = recurrence.get('weekday', 'sunday')
        if isinstance(weekday, str):
            if weekday.lower() not in WEEKDAYS:
                raise ValueError(_('weekday 必须是英文星期名称或 0–6'))
        elif type(weekday) is not int or not 0 <= weekday <= 6:
            raise ValueError(_('weekday 必须是英文星期名称或 0–6'))
    else:
        day = recurrence.get('day', 'last')
        if day != 'last' and (type(day) is not int or not 1 <= day <= 31):
            raise ValueError(_('day 必须为 last 或 1–31；短月按最后一天截止'))
        if kind == 'yearly':
            month = recurrence.get('month', 12)
            if type(month) is not int or not 1 <= month <= 12:
                raise ValueError(_('yearly month 必须为 1–12'))
    visibility = template.get('visibility', {})
    if not isinstance(visibility, dict):
        raise ValueError(_('请设置显示窗口 visibility'))
    if visibility.get('kind', 'calendar_days_ending_on_due') != 'calendar_days_ending_on_due':
        raise ValueError(_('显示窗口只支持截止日之前的自然日'))
    days = visibility.get('days', 1)
    if type(days) is not int or not 1 <= days <= 366:
        raise ValueError(_('显示窗口 days 必须为 1–366'))
    deadline = template.get('deadline', {})
    if not isinstance(deadline, dict) or deadline.get('kind', 'recurrence_date_end') != 'recurrence_date_end':
        raise ValueError(_('截止规则只支持 recurrence_date_end'))
    _json(template)
    return template


def validate_templates(templates):
    """Validate without writing; callers can use this before saving a profile."""
    if not isinstance(templates, list):
        raise ValueError(_('task_templates 必须是列表'))
    valid = [_validate_template(template) for template in templates]
    identifiers = [template['id'] for template in valid]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(_('周期任务 ID 不能重复'))
    return valid


def _period_start(day, kind):
    if kind == 'weekly':
        return day - dt.timedelta(days=day.weekday())
    if kind == 'monthly':
        return day.replace(day=1)
    if kind == 'quarterly':
        return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
    return day.replace(month=1, day=1)


def _next_period(start, kind):
    if kind == 'weekly':
        return start + dt.timedelta(days=7)
    months = {'monthly': 1, 'quarterly': 3, 'yearly': 12}[kind]
    month_index = start.year * 12 + start.month - 1 + months
    return dt.date(month_index // 12, month_index % 12 + 1, 1)


def _period_key(start, kind):
    if kind == 'weekly':
        return start.isoformat()
    if kind == 'monthly':
        return '%04d-%02d' % (start.year, start.month)
    if kind == 'quarterly':
        return '%04d-Q%d' % (start.year, (start.month - 1) // 3 + 1)
    return '%04d' % start.year


def _due_date(start, recurrence):
    kind = recurrence['kind']
    if kind == 'weekly':
        weekday = recurrence.get('weekday', 'sunday')
        weekday = WEEKDAYS[weekday.lower()] if isinstance(weekday, str) else weekday
        return start + dt.timedelta(days=weekday)
    month = start.month
    if kind == 'quarterly':
        month += 2
    elif kind == 'yearly':
        month = recurrence.get('month', 12)
    last = calendar.monthrange(start.year, month)[1]
    requested = recurrence.get('day', 'last')
    return dt.date(start.year, month, last if requested == 'last' else min(requested, last))


def _materialize(db, template, cutoff, current, timestamp, upcoming=True):
    kind = template['recurrence']['kind']
    period = _period_start(cutoff, kind)
    for _period in range(MAX_PERIODS):
        due = _due_date(period, template['recurrence'])
        if not upcoming and due > current:
            break
        if due >= cutoff:
            visible = max(cutoff, due - dt.timedelta(days=template.get('visibility', {}).get('days', 1) - 1))
            db.execute('''INSERT OR IGNORE INTO task_occurrences
                (id,template_id,period_key,name,description,visible_from,due_on,
                 template_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                       (uuid.uuid4().hex, template['id'], _period_key(period, kind),
                        template['name'], template.get('description', ''), visible.isoformat(),
                        due.isoformat(), _json(template), timestamp, timestamp))
            if due >= current:
                break
        try:
            period = _next_period(period, kind)
        except (ValueError, OverflowError):
            raise ValueError(_('周期日期超出支持范围')) from None
    else:
        raise ValueError(_('待补齐的周期超过 10,000 期，请缩短 starts_on 范围'))


def sync_occurrences(db, templates, today):
    """Idempotently materialize missed periods and the next available occurrence.

    A null starts_on is persisted as this template's first activation date.
    Existing occurrences, including future ones, are immutable rule snapshots.
    Disabled or removed templates stay in history but are hidden from daily lists.
    """
    current = _date(today, 'today')
    valid = validate_templates(templates)
    initialize(db)
    # The result depends only on the templates and the date. Skipping a repeat
    # keeps the client's periodic refresh from rewriting the database.
    signature = _json([today, valid])
    synced = db.execute('SELECT signature FROM task_sync_state WHERE id=1').fetchone()
    if synced and synced[0] == signature:
        return list_occurrences(db, today)
    timestamp = _now()
    with db:
        db.execute('INSERT OR REPLACE INTO task_sync_state(id,signature) VALUES(1,?)', (signature,))
        states = {row['template_id']: row for row in _rows(db.execute('SELECT * FROM task_template_state'))}
        db.execute('UPDATE task_template_state SET enabled=0')
        for template in valid:
            row = states.get(template['id'])
            requested_start = _date(template['starts_on']) if template.get('starts_on') else current
            activation = _date(row['activated_on']) if row else requested_start
            effective = _date(row['effective_on']) if row else activation
            enabled = template.get('enabled', True)
            encoded = _json(template)
            changed = row and (row['template_json'] != encoded or bool(row['enabled']) != enabled)
            if changed:
                previous = json.loads(row['template_json'])
                old_cutoff = max(activation, effective)
                if previous.get('starts_on'):
                    old_cutoff = max(old_cutoff, _date(previous['starts_on']))
                if row['enabled'] and current > dt.date.min:
                    _materialize(db, previous, old_cutoff, current - dt.timedelta(days=1), timestamp, upcoming=False)
                effective = max(activation, current)
            # Changing starts_on can postpone new copies, never backfill before activation.
            cutoff = max(activation, effective, requested_start) if template.get('starts_on') else max(activation, effective)
            db.execute('''INSERT INTO task_template_state
                (template_id,activated_on,effective_on,enabled,template_json) VALUES(?,?,?,?,?)
                ON CONFLICT(template_id) DO UPDATE SET
                effective_on=excluded.effective_on, enabled=excluded.enabled, template_json=excluded.template_json''',
                       (template['id'], activation.isoformat(), effective.isoformat(), int(enabled), encoded))
            if not enabled:
                continue
            _materialize(db, template, cutoff, current, timestamp)
    return list_occurrences(db, today)


def list_occurrences(db, today):
    current = _date(today, 'today').isoformat()
    result = _rows(db.execute('''SELECT o.*, COALESCE(s.enabled,0) AS template_enabled
        FROM task_occurrences o LEFT JOIN task_template_state s ON s.template_id=o.template_id
        ORDER BY o.due_on DESC,o.name,o.id'''))
    for row in result:
        row['is_visible'] = bool(row.pop('template_enabled')) and row['visible_from'] <= current
        row['is_overdue'] = row['status'] == 'pending' and row['due_on'] < current
        row['template'] = json.loads(row.pop('template_json'))
    return result


def update_occurrence(db, id, status, text, today):
    """Update one explicit occurrence; late completion cannot affect another period."""
    _date(today, 'today')
    if status not in ('pending', 'completed', 'skipped'):
        raise ValueError(_('任务状态必须为 pending/completed/skipped'))
    if not isinstance(text, str):
        raise ValueError(_('复盘内容必须为文字'))
    timestamp = _now()
    with db:
        row = db.execute('SELECT status,completed_at FROM task_occurrences WHERE id=?', (id,)).fetchone()
        if not row:
            raise ValueError(_('找不到这期任务'))
        completed_at = ((row[1] if row[0] == 'completed' and row[1] else timestamp)
                        if status == 'completed' else None)
        db.execute('''UPDATE task_occurrences SET status=?,completed_at=?,review_text=?,updated_at=?
            WHERE id=?''', (status, completed_at, text, timestamp, id))
    return next(item for item in list_occurrences(db, today) if item['id'] == id)


def save_weekly_review(db, week_start, week_end, text, completed, statistics, profile):
    """Save one week. Text edits to a completed review retain its original snapshot.

    Saving completed=False explicitly reopens it. That first reopen retains the
    old snapshot; a subsequent draft/completion save may capture fresh statistics.
    """
    first, last = _date(week_start, 'week_start'), _date(week_end, 'week_end')
    if not isinstance(text, str) or not isinstance(completed, bool):
        raise ValueError(_('复盘内容必须是文字，completed 必须是布尔值'))
    if not isinstance(statistics, dict) or not isinstance(profile, dict):
        raise ValueError(_('复盘统计和配置快照必须为对象'))
    start_name = profile.get('week_starts_on', 'monday')
    start_weekday = WEEKDAYS.get(start_name) if isinstance(start_name, str) else None
    if start_weekday is None or first.weekday() != start_weekday or last - first != dt.timedelta(days=6):
        raise ValueError(_('周复盘必须与配置中的周起点一致，并覆盖完整七天'))
    statistics_json, profile_json = _json(statistics), _json(profile)
    initialize(db)
    timestamp = _now()
    with db:
        previous = db.execute('''SELECT id,completed,statistics_json,profile_json FROM weekly_reviews
            WHERE week_start=?''', (week_start,)).fetchone()
        if previous and previous[1]:
            statistics_json, profile_json = previous[2], previous[3]
        identifier = previous[0] if previous else uuid.uuid4().hex
        db.execute('''INSERT INTO weekly_reviews
            (id,week_start,week_end,text,completed,statistics_json,profile_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(week_start) DO UPDATE SET
            week_end=excluded.week_end,text=excluded.text,completed=excluded.completed,
            statistics_json=excluded.statistics_json,profile_json=excluded.profile_json,
            updated_at=excluded.updated_at''',
                   (identifier, week_start, week_end, text, int(completed), statistics_json,
                    profile_json, timestamp, timestamp))
    return next(item for item in list_weekly_reviews(db) if item['id'] == identifier)


def list_weekly_reviews(db):
    result = _rows(db.execute('SELECT * FROM weekly_reviews ORDER BY week_start DESC'))
    for row in result:
        row['completed'] = bool(row['completed'])
        row['statistics'] = json.loads(row.pop('statistics_json'))
        row['profile'] = json.loads(row.pop('profile_json'))
    return result

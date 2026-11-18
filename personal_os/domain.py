"""Personal OS configuration, manual records, and exact-second goal statistics.

Only the new application database is written here. Legacy timer history is supplied
as records by the read-only adapter. Profile edits retain every prior version;
completed reviews retain their own snapshots. Scheduled future-effective profiles
are intentionally outside this compatibility MVP.
"""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo
from personal_os.i18n import _

SCHEMA_VERSION = 1
KINDS = {"minimum_duration", "maximum_duration", "duration_range", "frequency", "observe"}
STRENGTHS = {"hard", "flexible", "observe"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
# SketchyBar shows one English word per category; the app keeps the full name.
BAR_LABEL_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
BAR_LABELS = {"research": "Research", "course": "Study", "biology": "Biology", "social": "Service",
              "other_work": "Misc", "reading": "Reading", "uncategorized": "Untagged"}


def _date(value, field="日期"):
    if not isinstance(value, str):
        raise ValueError(_("{field}须为 YYYY-MM-DD 日期").format(field=_(field)))
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(_("{field}须为 YYYY-MM-DD 日期").format(field=_(field))) from exc
    if result.isoformat() != value:
        raise ValueError(_("{field}须为 YYYY-MM-DD 日期").format(field=_(field)))
    return result


def _integer(value, field, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(_("{field}须为范围内的整数").format(field=_(field)))
    return value


def _id(value, field="ID"):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(_("{field}须以小写字母开头，仅允许小写字母、数字、下划线和连字符，长度 1–64").format(field=_(field)))
    return value


def local_timezone(fallback):
    """The Mac's own time zone for a new profile (TZ first, then /etc/localtime)."""
    candidates = [os.environ.get("TZ", ""), os.path.realpath("/etc/localtime").partition("/zoneinfo/")[2]]
    for name in candidates:
        try:
            if name:
                ZoneInfo(name)
                return name
        except (ValueError, KeyError, OSError):
            continue
    return fallback


def bar_label(category):
    return category.get("bar_label") or BAR_LABELS.get(category["id"], "Custom")


def _name(value, field="名称"):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(_("{field}不能为空且须不超过 512 字符").format(field=_(field)))
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(_("{field}不能包含换行、制表符或控制字符").format(field=_(field)))
    return value


def validate_profile(profile):
    """Validate public configuration without normalizing away user metadata."""
    if not isinstance(profile, dict):
        raise ValueError(_("配置须为对象"))
    if type(profile.get("schema_version", 1)) is not int or profile.get("schema_version", 1) != 1:
        raise ValueError(_("不支持此配置版本"))
    try:
        ZoneInfo(profile.get("timezone", "Asia/Hong_Kong"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(_("时区名称无效")) from exc
    if profile.get("week_starts_on", "monday") not in WEEKDAYS:
        raise ValueError(_("每周起始日无效"))
    categories = profile.get("categories")
    if not isinstance(categories, list) or not categories:
        raise ValueError(_("至少需要一个时间类别"))
    category_ids = set()
    for cat in categories:
        if not isinstance(cat, dict):
            raise ValueError(_("类别须为对象"))
        key = _id(cat.get("id"), _("类别 ID"))
        if key in category_ids:
            raise ValueError(_("类别 ID 重复"))
        category_ids.add(key)
        _name(cat.get("name"), _("类别名称"))
        if "bar_label" in cat and not (isinstance(cat["bar_label"], str) and BAR_LABEL_PATTERN.fullmatch(cat["bar_label"])):
            raise ValueError(_("状态栏名称须为一个英文单词：字母开头，最多 16 个字母或数字"))
        for flag in ("counts_as_work", "archived"):
            if flag in cat and type(cat[flag]) is not bool:
                raise ValueError(_("类别 {flag} 须为布尔值").format(flag=flag))
    goals = profile.get("goals", [])
    if not isinstance(goals, list):
        raise ValueError(_("目标须为列表"))
    goal_ids = set()
    for goal in goals:
        if not isinstance(goal, dict):
            raise ValueError(_("目标须为对象"))
        key = _id(goal.get("id"), _("目标 ID"))
        if key in goal_ids:
            raise ValueError(_("目标 ID 重复"))
        goal_ids.add(key)
        _name(goal.get("name"), _("目标名称"))
        if goal.get("period", "week") != "week":
            raise ValueError(_("当前仅支持每周投入目标"))
        kind = goal.get("kind")
        strength = goal.get("strength", "flexible")
        if not isinstance(kind, str) or kind not in KINDS or not isinstance(strength, str) or strength not in STRENGTHS:
            raise ValueError(_("目标类型或强度无效"))
        criteria = goal.get("filter", {})
        if not isinstance(criteria, dict):
            raise ValueError(_("目标筛选须为对象"))
        ids = criteria.get("category_ids", [])
        if not isinstance(ids, list) or any(not isinstance(x, str) or x not in category_ids for x in ids):
            raise ValueError(_("目标引用了不存在的类别"))
        if "counts_as_work" in criteria and type(criteria["counts_as_work"]) is not bool:
            raise ValueError(_("目标工作筛选须为布尔值"))
        if kind in ("minimum_duration", "duration_range"):
            _integer(goal.get("minimum_seconds"), _("最低投入秒数"), 1)
        if kind in ("maximum_duration", "duration_range"):
            _integer(goal.get("maximum_seconds"), _("最高投入秒数"), 1)
        if kind == "duration_range" and goal["minimum_seconds"] > goal["maximum_seconds"]:
            raise ValueError(_("投入范围的下限不能高于上限"))
        if kind == "frequency":
            _integer(goal.get("minimum_distinct_days"), _("有效天数"), 1, 7)
            _integer(goal.get("minimum_daily_seconds"), _("有效日最低秒数"), 1, 86400)
    templates = profile.get("task_templates", [])
    if not isinstance(templates, list):
        raise ValueError(_("周期任务须为列表"))
    template_ids = set()
    for template in templates:
        if not isinstance(template, dict):
            raise ValueError(_("周期任务须为对象"))
        key = _id(template.get("id"), _("任务 ID"))
        if key in template_ids:
            raise ValueError(_("任务 ID 重复"))
        template_ids.add(key)
        _name(template.get("name"), _("任务名称"))
        if template.get("starts_on") is not None:
            _date(template["starts_on"], _("任务开始日期"))
        if "enabled" in template and type(template["enabled"]) is not bool:
            raise ValueError(_("任务 enabled 须为布尔值"))
        recurrence = template.get("recurrence", {})
        if (not isinstance(recurrence, dict) or not isinstance(recurrence.get("kind"), str)
                or recurrence["kind"] not in {"weekly", "monthly", "quarterly", "yearly"}):
            raise ValueError(_("不支持的周期规则"))
        if recurrence["kind"] == "weekly" and recurrence.get("weekday", "sunday") not in WEEKDAYS:
            raise ValueError(_("周期任务星期无效"))
        visibility = template.get("visibility", {})
        if not isinstance(visibility, dict):
            raise ValueError(_("显示窗口须为对象"))
        _integer(visibility.get("days", 1), _("显示窗口天数"), 1, 366)
    trial = profile.get("trial", {})
    if not isinstance(trial, dict):
        raise ValueError(_("试运行配置须为对象"))
    if trial.get("started_on") is not None:
        _date(trial["started_on"], _("试运行开始日期"))
    if "weeks" in trial:
        _integer(trial["weeks"], _("试运行周数"), 1, 52)
    return profile


def connect(path):
    """Create/open the application database; never use for a legacy timer DB."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        db.close()
        raise ValueError(_("数据库来自较新版本，请升级 Personal OS 后再打开"))
    # A legacy timer DB has user_version=0 too; refuse it rather than add tables.
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "sessions" in existing or "discarded_sessions" in existing:
        db.close()
        raise ValueError(_("不能把原计时数据库作为 Personal OS 配置库"))
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS profile_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, profile_json TEXT NOT NULL, created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS manual_activities (id TEXT PRIMARY KEY, day TEXT NOT NULL, category TEXT NOT NULL, seconds INTEGER NOT NULL CHECK(seconds > 0), goal_ids_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS manual_activities_day ON manual_activities(day)")
        if version < SCHEMA_VERSION:
            # Setting it unconditionally would rewrite the file on every read-only request.
            db.execute("PRAGMA user_version=1")
    return db


def _timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def get_profile(db):
    row = db.execute("SELECT id,profile_json FROM profile_versions ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        result = json.loads(row[1])
        result["revision"] = row[0]
        # Profiles saved before bar labels existed show the effective label for editing.
        for category in result.get("categories", []):
            category.setdefault("bar_label", bar_label(category))
        return result
    profile = json.loads(Path(__file__).with_name("initial_profile.json").read_text(encoding="utf-8"))
    profile["timezone"] = local_timezone(profile["timezone"])
    # A new user's plan is written in the interface language.
    profile["name"] = _(profile["name"])
    for item in profile["categories"] + profile["goals"] + profile["task_templates"]:
        item["name"] = _(item["name"])
        if "description" in item:
            item["description"] = _(item["description"])
    today = dt.datetime.now(ZoneInfo(profile["timezone"])).date().isoformat()
    profile.pop("status", None)
    profile.setdefault("trial", {})["started_on"] = today
    for template in profile.get("task_templates", []):
        if not template.get("starts_on"):
            template["starts_on"] = today
    return save_profile(db, profile)


def save_profile(db, profile, before_commit=None):
    """Retain a profile version, optionally coordinating a local catalog mirror.

    before_commit(profile) runs inside the SQLite transaction, including unchanged
    saves. If it raises, the profile insert and version number roll back. The
    caller owns rollback of any non-database side effects performed by its hook.
    """
    profile = copy.deepcopy(profile)
    validate_profile(profile)
    old = db.execute("SELECT id,profile_json FROM profile_versions ORDER BY id DESC LIMIT 1").fetchone()
    if old:
        existing = json.loads(old[1])
        old_ids = {c["id"] for c in existing["categories"]}
        new_ids = {c["id"] for c in profile["categories"]}
        if not old_ids <= new_ids:
            raise ValueError(_("已有类别不能删除或更改 ID，请改为归档"))
        if "revision" in profile and profile["revision"] != old[0]:
            raise ValueError(_("配置已被其他窗口更新，请刷新后重试"))
    profile.pop("revision", None)
    serialized = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    with db:
        # BEGIN IMMEDIATE prevents two writers from accepting the same revision.
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT id,profile_json FROM profile_versions ORDER BY id DESC LIMIT 1").fetchone()
        if old and (not current or current[0] != old[0]):
            raise ValueError(_("配置已被其他窗口更新，请刷新后重试"))
        if not old and current:
            profile = get_profile(db)
            if before_commit is not None:
                before_commit(profile)
            return profile
        if current and current[1] == serialized:
            profile["revision"] = current[0]
            if before_commit is not None:
                before_commit(profile)
            return profile
        cursor = db.execute("INSERT INTO profile_versions(profile_json,created_at) VALUES(?,?)", (serialized, _timestamp()))
        profile["revision"] = cursor.lastrowid
        if before_commit is not None:
            before_commit(profile)
    return profile


def list_manual_activities(db):
    return [dict(id=r["id"], day=r["day"], category=r["category"], seconds=r["seconds"],
                 source="manual", precision="day", saved=True,
                 goal_ids=json.loads(r["goal_ids_json"]))
            for r in db.execute("SELECT * FROM manual_activities ORDER BY day DESC, created_at DESC,id")]


def add_manual_activity(db, payload):
    if not isinstance(payload, dict):
        raise ValueError(_("活动须为对象"))
    day = _date(payload.get("day"), _("活动日期")).isoformat()
    seconds = _integer(payload.get("seconds"), _("活动秒数"), 1, 86400)
    profile = get_profile(db)
    cats = {c["id"]: c for c in profile["categories"]}
    category = payload.get("category")
    if category not in cats or cats[category].get("archived", False):
        raise ValueError(_("请选择有效且未归档的类别"))
    goals = payload.get("goal_ids", [])
    known_goals = {g["id"] for g in profile.get("goals", [])}
    if not isinstance(goals, list) or any(not isinstance(g, str) or g not in known_goals for g in goals):
        raise ValueError(_("活动关联了不存在的目标"))
    goals = list(dict.fromkeys(goals))
    identity = "manual-" + uuid.uuid4().hex
    with db:
        db.execute("INSERT INTO manual_activities(id,day,category,seconds,goal_ids_json,created_at) VALUES(?,?,?,?,?,?)",
                   (identity, day, category, seconds, json.dumps(goals), _timestamp()))
    return dict(id=identity, day=day, category=category, seconds=seconds, source="manual",
                precision="day", saved=True, goal_ids=goals)


def delete_manual_activity(db, id):
    if not isinstance(id, str) or not id.startswith("manual-"):
        raise ValueError(_("只能删除应用内补记的活动"))
    with db:
        result = db.execute("DELETE FROM manual_activities WHERE id=?", (id,))
        if result.rowcount != 1:
            raise ValueError(_("补记活动不存在"))
    return True


def _matches(goal, activity, categories):
    # Explicit association is an alternative to the automatic category filter.
    if goal["id"] in activity.get("goal_ids", []):
        return True
    criteria = goal.get("filter", {})
    if "category_ids" in criteria and activity["category"] not in criteria["category_ids"]:
        return False
    if "counts_as_work" in criteria:
        works = categories.get(activity["category"], {}).get("counts_as_work", False)
        if works != criteria["counts_as_work"]:
            return False
    return True


def _goal_progress(goal, records, categories, last, today):
    daily = {}
    for record in records:
        if _matches(goal, record, categories):
            daily[record["day"]] = daily.get(record["day"], 0) + record["seconds"]
    seconds = sum(daily.values())
    kind = goal["kind"]
    result = {k: goal[k] for k in ("id", "name", "kind")}
    result.update(strength=goal.get("strength", "flexible"), unit="seconds",
                  actual=seconds, target=0, status="observing", progress=0.0,
                  daily_seconds=daily, provisional=last >= today)
    if kind == "frequency":
        threshold = goal["minimum_daily_seconds"]
        result.update(actual=sum(v >= threshold for v in daily.values()),
                      target=goal["minimum_distinct_days"], unit="days",
                      minimum_daily_seconds=threshold)
        result["status"] = "met" if result["actual"] >= result["target"] else "below"
    elif kind in ("minimum_duration", "duration_range"):
        result.update(minimum=goal["minimum_seconds"], target=goal["minimum_seconds"])
        result["status"] = "met" if seconds >= result["target"] else "below"
        if kind == "duration_range":
            result["maximum"] = goal["maximum_seconds"]
            if seconds > goal["maximum_seconds"]:
                result["status"] = "over"
    elif kind == "maximum_duration":
        result.update(maximum=goal["maximum_seconds"], target=goal["maximum_seconds"],
                      status="over" if seconds > goal["maximum_seconds"] else "met")
    if result["target"]:
        result["progress"] = min(1.0, result["actual"] / result["target"])
    if result["strength"] == "observe":
        result["status"] = "observing"
    return result


def build_statistics(profile, activities, first, last, today):
    """Summarize inclusive local date buckets; previews never satisfy saved goals."""
    start, end = _date(first), _date(last)
    _date(today)
    if start > end or (end - start).days > 3660:
        raise ValueError(_("统计日期范围无效"))
    categories = {c["id"]: c for c in profile.get("categories", [])}
    records, previews, seen = [], [], set()
    for raw in activities:
        day = raw.get("day")
        _date(day, _("活动日期"))
        if not first <= day <= last:
            continue
        identity = raw.get("id")
        if identity:
            if identity in seen:
                continue
            seen.add(identity)
        seconds = _integer(raw.get("seconds"), _("活动秒数"), 0)
        category = raw.get("category")
        if not isinstance(category, str) or not category:
            raise ValueError(_("活动类别无效"))
        record = dict(raw, seconds=seconds)
        (records if raw.get("saved", True) else previews).append(record)
    by_day = {}
    category_seconds = {key: 0 for key in categories}
    current = start
    while current <= end:
        key = current.isoformat()
        by_day[key] = dict(day=key, seconds=0, work_seconds=0, by_category={})
        current += dt.timedelta(days=1)
    for record in records:
        category, seconds = record["category"], record["seconds"]
        day = by_day[record["day"]]
        day["seconds"] += seconds
        day["by_category"][category] = day["by_category"].get(category, 0) + seconds
        category_seconds[category] = category_seconds.get(category, 0) + seconds
        if categories.get(category, {}).get("counts_as_work", False):
            day["work_seconds"] += seconds
    goals = [_goal_progress(g, records, categories, last, today) for g in profile.get("goals", [])
             if not g.get("archived", False)]

    def frequency(category):
        matching = [g for g in goals if g["kind"] == "frequency" and
                    category in next((x.get("filter", {}).get("category_ids", [])
                                      for x in profile.get("goals", []) if x["id"] == g["id"]), [])]
        return matching[0]["actual"] if matching else 0

    return dict(work_seconds=sum(d["work_seconds"] for d in by_day.values()),
                total_seconds=sum(category_seconds.values()),
                research_seconds=category_seconds.get("research", 0),
                research_days=frequency("research"), reading_days=frequency("reading"),
                category_totals=[dict(id=key, name=categories.get(key, {}).get("name", key), seconds=value)
                                 for key, value in category_seconds.items()],
                days=list(by_day.values()), goals=goals,
                preview_seconds=sum(r["seconds"] for r in previews))

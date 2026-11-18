"""Read the existing timer ledger without migrating or modifying it."""
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import time
from personal_os.i18n import _


def _split(start, end, category):
    rows = []
    while start < end:
        day = dt.datetime.fromtimestamp(start).date()
        boundary = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time()).timestamp())
        stop = min(end, boundary)
        rows.append((day.isoformat(), category, stop - start))
        start = stop
    return rows


def _clock(start, end):
    """Local HH:MM range for records saved with clock times (timer API 2 and later)."""
    if start is None or end is None:
        return {}
    return dict(start_time=time.strftime("%H:%M", time.localtime(start)),
                end_time=time.strftime("%H:%M", time.localtime(end)), precision="minute")


def read_activities(data_dir, first, last, now):
    data_dir = Path(data_dir)
    dt.date.fromisoformat(first)
    dt.date.fromisoformat(last)
    activities, warnings = [], []
    state = {"mode": "idle", "category": "research", "elapsed": 0,
             "anchor": 0, "last_tick": 0, "pending": []}
    path = data_dir / "focus.sqlite3"
    if path.exists():
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            db.execute("BEGIN")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'sessions' in tables:
                columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
                times = "started_at,ended_at" if {"started_at", "ended_at"} <= columns else "NULL,NULL"
                for row in db.execute("SELECT id,day,category,seconds,%s FROM sessions WHERE day BETWEEN ? AND ? ORDER BY day,id" % times, (first, last)):
                    if row[3] > 0:
                        activity = dict(id="focus:%s" % row[0], day=row[1], category=row[2],
                                        seconds=row[3], source="sketchybar", precision="day", saved=True)
                        activity.update(_clock(row[4], row[5]))
                        activities.append(activity)
            if 'state' in tables:
                row = db.execute("SELECT value FROM state WHERE id=1").fetchone()
                if row:
                    saved_state = json.loads(row[0])
                    if not isinstance(saved_state, dict):
                        raise ValueError(_("计时状态格式无效"))
                    state.update(saved_state)
        finally:
            db.close()
    for path in sorted(data_dir.glob("focus_????-??-??.log")):
        day = path.stem[6:]
        if not first <= day <= last:
            continue
        try:
            dt.date.fromisoformat(day)
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                parts = line.split()
                if len(parts) >= 2 and parts[-1].isdigit() and int(parts[-1]) > 0:
                    category = parts[1] if len(parts) >= 3 else "uncategorized"
                    activity = dict(id="legacy:%s:%s" % (path.name, index + 1), day=day,
                                    category=category, seconds=int(parts[-1]), source="legacy_log",
                                    precision="day", saved=True)
                    # Old log lines start with the clock time they were written.
                    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", parts[0]):
                        activity["logged_time"] = parts[0][:5]
                    activities.append(activity)
                elif line.strip():
                    warnings.append(_("%s 第 %s 行未识别，原文件已保留。") % (path.name, index + 1))
        except (ValueError, UnicodeError, OSError) as exc:
            warnings.append(_("无法读取 %s：%s") % (path.name, exc))
    running = state['mode'] in ('up', 'down', 'overtime')
    pending = list(state.get('pending', []))
    if running:
        pending += _split(state['anchor'], max(state['anchor'], now), state['category'])
    for index, (day, _category, seconds) in enumerate(pending):
        if first <= day <= last and seconds > 0:
            activities.append(dict(id="preview:%s" % index, day=day, category=state['category'],
                                   seconds=seconds, source="live", precision="day", saved=False))
    elapsed = state['elapsed'] + (max(0, now - state['anchor']) if running else 0)
    timer = dict(mode=state['mode'], category=state['category'], elapsed_seconds=elapsed,
                 running=running, active=state['mode'] != 'idle', available=True)
    source = dict(path=str(data_dir), warnings=warnings, read_only=True)
    return activities, timer, source

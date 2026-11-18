#!/usr/bin/env python3
"""One JSON request per local process. No server, account, or network required."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

# The backend is shipped inside a signed .app; bytecode caches would modify it.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_os import backup, domain, legacy, reviews, timer_bridge
from personal_os.i18n import _


def has_ledger(path):
    return (path / 'focus.sqlite3').exists() or any(path.glob('focus_*.log'))


def paths():
    root = Path(os.environ.get('PERSONAL_OS_DATA_DIR', Path.home() / 'Library/Application Support/Personal OS')).expanduser()
    explicit = os.environ.get('SKETCHYBAR_DATA_DIR')
    source = Path(explicit).expanduser() if explicit else Path.home() / '.config/sketchybar/data'
    if not explicit and not has_ledger(source):
        source = root / 'timer'
    override = root / 'workspace.json'
    if override.exists():
        pointer = json.loads(override.read_text(encoding='utf-8'))
        selected = Path(pointer['path'])
        # A restored workspace replaces only the app database. The shared timer
        # ledger stays the single writer; the backup's copy is used only when no
        # ledger existed at import (pointers written before timer_dir included).
        if pointer.get('timer_dir'):
            timer = Path(pointer['timer_dir'])
        else:
            timer = source if has_ledger(source) else selected / 'legacy'
        return root, selected / 'personal_os.sqlite3', timer
    return root, root / 'personal_os.sqlite3', source


def week_bounds(profile, requested, today):
    if requested:
        first = dt.date.fromisoformat(requested)
    else:
        day = dt.date.fromisoformat(today)
        index = domain.WEEKDAYS.index(profile.get('week_starts_on', 'monday'))
        first = day - dt.timedelta(days=(day.weekday() - index) % 7)
    if first.weekday() != domain.WEEKDAYS.index(profile.get('week_starts_on', 'monday')):
        raise ValueError(_('所选日期须与配置的每周起始日一致'))
    return first.isoformat(), (first + dt.timedelta(days=6)).isoformat()


def snapshot(db, profile, data, requested=None):
    today = dt.datetime.now(ZoneInfo(profile['timezone'])).date().isoformat()
    first, last = week_bounds(profile, requested, today)
    earliest = (dt.date.fromisoformat(first) - dt.timedelta(days=21)).isoformat()
    records, timer, source = legacy.read_activities(data, earliest, last, int(time.time()))
    all_records = records + domain.list_manual_activities(db)
    statistics = domain.build_statistics(profile, all_records, first, last, today)
    tasks = reviews.sync_occurrences(db, profile.get('task_templates', []), today)
    trends = []
    for offset in (21, 14, 7, 0):
        start = dt.date.fromisoformat(first) - dt.timedelta(days=offset)
        end = start + dt.timedelta(days=6)
        stats = domain.build_statistics(profile, all_records, start.isoformat(), end.isoformat(), today)
        trends.append(dict(week_start=start.isoformat(), work_seconds=stats['work_seconds'], research_seconds=stats['research_seconds']))
    return dict(profile=profile, today=today, week_start=first, week_end=last, statistics=statistics,
                timer=timer, activities=sorted([r for r in all_records if first <= r['day'] <= last],
                                               key=lambda r: (r['day'], r.get('start_time', ''), r['id']), reverse=True),
                tasks=tasks, reviews=reviews.list_weekly_reviews(db), trends=trends, source=source)


def _mirror_manual(db, data):
    """Share time added by hand with the status bar, which counts it in its day and week totals."""
    entries = [dict(day=a['day'], category=a['category'], seconds=a['seconds']) for a in domain.list_manual_activities(db)]
    text = json.dumps(entries, ensure_ascii=False, sort_keys=True)
    path = Path(data) / 'personal-os-manual.json'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return
    Path(data).mkdir(parents=True, exist_ok=True)
    staged = path.with_name('.personal-os-manual.tmp')
    staged.write_text(text, encoding='utf-8')
    staged.replace(path)
    if not os.environ.get('PERSONAL_OS_NO_BAR') and (Path(data).parent / 'plugins/timer.py').exists():
        try:
            timer_bridge.refresh_bar_stats(data)
        except (subprocess.SubprocessError, OSError):
            pass


def _mirror_categories(data, profile, refresh=True):
    # Shared timer code must support the catalog before introducing new IDs.
    installed = Path(data).parent / 'plugins/timer.py'
    # Any engine with the API marker understands the category catalog; API 2 only added clock times.
    if installed.exists() and 'PERSONAL_OS_TIMER_API = ' not in installed.read_text(encoding='utf-8'):
        raise ValueError(_('请先使用项目提供的备份与安装步骤升级共享计时插件，避免新类别与旧菜单栏不兼容。'))
    refresh = refresh and not os.environ.get('PERSONAL_OS_NO_BAR') and installed.exists()
    settings = Path(data) / 'personal-os-settings.json'
    text = json.dumps({'timezone': profile['timezone'], 'archived_categories': [c['id'] for c in profile['categories'] if c.get('archived')]}, ensure_ascii=False)
    Path(data).mkdir(parents=True, exist_ok=True)
    settings_changed = False
    if not settings.exists() or settings.read_text(encoding='utf-8') != text:
        staged = settings.with_suffix('.tmp')
        staged.write_text(text, encoding='utf-8')
        staged.replace(settings)
        settings_changed = True
    catalog_changed = timer_bridge.sync_categories(data, profile['categories'], refresh=refresh)
    if settings_changed and not catalog_changed and refresh:
        import subprocess
        subprocess.run(['sketchybar', '--reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    return catalog_changed or settings_changed


def dispatch(request):
    if not isinstance(request, dict):
        raise ValueError(_('请求格式无效'))
    root, db_path, data = paths()
    db = domain.connect(db_path)
    try:
        reviews.initialize(db)
        profile = domain.get_profile(db)
        os.environ['TZ'] = profile['timezone']
        if hasattr(time, 'tzset'):
            time.tzset()
        action = request.get('action', 'snapshot')
        today = dt.datetime.now(ZoneInfo(profile['timezone'])).date().isoformat()
        if action == 'snapshot':
            # Also catches added time from before the bar counted it, or from a restored backup.
            _mirror_manual(db, data)
            return snapshot(db, profile, data, request.get('week_start'))
        if action == 'save_profile':
            proposed = request['profile']
            reviews.validate_templates(proposed.get('task_templates', []))
            # Validate and check compatibility before committing configuration.
            domain.validate_profile(proposed)
            installed = data.parent / 'plugins/timer.py'
            if installed.exists() and 'PERSONAL_OS_TIMER_API = ' not in installed.read_text(encoding='utf-8'):
                raise ValueError(_('请先升级共享计时插件再修改类别；原数据仍可查看。'))
            mirrors = [data / 'personal-os-categories.json', data / 'personal-os-settings.json']
            originals = {path: path.read_bytes() if path.exists() else None for path in mirrors}
            changed = []
            try:
                profile = domain.save_profile(db, proposed, before_commit=lambda value: changed.append(_mirror_categories(data, value, refresh=False)))
            except BaseException:
                for path, content in originals.items():
                    if content is None:
                        if path.is_file():
                            path.unlink()
                    else:
                        temporary = path.with_suffix('.rollback')
                        temporary.write_bytes(content)
                        temporary.replace(path)
                raise
            if any(changed) and installed.exists() and not os.environ.get('PERSONAL_OS_NO_BAR'):
                import subprocess
                subprocess.run(['sketchybar', '--reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            reviews.sync_occurrences(db, profile.get('task_templates', []), today)
        elif action == 'timer':
            _mirror_categories(data, profile)
            command = request['command']
            category = request.get('category')
            if command in ('start', 'switch') and category:
                active = {c['id'] for c in profile['categories'] if not c.get('archived')}
                if category not in active:
                    raise ValueError(_('不能开始已归档的类别'))
            timer_bridge.command(data, command, category,
                                 refresh=not os.environ.get('PERSONAL_OS_NO_BAR') and (data.parent / 'plugins/timer.py').exists())
        elif action == 'add_activity':
            domain.add_manual_activity(db, request)
            _mirror_manual(db, data)
        elif action == 'delete_activity':
            record = request.get('id')
            if isinstance(record, str) and record.startswith('focus:') and record[6:].isdigit():
                timer_bridge.delete_record(data, int(record[6:]),
                                           refresh=not os.environ.get('PERSONAL_OS_NO_BAR') and (data.parent / 'plugins/timer.py').exists())
            elif isinstance(record, str) and record.startswith('legacy:'):
                raise ValueError(_('旧日志里的记录不能在应用里删除'))
            else:
                domain.delete_manual_activity(db, record)
                _mirror_manual(db, data)
        elif action == 'complete_task':
            reviews.sync_occurrences(db, profile.get('task_templates', []), today)
            reviews.update_occurrence(db, request['id'], request['status'], request.get('text', ''), today)
        elif action == 'save_review':
            state = snapshot(db, profile, data, request['week_start'])
            reviews.save_weekly_review(db, state['week_start'], state['week_end'], request.get('text', ''),
                                       request.get('completed', False), state['statistics'], profile)
        elif action == 'export':
            reviews.sync_occurrences(db, profile.get('task_templates', []), today)
            all_records, _timer, _source = legacy.read_activities(data, '0001-01-01', '9999-12-31', int(time.time()))
            return {'path': backup.export_bundle(db_path, data, profile,
                    all_records + domain.list_manual_activities(db), reviews.list_occurrences(db, today),
                    reviews.list_weekly_reviews(db), request['path'],
                    overwrite=request.get('overwrite') is True)}
        elif action == 'import':
            _records, current, _source = legacy.read_activities(data, today, today, int(time.time()))
            if current['active']:
                raise ValueError(_('请先保存或丢弃当前计时，再恢复备份'))
            destination = root / 'restores' / ('restore-' + str(time.time_ns()))
            backup.restore_bundle(request['path'], destination)
            # Keep timing on the ledger SketchyBar writes; the restored copy is an archive.
            timer_dir = data if has_ledger(data) else destination / 'legacy'
            pointer = root / '.workspace.tmp'
            pointer.write_text(json.dumps({'path': str(destination), 'timer_dir': str(timer_dir)}), encoding='utf-8')
            pointer.replace(root / 'workspace.json')
        else:
            raise ValueError(_('未知操作'))
        return {'ok': True}
    finally:
        db.close()


if __name__ == '__main__':
    try:
        result = dispatch(json.load(sys.stdin))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)

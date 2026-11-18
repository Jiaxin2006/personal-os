"""Consistent SQLite snapshots; never copy a live database as an ordinary file."""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from personal_os.i18n import _


def sqlite_bytes(path):
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / 'snapshot.sqlite3'
        source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
            # The copy inherits WAL mode; a backup should open without -wal/-shm sidecars.
            target.execute('PRAGMA journal_mode=DELETE')
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError(_('数据库备份完整性检查失败'))
        finally:
            target.close()
            source.close()
        return snapshot.read_bytes()


def backup_directory(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(_('备份来源目录不存在'))
    if destination.exists() or source == destination or source in destination.parents:
        raise ValueError(_('备份必须使用来源目录之外的新位置'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.personal-os-backup-', dir=destination.parent))
    manifest = {'format_version': 1, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'files': {}}
    try:
        for path in sorted(source.rglob('*')):
            if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts:
                continue
            if path.name.endswith(('-wal', '-shm', '-journal')):
                continue
            relative = path.relative_to(source)
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in ('.sqlite3', '.sqlite', '.db'):
                target.write_bytes(sqlite_bytes(path))
            else:
                shutil.copy2(path, target)
            manifest['files'][str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
        (staged / 'backup-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        staged.rename(destination)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return destination


def export_bundle(db_path, legacy_dir, profile, activities, tasks, reviews, destination, overwrite=False):
    """overwrite=True only after the user confirmed replacing the file in a save dialog."""
    destination = Path(destination).expanduser()
    legacy_dir = Path(legacy_dir)
    # Files in the timer folder are themselves exported, so a backup there would nest.
    if destination.resolve().parent == legacy_dir.resolve():
        raise ValueError(_('请把备份保存到计时数据目录之外'))
    if destination.is_dir():
        raise ValueError(_('备份位置是文件夹，请选择文件名'))
    if destination.exists() and not overwrite:
        raise ValueError(_('备份文件已存在，请换一个文件名'))
    payload = {'format': 'personal-os-backup', 'version': 1,
               'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'profile': profile, 'activities': activities, 'tasks': tasks, 'reviews': reviews,
               'app_database_base64': base64.b64encode(sqlite_bytes(db_path)).decode('ascii'),
               'legacy_files': {}}
    for path in sorted(legacy_dir.glob('*')):
        if not path.is_file():
            continue
        if path.suffix in ('.sqlite3', '.sqlite', '.db'):
            raw = sqlite_bytes(path)
        elif path.suffix in ('.log', '.json'):
            raw = path.read_bytes()
        else:
            continue
        payload['legacy_files'][path.name] = base64.b64encode(raw).decode('ascii')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target, then rename: a failed export never leaves a partial file,
    # and a confirmed replacement swaps the old backup only after the new one is complete.
    descriptor, name = tempfile.mkstemp(prefix='.personal-os-export-', suffix='.json', dir=destination.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        if overwrite:
            staged.replace(destination)
        else:
            # link() fails if the name appeared meanwhile, so nothing is replaced unasked.
            try:
                os.link(staged, destination)
            except FileExistsError:
                raise ValueError(_('备份文件已存在，请换一个文件名')) from None
    finally:
        staged.unlink(missing_ok=True)
    return str(destination)


def restore_bundle(source, destination):
    """Validate in a new directory; the caller switches workspaces only on success."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError(_('恢复必须使用新目录'))
    payload = json.loads(Path(source).read_text(encoding='utf-8'))
    if payload.get('format') != 'personal-os-backup' or payload.get('version') != 1:
        raise ValueError(_('不是支持的 Personal OS 备份版本'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.restore-', dir=destination.parent))
    try:
        (staged / 'legacy').mkdir()
        app = staged / 'personal_os.sqlite3'
        app.write_bytes(base64.b64decode(payload['app_database_base64'], validate=True))
        files = payload.get('legacy_files', {})
        if not isinstance(files, dict):
            raise ValueError(_('备份来源清单无效'))
        for name, encoded in files.items():
            if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
                raise ValueError(_('备份包含无效文件名'))
            if Path(name).suffix not in ('.sqlite3', '.sqlite', '.db', '.log', '.json'):
                raise ValueError(_('备份包含不支持的来源文件'))
            (staged / 'legacy' / name).write_bytes(base64.b64decode(encoded, validate=True))
        databases = [app] + [p for p in (staged / 'legacy').glob('*') if p.suffix in ('.sqlite3', '.sqlite', '.db')]
        for path in databases:
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError(_('备份数据库损坏'))
                if path == app:
                    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    required = {'profile_versions', 'manual_activities', 'task_template_state', 'task_occurrences', 'weekly_reviews'}
                    if not required <= names or not db.execute('SELECT 1 FROM profile_versions LIMIT 1').fetchone():
                        raise ValueError(_('备份缺少应用数据表或初始配置'))
            finally:
                db.close()
        from personal_os import domain, reviews
        db = domain.connect(app)
        try:
            profile = domain.validate_profile(domain.get_profile(db))
            reviews.validate_templates(profile.get('task_templates', []))
            reviews.initialize(db)
        finally:
            db.close()
        timer_path = staged / 'legacy/focus.sqlite3'
        if timer_path.exists():
            from personal_os import timer_bridge
            t = timer_bridge.engine(staged / 'legacy')
            db = t.connect(staged / 'legacy')
            try:
                with db:
                    state = t.load(db, 0, cache=staged / 'no-cache')
                    if t.running(state):
                        t.pause(state, max(state['anchor'], state['last_tick']))
                        db.execute('INSERT OR REPLACE INTO state(id,value) VALUES(1,?)', (json.dumps(state),))
            finally:
                db.close()
        staged.rename(destination)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return destination

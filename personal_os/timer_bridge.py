"""Native controls and SketchyBar share the same state machine and ledger."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from personal_os import domain
from personal_os.i18n import _

ENGINE_PATH = Path(__file__).resolve().parents[1] / 'plugins/timer.py'


def engine(data):
    spec = importlib.util.spec_from_file_location('personal_os_timer_engine', ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CATEGORIES = module.category_labels(Path(data))
    return module


def sync_categories(data, categories, refresh=True):
    data = Path(data)
    labels = {item['id']: domain.bar_label(item) for item in categories}
    text = json.dumps(labels, ensure_ascii=False, sort_keys=True)
    path = data / 'personal-os-categories.json'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    data.mkdir(parents=True, exist_ok=True)
    temporary = data / '.personal-os-categories.tmp'
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)
    if refresh and shutil.which('sketchybar'):
        subprocess.run(['sketchybar', '--reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    return True


def _boot_time():
    if not shutil.which('sysctl'):
        return None
    result = subprocess.run(['sysctl', '-n', 'kern.boottime'], capture_output=True, text=True, timeout=5)
    match = re.search(r'sec = (\d+)', result.stdout)
    return int(match[1]) if match else None


def refresh_bar_stats(data):
    focus = Path(data).parent / 'plugins/focus.sh'
    if focus.exists():
        env = dict(os.environ, CONFIG_DIR=str(Path(data).parent), NAME='focus', SENDER='timer_saved')
        subprocess.run([str(focus)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def delete_record(data, session_id, now=None, refresh=True):
    """Delete one saved timer record from the shared ledger; the engine keeps a copy."""
    data = Path(data)
    t = engine(data)
    now = int(time.time()) if now is None else int(now)
    db = t.connect(data)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not t.delete_session(db, session_id, now):
                raise ValueError(_('这条计时记录不存在'))
    finally:
        db.close()
    if refresh and shutil.which('sketchybar'):
        try:
            refresh_bar_stats(data)
        except (subprocess.SubprocessError, OSError):
            pass
    return {'ok': True}


def command(data, action, category=None, now=None, boot_time=None, refresh=True):
    data = Path(data)
    t = engine(data)
    now = int(time.time()) if now is None else int(now)
    if action not in ('start', 'pause', 'resume', 'stop', 'switch', 'discard', 'restore', 'tick', 'sleep', 'wake'):
        raise ValueError(_('未知计时操作'))
    if category is not None and category not in t.CATEGORIES:
        raise ValueError(_('请先保存这个活动类别'))
    if boot_time is None:
        boot_time = _boot_time()
    saved = sound = False
    db = t.connect(data)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            state = t.load(db, now, cache=data / 'legacy-cache-disabled')
            if t.running(state) and state['last_tick'] and boot_time and state['last_tick'] < boot_time:
                t.pause(state, max(state['anchor'], state['last_tick']))
            if action == 'tick' and t.running(state) and state['last_tick'] and now - state['last_tick'] > 60:
                t.pause(state, max(state['anchor'], state['last_tick']))
            if action == 'start':
                if state['mode'] != 'idle':
                    raise ValueError(_('已有活动，请使用继续或切换活动'))
                state.update(t.fresh(category or state['category']))
                state.update(mode='up', anchor=now)
            elif action == 'pause' or action == 'sleep':
                t.pause(state, now)
            elif action == 'wake':
                if t.running(state):
                    t.pause(state, max(state['anchor'], state['last_tick']))
            elif action == 'resume':
                if state['mode'].endswith('_paused'):
                    state.update(mode=state['mode'].removesuffix('_paused'), anchor=now)
            elif action == 'stop':
                if state['mode'] != 'idle':
                    t.save_session(db, state, now)
                    saved = True
            elif action == 'switch':
                if not category:
                    raise ValueError(_('请选择要切换的活动'))
                if state['mode'] != 'idle':
                    t.save_session(db, state, now)
                    saved = True
                state.update(t.fresh(category))
                state.update(mode='up', anchor=now)
            elif action == 'discard':
                saved = t.discard_session(db, state, now)
            elif action == 'restore':
                saved = t.restore_last_discarded(db, now)
            _state, sound = t.transition(db, state, now, 'native', 'routine')
        if refresh and shutil.which('sketchybar'):
            try:
                t.render_timer(state, now)
                if saved:
                    refresh_bar_stats(data)
            except (subprocess.SubprocessError, OSError):
                pass
        if sound and refresh and Path('/System/Library/Sounds/Glass.aiff').exists():
            subprocess.Popen(['afplay', '/System/Library/Sounds/Glass.aiff'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'ok': True}
    finally:
        db.close()

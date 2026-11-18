"""End-to-end JSON client tests; every request starts a fresh isolated process."""
import base64
import copy
from contextlib import closing
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from personal_os import timer_bridge


PROJECT = Path(__file__).resolve().parents[1]


class PersonalCLIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app_data = self.root / 'application'
        self.source = self.root / 'source' / 'data'
        self.source.mkdir(parents=True)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        PERSONAL_OS_DATA_DIR=str(self.app_data),
                        SKETCHYBAR_DATA_DIR=str(self.source),
                        PERSONAL_OS_NO_BAR='1', TZ='Asia/Hong_Kong')
        self.today = dt.datetime.now(ZoneInfo('Asia/Hong_Kong')).date().isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def request(self, payload, succeeds=True):
        result = subprocess.run([sys.executable, str(PROJECT / 'personal_os/cli.py')],
                                input=json.dumps(payload, ensure_ascii=False), text=True,
                                capture_output=True, cwd=PROJECT, env=self.env, timeout=20)
        try:
            response = json.loads(result.stdout)
        except (ValueError, TypeError):
            self.fail('CLI did not return one JSON object: stdout=%r stderr=%r' %
                      (result.stdout, result.stderr))
        if succeeds:
            self.assertEqual(result.returncode, 0, response)
            self.assertNotIn('error', response)
        else:
            self.assertNotEqual(result.returncode, 0, response)
            self.assertIsInstance(response.get('error'), str)
            self.assertTrue(response['error'])
        return response

    def snapshot(self, **kwargs):
        return self.request(dict(action='snapshot', **kwargs))

    def direct_timer(self, command, now, category=None):
        # Importing the engine also reads its catalog; override HOME and source
        # for the entire call so even that read cannot touch real personal data.
        original_tz = os.environ.get('TZ')
        try:
            with patch.dict(os.environ, self.env):
                if hasattr(time, 'tzset'):
                    time.tzset()
                return timer_bridge.command(self.source, command, category=category,
                                            now=now, boot_time=1, refresh=False)
        finally:
            if original_tz is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = original_tz
            if hasattr(time, 'tzset'):
                time.tzset()

    def seed_legacy(self):
        with patch.dict(os.environ, self.env):
            engine = timer_bridge.engine(self.source)
            db = engine.connect(self.source)
            try:
                with db:
                    db.execute('INSERT INTO sessions(day,category,seconds) VALUES(?,?,?)',
                               (self.today, 'research', 7200))
                    db.execute('INSERT INTO state(id,value) VALUES(1,?)',
                               (json.dumps(engine.fresh('reading')),))
                    db.execute('CREATE TABLE recovery_events (evidence_key TEXT PRIMARY KEY, details TEXT)')
                    db.execute("INSERT INTO recovery_events VALUES('proof','keep exactly')")
            finally:
                db.close()
        (self.source / ('focus_%s.log' % self.today)).write_text('08:00:00 300\n', encoding='utf-8')

    @staticmethod
    def database_dump(path):
        db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            return '\n'.join(db.iterdump())
        finally:
            db.close()

    def test_snapshot_contract_and_empty_read_isolation(self):
        state = self.snapshot()
        self.assertTrue({'profile', 'today', 'week_start', 'week_end', 'statistics', 'timer',
                         'activities', 'tasks', 'reviews', 'trends', 'source'} <= set(state))
        self.assertEqual(state['today'], self.today)
        self.assertTrue({'work_seconds', 'total_seconds', 'research_seconds', 'research_days',
                         'reading_days', 'category_totals', 'days', 'goals'} <= set(state['statistics']))
        self.assertEqual(state['statistics']['total_seconds'], 0)
        self.assertEqual(len(state['statistics']['days']), 7)
        self.assertEqual(len(state['trends']), 4)
        for goal in state['statistics']['goals']:
            self.assertTrue({'id', 'name', 'kind', 'strength', 'actual', 'target',
                             'unit', 'status', 'progress'} <= set(goal))
        self.assertTrue({'mode', 'category', 'elapsed_seconds', 'running', 'active', 'available'} <= set(state['timer']))
        self.assertFalse(state['timer']['active'])
        self.assertEqual(state['source']['path'], str(self.source))
        self.assertTrue(state['source']['read_only'])
        self.assertFalse((self.source / 'focus.sqlite3').exists())
        self.assertEqual(list(self.home.iterdir()), [])
        for task in state['tasks']:
            self.assertTrue({'id', 'template_id', 'name', 'description', 'period_key',
                             'visible_from', 'due_on', 'status', 'is_visible', 'is_overdue',
                             'completed_at', 'review_text'} <= set(task))

    def test_manual_activity_survives_process_restart_and_can_be_deleted(self):
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'reading', 'seconds': 1800})
        state = self.snapshot()
        self.assertEqual(state['statistics']['reading_days'], 1)
        self.assertEqual(state['statistics']['total_seconds'], 1800)
        activity = state['activities'][0]
        self.assertEqual((activity['source'], activity['precision'], activity['saved']), ('manual', 'day', True))
        self.request({'action': 'delete_activity', 'id': activity['id']})
        self.assertEqual(self.snapshot()['statistics']['total_seconds'], 0)
        self.request({'action': 'delete_activity', 'id': 'focus:1'}, succeeds=False)

    def test_profile_edit_custom_category_goal_and_stale_revision(self):
        original = self.snapshot()['profile']
        edited = copy.deepcopy(original)
        edited['categories'].append({'id': 'writing', 'name': '写作', 'bar_label': 'Writing', 'counts_as_work': True, 'archived': False})
        edited['goals'].append({'id': 'writing-hours', 'name': '写作投入', 'period': 'week',
                                'kind': 'minimum_duration', 'strength': 'flexible',
                                'filter': {'category_ids': ['writing']}, 'minimum_seconds': 3600})
        self.request({'action': 'save_profile', 'profile': edited})
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'writing', 'seconds': 3600})
        state = self.snapshot()
        self.assertGreater(state['profile']['revision'], original['revision'])
        self.assertEqual(state['statistics']['work_seconds'], 3600)
        goal = next(goal for goal in state['statistics']['goals'] if goal['id'] == 'writing-hours')
        self.assertEqual((goal['actual'], goal['status']), (3600, 'met'))
        self.assertEqual(json.loads((self.source / 'personal-os-categories.json').read_text())['writing'], 'Writing')
        self.request({'action': 'save_profile', 'profile': original}, succeeds=False)
        self.assertEqual(self.snapshot()['profile'], state['profile'])

    def test_status_bar_gets_one_english_word_per_category(self):
        profile = self.snapshot()['profile']
        self.request({'action': 'save_profile', 'profile': profile})
        mirror = json.loads((self.source / 'personal-os-categories.json').read_text(encoding='utf-8'))
        self.assertEqual(mirror['course'], 'Study')
        self.assertTrue(all(label.isascii() and label.isalnum() for label in mirror.values()), mirror)
        # Profiles from before bar labels existed fall back to the built-in words.
        legacy = copy.deepcopy(self.snapshot()['profile'])
        for category in legacy['categories']:
            category.pop('bar_label')
        legacy['categories'].append({'id': 'category-1a2b3c4d', 'name': '写作', 'counts_as_work': True})
        self.request({'action': 'save_profile', 'profile': legacy})
        mirror = json.loads((self.source / 'personal-os-categories.json').read_text(encoding='utf-8'))
        self.assertEqual((mirror['research'], mirror['category-1a2b3c4d']), ('Research', 'Custom'))
        self.assertEqual(next(c for c in self.snapshot()['profile']['categories'] if c['id'] == 'reading')['bar_label'], 'Reading')
        for invalid in ('写作', 'Deep Work', '1st', 'A' * 17):
            bad = copy.deepcopy(self.snapshot()['profile'])
            bad['categories'][0]['bar_label'] = invalid
            self.request({'action': 'save_profile', 'profile': bad}, succeeds=False)

    def test_invalid_task_rule_is_rejected_before_profile_write(self):
        original = self.snapshot()['profile']
        invalid = copy.deepcopy(original)
        monthly = next(t for t in invalid['task_templates'] if t['recurrence']['kind'] == 'monthly')
        monthly['recurrence']['day'] = 32
        self.request({'action': 'save_profile', 'profile': invalid}, succeeds=False)
        self.assertEqual(self.snapshot()['profile'], original)

    def test_failed_category_catalog_write_does_not_commit_profile(self):
        original = self.snapshot()['profile']
        proposed = copy.deepcopy(original)
        proposed['categories'][0]['name'] = '修改后的科研名称'
        # A filesystem obstruction is deterministic on all platforms, unlike
        # permission bits when tests run with elevated privileges.
        (self.source / 'personal-os-categories.json').mkdir()
        self.request({'action': 'save_profile', 'profile': proposed}, succeeds=False)
        self.assertEqual(self.snapshot()['profile'], original)

    def test_cli_timer_controls_reopen_same_source_ledger(self):
        self.request({'action': 'timer', 'command': 'start', 'category': 'research'})
        self.assertTrue(self.snapshot()['timer']['running'])
        self.request({'action': 'timer', 'command': 'pause'})
        self.assertEqual(self.snapshot()['timer']['mode'], 'up_paused')
        self.request({'action': 'timer', 'command': 'resume'})
        self.assertTrue(self.snapshot()['timer']['running'])
        self.request({'action': 'timer', 'command': 'switch', 'category': 'reading'})
        self.request({'action': 'timer', 'command': 'pause'})
        paused = self.snapshot()['timer']
        self.assertEqual((paused['category'], paused['mode']), ('reading', 'up_paused'))
        self.request({'action': 'timer', 'command': 'stop'})
        self.assertFalse(self.snapshot()['timer']['active'])
        self.assertTrue((self.source / 'focus.sqlite3').exists())
        self.assertFalse((self.app_data / 'timer/focus.sqlite3').exists())

    def test_deterministic_timer_pause_switch_and_cold_snapshot(self):
        now = int(dt.datetime.combine(dt.date.fromisoformat(self.today), dt.time(9),
                                     tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp())
        self.direct_timer('start', now, 'research')
        self.direct_timer('pause', now + 60)
        self.assertEqual(self.snapshot()['timer']['elapsed_seconds'], 60)
        self.direct_timer('resume', now + 3600)
        self.direct_timer('switch', now + 3660, 'reading')
        self.direct_timer('pause', now + 3720)
        paused = self.snapshot()
        self.assertEqual(paused['timer']['elapsed_seconds'], 60)
        self.assertEqual(paused['statistics']['research_seconds'], 120)
        self.assertEqual(paused['statistics']['total_seconds'], 120)
        self.assertEqual(paused['statistics']['preview_seconds'], 60)
        self.direct_timer('stop', now + 4000)
        saved = self.snapshot()
        self.assertEqual(saved['statistics']['total_seconds'], 180)
        self.assertEqual(saved['statistics']['reading_days'], 0)
        self.assertFalse(saved['timer']['active'])
        with closing(sqlite3.connect(self.source / 'focus.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT category,seconds FROM sessions ORDER BY id').fetchall(),
                             [('research', 120), ('reading', 60)])

    def test_saved_record_shows_clock_times_and_can_be_deleted(self):
        now = int(dt.datetime.combine(dt.date.fromisoformat(self.today), dt.time(9),
                                     tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp())
        self.direct_timer('start', now, 'research')
        self.direct_timer('stop', now + 5400)
        (self.source / ('focus_%s.log' % self.today)).write_text('17:22:01 600\n', encoding='utf-8')
        activities = self.snapshot()['activities']
        record = next(a for a in activities if a['id'].startswith('focus:'))
        self.assertEqual((record['start_time'], record['end_time'], record['seconds']), ('09:00', '10:30', 5400))
        old = next(a for a in activities if a['id'].startswith('legacy:'))
        self.assertEqual(old['logged_time'], '17:22')
        self.request({'action': 'delete_activity', 'id': record['id']})
        self.assertNotIn(record['id'], [a['id'] for a in self.snapshot()['activities']])
        with closing(sqlite3.connect(self.source / 'focus.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM deleted_sessions').fetchone()[0], 1)
        self.request({'action': 'delete_activity', 'id': record['id']}, succeeds=False)
        self.request({'action': 'delete_activity', 'id': old['id']}, succeeds=False)

    def test_added_time_is_shared_with_the_status_bar(self):
        mirror = self.source / 'personal-os-manual.json'
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'reading', 'seconds': 1800})
        self.assertEqual(json.loads(mirror.read_text(encoding='utf-8')),
                         [{'day': self.today, 'category': 'reading', 'seconds': 1800}])
        added = next(a for a in self.snapshot()['activities'] if a['source'] == 'manual')
        self.request({'action': 'delete_activity', 'id': added['id']})
        self.assertEqual(json.loads(mirror.read_text(encoding='utf-8')), [])
        mirror.unlink()
        self.snapshot()
        self.assertTrue(mirror.exists())

    def test_task_completion_and_review_survive_new_process(self):
        state = self.snapshot()
        task = state['tasks'][0]
        self.request({'action': 'complete_task', 'id': task['id'], 'status': 'completed', 'text': '本期已复盘'})
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'research', 'seconds': 3600})
        self.request({'action': 'save_review', 'week_start': state['week_start'], 'text': '本周结论', 'completed': True})
        saved = self.snapshot()
        task_saved = next(item for item in saved['tasks'] if item['id'] == task['id'])
        self.assertEqual((task_saved['status'], task_saved['review_text']), ('completed', '本期已复盘'))
        self.assertIsNotNone(task_saved['completed_at'])
        review = saved['reviews'][0]
        self.assertEqual((review['text'], review['completed']), ('本周结论', True))
        self.assertEqual(review['statistics']['research_seconds'], 3600)
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'research', 'seconds': 1800})
        self.assertEqual(self.snapshot()['reviews'][0]['statistics']['research_seconds'], 3600)

    def test_future_tasks_stay_accessible_but_hidden_from_daily(self):
        profile = self.snapshot()['profile']
        future_start = (dt.date.fromisoformat(self.today) + dt.timedelta(days=40)).isoformat()
        profile['task_templates'].append({'id': 'future-review', 'name': '未来复盘',
                                          'starts_on': future_start, 'enabled': True,
                                          'recurrence': {'kind': 'monthly', 'day': 'last'},
                                          'visibility': {'kind': 'calendar_days_ending_on_due', 'days': 7},
                                          'deadline': {'kind': 'recurrence_date_end'}})
        self.request({'action': 'save_profile', 'profile': profile})
        item = next(task for task in self.snapshot()['tasks'] if task['template_id'] == 'future-review')
        self.assertFalse(item['is_visible'])
        self.assertFalse(item['is_overdue'])
        self.assertGreaterEqual(item['visible_from'], future_start)

    def test_export_import_round_trip_preserves_totals_and_all_history(self):
        self.seed_legacy()
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'reading', 'seconds': 1800})
        before = self.snapshot()
        self.request({'action': 'complete_task', 'id': before['tasks'][0]['id'],
                      'status': 'completed', 'text': '历史任务结论'})
        self.request({'action': 'save_review', 'week_start': before['week_start'],
                      'text': '导出前复盘', 'completed': True})
        before = self.snapshot()
        bundle = self.root / 'backup.json'
        self.assertEqual(self.request({'action': 'export', 'path': str(bundle)})['path'], str(bundle))
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'research', 'seconds': 999})
        self.assertEqual(self.snapshot()['statistics']['total_seconds'], before['statistics']['total_seconds'] + 999)
        self.request({'action': 'import', 'path': str(bundle)})
        restored = self.snapshot()
        self.assertEqual(restored['statistics'], before['statistics'])
        self.assertEqual(restored['profile'], before['profile'])
        self.assertEqual(restored['activities'], before['activities'])
        self.assertEqual(restored['tasks'], before['tasks'])
        self.assertEqual(restored['reviews'], before['reviews'])
        # Timing continues on the ledger SketchyBar writes; the backup's copy is an archive.
        self.assertEqual(restored['source']['path'], str(self.source))
        pointer = json.loads((self.app_data / 'workspace.json').read_text())
        selected = Path(pointer['path'])
        with closing(sqlite3.connect(selected / 'legacy/focus.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT * FROM recovery_events').fetchall(), [('proof', 'keep exactly')])
        self.assertEqual((selected / 'legacy' / ('focus_%s.log' % self.today)).read_bytes(),
                         (self.source / ('focus_%s.log' % self.today)).read_bytes())
        # A repeated restore switches to a new workspace but never double-counts.
        self.request({'action': 'import', 'path': str(bundle)})
        self.assertEqual(self.snapshot()['statistics'], before['statistics'])

    def test_import_keeps_timer_on_shared_ledger(self):
        self.seed_legacy()
        bundle = self.root / 'backup.json'
        self.request({'action': 'export', 'path': str(bundle)})
        self.request({'action': 'import', 'path': str(bundle)})
        selected = Path(json.loads((self.app_data / 'workspace.json').read_text())['path'])
        self.request({'action': 'timer', 'command': 'start', 'category': 'research'})

        def mode(folder):
            with closing(sqlite3.connect(folder / 'focus.sqlite3')) as db:
                return json.loads(db.execute('SELECT value FROM state WHERE id=1').fetchone()[0])['mode']
        self.assertEqual(mode(self.source), 'up')
        self.assertEqual(mode(selected / 'legacy'), 'idle')
        self.assertTrue(self.snapshot()['timer']['running'])

    def test_import_without_ledger_continues_backup_history(self):
        self.seed_legacy()
        bundle = self.root / 'backup.json'
        self.request({'action': 'export', 'path': str(bundle)})
        before = self.snapshot()['statistics']
        # Another Mac: no SketchyBar history and a fresh application folder.
        empty = self.root / 'other-mac-source'
        empty.mkdir()
        self.env.update(PERSONAL_OS_DATA_DIR=str(self.root / 'other-mac-app'), SKETCHYBAR_DATA_DIR=str(empty))
        self.request({'action': 'import', 'path': str(bundle)})
        restored = self.snapshot()
        selected = Path(json.loads((self.root / 'other-mac-app/workspace.json').read_text())['path'])
        self.assertEqual(restored['source']['path'], str(selected / 'legacy'))
        self.assertEqual(restored['statistics']['total_seconds'], before['total_seconds'])
        self.assertEqual(list(empty.iterdir()), [])

    def test_snapshot_does_not_rewrite_application_database(self):
        self.snapshot()
        database = self.app_data / 'personal_os.sqlite3'
        first = database.read_bytes()
        self.snapshot()
        self.snapshot(week_start=self.snapshot()['week_start'])
        self.assertEqual(database.read_bytes(), first)

    def test_invalid_import_keeps_current_pointer_and_logical_database(self):
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'reading', 'seconds': 1800})
        good = self.root / 'good.json'
        self.request({'action': 'export', 'path': str(good)})
        self.request({'action': 'import', 'path': str(good)})
        state = self.snapshot()
        pointer = self.app_data / 'workspace.json'
        pointer_before = pointer.read_bytes()
        selected = Path(json.loads(pointer_before)['path'])
        database = selected / 'personal_os.sqlite3'
        before = self.database_dump(database)
        payload = json.loads(good.read_text())
        forged_app = self.root / 'forged-app.sqlite3'
        forged_app.write_bytes(base64.b64decode(payload['app_database_base64']))
        with closing(sqlite3.connect(forged_app)) as db:
            with db:
                row = db.execute('SELECT id,profile_json FROM profile_versions ORDER BY id DESC LIMIT 1').fetchone()
                invalid_profile = json.loads(row[1])
                monthly = next(t for t in invalid_profile['task_templates'] if t['recurrence']['kind'] == 'monthly')
                monthly['recurrence']['day'] = 0
                db.execute('UPDATE profile_versions SET profile_json=? WHERE id=?',
                           (json.dumps(invalid_profile), row[0]))
        cases = [
            dict(payload, version=999),
            dict(payload, app_database_base64='not base64!'),
            dict(payload, app_database_base64=base64.b64encode(b'not sqlite').decode('ascii')),
            dict(payload, legacy_files={'../outside.json': base64.b64encode(b'{}').decode('ascii')}),
            dict(payload, app_database_base64=base64.b64encode(forged_app.read_bytes()).decode('ascii')),
        ]
        for index, invalid in enumerate(cases):
            with self.subTest(case=index):
                path = self.root / ('invalid-%d.json' % index)
                path.write_text(json.dumps(invalid), encoding='utf-8')
                self.request({'action': 'import', 'path': str(path)}, succeeds=False)
                self.assertEqual(pointer.read_bytes(), pointer_before)
                self.assertEqual(self.database_dump(database), before)
                self.assertEqual(self.snapshot()['statistics'], state['statistics'])
                self.assertFalse((self.app_data / 'outside.json').exists())

    def test_export_refuses_overwriting_and_active_timer_blocks_import(self):
        self.snapshot()
        bundle = self.root / 'backup.json'
        self.request({'action': 'export', 'path': str(bundle)})
        original = bundle.read_bytes()
        refused = self.request({'action': 'export', 'path': str(bundle)}, succeeds=False)
        self.assertIn('已存在', refused['error'])
        self.assertEqual(bundle.read_bytes(), original)
        self.request({'action': 'add_activity', 'day': self.today, 'category': 'reading', 'seconds': 60})
        self.request({'action': 'export', 'path': str(bundle), 'overwrite': True})
        self.assertNotEqual(bundle.read_bytes(), original)
        self.request({'action': 'timer', 'command': 'start', 'category': 'reading'})
        self.request({'action': 'import', 'path': str(bundle)}, succeeds=False)
        self.assertFalse((self.app_data / 'workspace.json').exists())
        self.assertTrue(self.snapshot()['timer']['active'])


if __name__ == '__main__':
    unittest.main()

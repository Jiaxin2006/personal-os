import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from personal_os import reviews as r


def template(kind='monthly', starts_on='2026-11-01', **recurrence):
    rule = {'kind': kind}
    rule.update({'weekday': 'sunday'} if kind == 'weekly' else {'day': 'last'})
    rule.update(recurrence)
    return {'id': 'review', 'name': '复盘', 'description': '记下本期结论',
            'enabled': True, 'starts_on': starts_on, 'recurrence': rule,
            'visibility': {'kind': 'calendar_days_ending_on_due', 'days': 7},
            'deadline': {'kind': 'recurrence_date_end'}}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'app.sqlite3'
        self.db = sqlite3.connect(self.path)
        r.initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_last_seven_days_window_and_inclusive_deadline(self):
        t = template()
        before = r.sync_occurrences(self.db, [t], '2026-11-23')[0]
        self.assertEqual((before['visible_from'], before['due_on']), ('2026-11-24', '2026-11-30'))
        self.assertFalse(before['is_visible'])
        self.assertTrue(r.list_occurrences(self.db, '2026-11-24')[0]['is_visible'])
        self.assertFalse(r.list_occurrences(self.db, '2026-11-30')[0]['is_overdue'])
        self.assertTrue(r.list_occurrences(self.db, '2026-12-01')[0]['is_overdue'])

    def test_leap_year_and_short_month_numeric_deadline(self):
        for year, expected in [(2027, '2027-02-28'), (2028, '2028-02-29')]:
            t = template(starts_on='%d-02-01' % year, day=31)
            t['id'] = str(year)
            items = r.sync_occurrences(self.db, [t], '%d-02-15' % year)
            item = next(item for item in items if item['template_id'] == str(year))
            self.assertEqual(item['due_on'], expected)
            self.assertEqual(item['visible_from'], '%d-02-%s' % (year, '22' if year == 2027 else '23'))

    def test_week_quarter_and_year_boundaries(self):
        specs = [('weekly', '2026-12-28', '2027-01-03'),
                 ('quarterly', '2026-10-01', '2026-12-31'),
                 ('yearly', '2026-01-01', '2026-12-31')]
        for kind, activation, expected in specs:
            t = template(kind, starts_on=activation)
            t['id'] = kind
            items = r.sync_occurrences(self.db, [t], '2026-12-31')
            upcoming = next(item for item in items if item['template_id'] == kind and item['due_on'] >= '2026-12-31')
            self.assertEqual(upcoming['due_on'], expected)

    def test_weekday_and_year_month_are_editable(self):
        t = template('weekly', '2026-11-01', weekday='wednesday')
        self.assertEqual(r.sync_occurrences(self.db, [t], '2026-11-01')[0]['due_on'], '2026-11-04')
        t = template('yearly', '2026-01-01', month=3, day=15)
        t['id'] = 'year'
        items = r.sync_occurrences(self.db, [t], '2026-02-01')
        self.assertEqual(next(item for item in items if item['template_id'] == 'year')['due_on'], '2026-03-15')

    def test_reopen_months_later_backfills_and_is_idempotent(self):
        t = template(starts_on=None)
        november = r.sync_occurrences(self.db, [t], '2026-11-05')[0]
        self.db.close()
        self.db = sqlite3.connect(self.path)
        r.initialize(self.db)
        items = r.sync_occurrences(self.db, [t], '2027-02-03')
        self.assertEqual([item['period_key'] for item in items], ['2027-02', '2027-01', '2026-12', '2026-11'])
        self.assertEqual(next(item for item in items if item['period_key'] == '2026-11')['id'], november['id'])
        self.assertEqual(len(r.sync_occurrences(self.db, [t], '2027-02-03')), 4)

    def test_activation_never_creates_prior_due_or_prior_visible_days(self):
        t = template(starts_on=None)
        item = r.sync_occurrences(self.db, [t], '2026-11-29')[0]
        self.assertEqual(item['visible_from'], '2026-11-29')
        weekly = template('weekly', starts_on=None, weekday='wednesday')
        weekly['id'] = 'weekly'
        items = r.sync_occurrences(self.db, [t, weekly], '2026-11-05')
        item = next(item for item in items if item['template_id'] == 'weekly')
        self.assertEqual(item['due_on'], '2026-11-11')

    def test_template_edits_preserve_open_and_completed_instances(self):
        t = template()
        old = r.sync_occurrences(self.db, [t], '2026-11-05')[0]
        r.update_occurrence(self.db, old['id'], 'completed', '旧结论', '2026-11-30')
        t['name'] = '新名字'
        t['visibility']['days'] = 3
        items = r.sync_occurrences(self.db, [t], '2026-12-05')
        previous = next(item for item in items if item['period_key'] == '2026-11')
        current = next(item for item in items if item['period_key'] == '2026-12')
        self.assertEqual(previous['name'], '复盘')
        self.assertEqual(previous['visible_from'], '2026-11-24')
        self.assertEqual(previous['status'], 'completed')
        self.assertEqual(previous['review_text'], '旧结论')
        self.assertEqual(current['name'], '新名字')
        self.assertEqual(current['visible_from'], '2026-12-29')

    def test_changed_rule_backfills_old_periods_then_applies_only_forward(self):
        t = template()
        r.sync_occurrences(self.db, [t], '2026-11-05')
        t['recurrence'] = {'kind': 'weekly', 'weekday': 'sunday'}
        t['name'] = '改为周复盘'
        items = r.sync_occurrences(self.db, [t], '2027-02-03')
        old = {item['period_key']: item for item in items if item['period_key'] in ('2026-11', '2026-12', '2027-01')}
        self.assertEqual(set(old), {'2026-11', '2026-12', '2027-01'})
        self.assertTrue(all(item['name'] == '复盘' for item in old.values()))
        weeks = [item for item in items if item['name'] == '改为周复盘']
        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0]['due_on'], '2027-02-07')

    def test_validation_can_run_before_any_database_mutation(self):
        t = template()
        self.assertEqual(r.validate_templates([t]), [t])
        with self.assertRaises(ValueError):
            r.validate_templates([t, t])
        t['recurrence']['day'] = 32
        with self.assertRaises(ValueError):
            r.validate_templates([t])

    def test_late_completion_and_skip_are_per_occurrence(self):
        items = r.sync_occurrences(self.db, [template()], '2026-12-10')
        november = next(item for item in items if item['period_key'] == '2026-11')
        december = next(item for item in items if item['period_key'] == '2026-12')
        r.update_occurrence(self.db, november['id'], 'completed', '补写十一月', '2026-12-10')
        r.update_occurrence(self.db, december['id'], 'skipped', '跳过', '2026-12-31')
        reopened = r.list_occurrences(self.db, '2027-01-01')
        self.assertEqual({item['period_key']: item['status'] for item in reopened},
                         {'2026-11': 'completed', '2026-12': 'skipped'})
        self.assertFalse(any(item['is_overdue'] for item in reopened))
        completed = r.update_occurrence(self.db, november['id'], 'completed', '改文字', '2027-01-02')
        self.assertIsNotNone(completed['completed_at'])

    def test_disabled_and_removed_templates_keep_history_but_hide_daily(self):
        t = template()
        old = r.sync_occurrences(self.db, [t], '2026-11-30')[0]
        t['enabled'] = False
        item = r.sync_occurrences(self.db, [t], '2026-12-31')[0]
        self.assertFalse(item['is_visible'])
        self.assertEqual(item['id'], old['id'])
        self.assertEqual(len(r.sync_occurrences(self.db, [], '2027-03-01')), 1)

    def test_weekly_draft_reopen_and_completed_snapshot_freeze(self):
        args = ('2026-11-02', '2026-11-08')
        saved = r.save_weekly_review(self.db, *args, '草稿', False, {'work_seconds': 100}, {'name': '初始'})
        completed = r.save_weekly_review(self.db, *args, '完成', True, {'work_seconds': 200}, {'name': '初始'})
        self.assertEqual(saved['id'], completed['id'])
        self.db.close()
        self.db = sqlite3.connect(self.path)
        r.initialize(self.db)
        edited = r.save_weekly_review(self.db, *args, '润色完成', True, {'work_seconds': 900}, {'name': '改目标'})
        self.assertEqual(edited['statistics']['work_seconds'], 200)
        self.assertEqual(edited['profile']['name'], '初始')
        self.assertEqual(edited['text'], '润色完成')
        r.save_weekly_review(self.db, *args, '重新打开', False, {'work_seconds': 900}, {})
        final = r.save_weekly_review(self.db, *args, '再次完成', True, {'work_seconds': 900}, {'name': '改目标'})
        self.assertEqual(final['statistics']['work_seconds'], 900)

    def test_invalid_batch_rolls_back_and_bad_dates_rejected(self):
        invalid = template()
        invalid['id'] = 'broken'
        invalid['recurrence']['day'] = 0
        with self.assertRaises(ValueError):
            r.sync_occurrences(self.db, [template(), invalid], '2026-11-01')
        self.assertEqual(r.list_occurrences(self.db, '2026-11-01'), [])
        with self.assertRaises(ValueError):
            r.sync_occurrences(self.db, [template('unknown')], '2026-11-01')
        with self.assertRaises(ValueError):
            r.sync_occurrences(self.db, [template()], '2026-02-30')
        with self.assertRaises(ValueError):
            r.save_weekly_review(self.db, '2026-11-02', '2026-11-01', '', False, {}, {})
        with self.assertRaises(ValueError):
            r.save_weekly_review(self.db, '2026-11-03', '2026-11-09', '', False, {}, {})

    def test_configurable_week_start(self):
        saved = r.save_weekly_review(self.db, '2026-11-01', '2026-11-07', '周日开始', True,
                                     {}, {'week_starts_on': 'sunday'})
        self.assertEqual(saved['week_start'], '2026-11-01')
        with self.assertRaises(ValueError):
            r.save_weekly_review(self.db, '2026-11-02', '2026-11-08', '', False,
                                 {}, {'week_starts_on': 'sunday'})

    def test_initial_profile_templates_are_supported(self):
        profile = json.loads((Path(__file__).parents[1] / 'personal_os/initial_profile.json').read_text())
        items = r.sync_occurrences(self.db, profile['task_templates'], '2026-11-05')
        self.assertEqual(len(items), 3)
        self.assertEqual({item['template_id'] for item in items},
                         {template['id'] for template in profile['task_templates']})

    def test_sqlite_row_factory_and_initialize_do_not_change_version(self):
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA user_version=7')
        r.initialize(self.db)
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 7)
        self.assertEqual(len(r.sync_occurrences(self.db, [template()], '2026-11-05')), 1)


if __name__ == '__main__':
    unittest.main()

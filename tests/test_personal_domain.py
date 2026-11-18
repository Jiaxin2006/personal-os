import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from personal_os import domain as d


FIRST, LAST, TODAY = "2026-11-02", "2026-11-08", "2026-11-05"


def activity(day, category, seconds, **extra):
    return dict(day=day, category=category, seconds=seconds, saved=True, **extra)


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "personal.sqlite3"
        self.db = d.connect(self.path)
        self.profile = d.get_profile(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def stats(self, records, profile=None):
        return d.build_statistics(profile or self.profile, records, FIRST, LAST, TODAY)

    def goal(self, result, identity):
        return next(g for g in result["goals"] if g["id"] == identity)

    def test_research_duration_and_frequency_are_independent(self):
        stats = self.stats([activity("2026-11-02", "research", 8 * 3600),
                            activity("2026-11-04", "research", 8 * 3600),
                            activity("2026-11-06", "research", 4 * 3600)])
        self.assertEqual(stats["research_seconds"], 72000)
        self.assertEqual(stats["research_days"], 3)
        self.assertEqual(self.goal(stats, "research-weekly-duration")["status"], "met")
        self.assertEqual(self.goal(stats, "research-weekly-frequency")["status"], "below")

    def test_reading_one_day_ninety_minutes_is_one_day(self):
        stats = self.stats([activity(FIRST, "reading", 5400)])
        self.assertEqual(stats["reading_days"], 1)
        self.assertEqual(self.goal(stats, "reading-weekly-frequency")["status"], "below")
        self.assertEqual(stats["work_seconds"], 0)

    def test_reading_three_days_accumulate_partial_sessions(self):
        records = [activity(day, "reading", 900) for day in (FIRST, "2026-11-03", "2026-11-04") for _ in range(2)]
        stats = self.stats(records)
        self.assertEqual(stats["reading_days"], 3)
        self.assertEqual(self.goal(stats, "reading-weekly-frequency")["status"], "met")

    def test_frequency_uses_seconds_and_configurable_threshold(self):
        records = [activity(FIRST, "reading", 1799), activity("2026-11-03", "reading", 1800)]
        self.assertEqual(self.stats(records)["reading_days"], 1)
        profile = copy.deepcopy(self.profile)
        goal = next(g for g in profile["goals"] if g["id"] == "reading-weekly-frequency")
        goal["minimum_daily_seconds"] = 900
        self.assertEqual(self.stats(records, profile)["reading_days"], 2)

    def test_split_midnight_reading_does_not_meet_either_day(self):
        stats = self.stats([activity(FIRST, "reading", 900), activity("2026-11-03", "reading", 900)])
        self.assertEqual(stats["reading_days"], 0)

    def test_preview_excluded_from_saved_goals(self):
        preview = activity(FIRST, "reading", 5400)
        preview["saved"] = False
        result = self.stats([preview])
        self.assertEqual(result["reading_days"], 0)
        self.assertEqual(result["total_seconds"], 0)
        self.assertEqual(result["preview_seconds"], 5400)

    def test_work_does_not_double_count_goal_associations(self):
        result = self.stats([activity(FIRST, "research", 3600,
                                     goal_ids=["research-weekly-duration", "course-weekly-range"])])
        self.assertEqual(result["total_seconds"], 3600)
        self.assertEqual(result["work_seconds"], 3600)
        self.assertEqual(self.goal(result, "research-weekly-duration")["actual"], 3600)
        self.assertEqual(self.goal(result, "course-weekly-range")["actual"], 3600)

    def test_duplicate_source_identity_only_counted_once(self):
        record = activity(FIRST, "research", 100, id="source-row-1")
        self.assertEqual(self.stats([record, dict(record)])["total_seconds"], 100)

    def test_unknown_categories_remain_visible_without_assumed_work(self):
        result = self.stats([activity(FIRST, "legacy_custom", 123)])
        category = next(c for c in result["category_totals"] if c["id"] == "legacy_custom")
        self.assertEqual(category, {"id": "legacy_custom", "name": "legacy_custom", "seconds": 123})
        self.assertEqual(result["work_seconds"], 0)
        self.assertEqual(result["total_seconds"], 123)

    def test_goal_range_ceiling_and_observation(self):
        profile = copy.deepcopy(self.profile)
        for hours, expected in [(3, "below"), (4, "met"), (6, "met"), (7, "over")]:
            with self.subTest(hours=hours):
                result = self.stats([activity(FIRST, "course", hours * 3600)], profile)
                self.assertEqual(self.goal(result, "course-weekly-range")["status"], expected)
        result = self.stats([activity(FIRST, "social", 18001), activity(FIRST, "other_work", 3600)])
        self.assertEqual(self.goal(result, "service-weekly-ceiling")["status"], "over")
        self.assertEqual(self.goal(result, "other-work-observe")["status"], "observing")

    def test_date_range_and_empty_day_buckets(self):
        result = self.stats([activity("2026-11-01", "research", 500), activity(LAST, "research", 100),
                             activity("2026-11-09", "research", 500)])
        self.assertEqual(result["total_seconds"], 100)
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["days"][0]["seconds"], 0)

    def test_calendar_year_and_leap_day_buckets(self):
        result = d.build_statistics(self.profile, [activity("2024-02-29", "research", 3600)],
                                    "2024-02-26", "2024-03-03", TODAY)
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["research_seconds"], 3600)
        result = d.build_statistics(self.profile, [], "2026-12-28", "2027-01-03", TODAY)
        self.assertEqual(len(result["days"]), 7)

    def test_profile_seed_activated_once_and_reopens(self):
        self.assertNotIn("status", self.profile)
        self.assertIsNotNone(self.profile["trial"]["started_on"])
        self.assertTrue(all(t["starts_on"] for t in self.profile["task_templates"]))
        changed = copy.deepcopy(self.profile)
        changed["goals"][0]["minimum_seconds"] = 120000
        saved = d.save_profile(self.db, changed)
        self.db.close()
        self.db = d.connect(self.path)
        self.assertEqual(d.get_profile(self.db), saved)
        self.assertEqual(self.db.execute("SELECT count(*) FROM profile_versions").fetchone()[0], 2)
        self.assertEqual(d.get_profile(self.db)["trial"]["started_on"], self.profile["trial"]["started_on"])

    def test_identical_profile_does_not_add_version(self):
        d.save_profile(self.db, self.profile)
        self.assertEqual(self.db.execute("SELECT count(*) FROM profile_versions").fetchone()[0], 1)

    def test_before_commit_failure_rolls_back_profile_and_version(self):
        changed = copy.deepcopy(self.profile)
        changed["name"] = "不应保存"
        calls = []

        def failing_mirror(profile):
            self.assertTrue(self.db.in_transaction)
            self.assertEqual(profile["name"], "不应保存")
            self.assertGreater(profile["revision"], self.profile["revision"])
            calls.append(profile["revision"])
            raise OSError("catalog mirror cannot be written")

        with self.assertRaisesRegex(OSError, "catalog mirror"):
            d.save_profile(self.db, changed, before_commit=failing_mirror)
        self.assertEqual(len(calls), 1)
        self.assertEqual(d.get_profile(self.db), self.profile)
        self.assertEqual(self.db.execute("SELECT count(*) FROM profile_versions").fetchone()[0], 1)
        self.assertFalse(self.db.in_transaction)

    def test_before_commit_runs_on_identical_save_without_duplicate_version(self):
        calls = []

        def mirror(profile):
            self.assertTrue(self.db.in_transaction)
            calls.append(copy.deepcopy(profile))

        result = d.save_profile(self.db, self.profile, before_commit=mirror)
        self.assertEqual(calls, [self.profile])
        self.assertEqual(result, self.profile)
        self.assertEqual(self.db.execute("SELECT count(*) FROM profile_versions").fetchone()[0], 1)

    def test_stale_profile_cannot_overwrite_newer_changes(self):
        changed = copy.deepcopy(self.profile)
        changed["name"] = "更新"
        d.save_profile(self.db, changed)
        with self.assertRaisesRegex(ValueError, "其他窗口"):
            d.save_profile(self.db, self.profile)

    def test_stable_category_ids_can_be_archived_but_not_removed(self):
        changed = copy.deepcopy(self.profile)
        changed["categories"][0]["archived"] = True
        changed = d.save_profile(self.db, changed)
        self.assertTrue(changed["categories"][0]["archived"])
        changed["categories"] = [c for c in changed["categories"] if c["id"] != "uncategorized"]
        with self.assertRaisesRegex(ValueError, "归档"):
            d.save_profile(self.db, changed)

    def test_invalid_profile_does_not_change_saved_version(self):
        for field, value in [("minimum_daily_seconds", 0), ("minimum_daily_seconds", 1800.5),
                             ("minimum_distinct_days", 8), ("minimum_distinct_days", True)]:
            profile = copy.deepcopy(self.profile)
            next(g for g in profile["goals"] if g["kind"] == "frequency")[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                d.save_profile(self.db, profile)
        self.assertEqual(d.get_profile(self.db), self.profile)

    def test_shell_safe_category_ids_and_names(self):
        for identity, name in [("bad.id", "类别"), ("Upper", "类别"), ("valid", "错误\n类别")]:
            profile = copy.deepcopy(self.profile)
            profile["categories"].append({"id": identity, "name": name, "counts_as_work": False})
            with self.subTest(identity=identity, name=name), self.assertRaises(ValueError):
                d.save_profile(self.db, profile)

    def test_goal_must_reference_existing_category(self):
        profile = copy.deepcopy(self.profile)
        profile["goals"][0]["filter"] = {"category_ids": ["missing"]}
        with self.assertRaisesRegex(ValueError, "不存在"):
            d.save_profile(self.db, profile)

    def test_manual_activity_persists_and_only_manual_can_be_deleted(self):
        record = d.add_manual_activity(self.db, dict(day=FIRST, category="reading", seconds=1800,
                                                   goal_ids=["reading-weekly-frequency"]))
        self.db.close()
        self.db = d.connect(self.path)
        self.assertEqual(d.list_manual_activities(self.db), [record])
        with self.assertRaisesRegex(ValueError, "只能删除"):
            d.delete_manual_activity(self.db, "legacy-1")
        d.delete_manual_activity(self.db, record["id"])
        self.assertEqual(d.list_manual_activities(self.db), [])

    def test_invalid_manual_activity_never_inserted(self):
        for record in [dict(day="not-a-date", category="reading", seconds=10),
                       dict(day=FIRST, category="reading", seconds=-10),
                       dict(day=FIRST, category="missing", seconds=10),
                       dict(day=FIRST, category="reading", seconds=10, goal_ids=["missing"])]:
            with self.subTest(record=record), self.assertRaises(ValueError):
                d.add_manual_activity(self.db, record)
        self.assertEqual(d.list_manual_activities(self.db), [])

    def test_future_schema_is_not_downgraded_or_written(self):
        self.db.execute("PRAGMA user_version=99")
        self.db.commit()
        self.db.close()
        with self.assertRaisesRegex(ValueError, "较新版本"):
            d.connect(self.path)
        self.db = sqlite3.connect(self.path)
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_legacy_database_is_not_migrated_as_application_database(self):
        path = Path(self.temp.name) / "legacy.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE sessions(id INTEGER PRIMARY KEY, day TEXT, category TEXT, seconds INTEGER)")
        with self.assertRaisesRegex(ValueError, "原计时数据库"):
            d.connect(path)
        with sqlite3.connect(path) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertEqual(tables, ["sessions"])


if __name__ == "__main__":
    unittest.main()

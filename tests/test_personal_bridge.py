"""Compatibility tests operate exclusively on temporary source ledgers."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from personal_os import backup, domain, legacy, reviews, timer_bridge as bridge


def stamp(value):
    return int(dt.datetime.fromisoformat(value).timestamp())


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "source" / "data"
        self.data.mkdir(parents=True)
        self.now = stamp("2026-11-05T10:00:00")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, action, offset=0, category=None, boot_time=1):
        return bridge.command(self.data, action, category=category, now=self.now + offset,
                              boot_time=boot_time, refresh=False)

    def state_and_rows(self):
        with closing(sqlite3.connect(self.data / "focus.sqlite3")) as db, db:
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            rows = db.execute("SELECT day,category,seconds FROM sessions ORDER BY id").fetchall()
        return state, rows

    def seed_unknown_table(self):
        t = bridge.engine(self.data)
        with closing(t.connect(self.data)) as db, db:
            db.execute("CREATE TABLE recovery_events (evidence_key TEXT PRIMARY KEY, details TEXT)")
            db.execute("INSERT INTO recovery_events VALUES('recovery-proof','preserve me')")

    def test_read_only_history_preserves_database_logs_and_unknown_tables(self):
        self.seed_unknown_table()
        t = bridge.engine(self.data)
        state = t.fresh("reading")
        state.update(mode="up", elapsed=60, pending=[["2026-11-04", "research", 60]],
                     anchor=self.now - 30, last_tick=self.now - 5)
        with closing(sqlite3.connect(self.data / "focus.sqlite3")) as db, db:
            db.execute("INSERT INTO sessions(day,category,seconds) VALUES('2026-11-05','legacy_custom',120)")
            db.execute("INSERT INTO state VALUES(1,?)", (json.dumps(state),))
        log = self.data / "focus_2026-11-05.log"
        log.write_text("08:00:00 60\n09:00:00 forgotten_category 90\nnot a valid row\n", encoding="utf-8")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.data.iterdir()}
        records, timer, source = legacy.read_activities(self.data, "2026-11-03", "2026-11-05", self.now)
        again = legacy.read_activities(self.data, "2026-11-03", "2026-11-05", self.now)[0]
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.data.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(records, again)
        self.assertTrue(source["read_only"])
        self.assertEqual(len(source["warnings"]), 1)
        self.assertEqual(timer["elapsed_seconds"], 90)
        self.assertEqual(timer["category"], "reading")
        saved = [r for r in records if r["saved"]]
        previews = [r for r in records if not r["saved"]]
        self.assertEqual(sum(r["seconds"] for r in saved), 270)
        self.assertEqual({r["category"] for r in saved},
                         {"legacy_custom", "uncategorized", "forgotten_category"})
        self.assertEqual([(r["day"], r["category"], r["seconds"]) for r in previews],
                         [("2026-11-04", "reading", 60), ("2026-11-05", "reading", 30)])
        self.assertTrue(all(r["precision"] == "day" for r in records))
        with closing(sqlite3.connect(self.data / "focus.sqlite3")) as db, db:
            self.assertEqual(db.execute("SELECT * FROM recovery_events").fetchall(),
                             [("recovery-proof", "preserve me")])
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_empty_source_read_does_not_create_a_database(self):
        missing = self.root / "not-created"
        activities, timer, source = legacy.read_activities(missing, "2026-11-01", "2026-11-07", self.now)
        self.assertEqual(activities, [])
        self.assertEqual(timer["mode"], "idle")
        self.assertFalse(missing.exists())
        self.assertTrue(source["read_only"])

    def test_preview_split_at_midnight_and_excluded_from_saved_goal_statistics(self):
        self.now = stamp("2026-11-08T23:45:00")
        self.command("start", category="reading")
        records, _, _ = legacy.read_activities(self.data, "2026-11-08", "2026-11-09", self.now + 1800)
        self.assertEqual([(r["day"], r["seconds"]) for r in records],
                         [("2026-11-08", 900), ("2026-11-09", 900)])
        db = domain.connect(self.root / "personal.sqlite3")
        try:
            profile = domain.get_profile(db)
            result = domain.build_statistics(profile, records, "2026-11-08", "2026-11-09", "2026-11-09")
            self.assertEqual(result["total_seconds"], 0)
            self.assertEqual(result["preview_seconds"], 1800)
            self.assertEqual(result["reading_days"], 0)
        finally:
            db.close()

    def test_native_pause_resume_switch_and_stop_share_original_ledger(self):
        self.seed_unknown_table()
        self.command("start", category="research")
        self.command("tick", 10)
        self.command("pause", 60)
        self.command("resume", 3600)
        self.command("switch", 3660, category="reading")
        self.command("tick", 3670)
        self.command("stop", 3720)
        self.command("stop", 3730)
        state, rows = self.state_and_rows()
        self.assertEqual(rows, [("2026-11-05", "research", 120), ("2026-11-05", "reading", 60)])
        self.assertEqual(state["mode"], "idle")
        self.assertEqual(state["category"], "reading")
        self.assertEqual(list(self.data.glob("*.sqlite3")), [self.data / "focus.sqlite3"])
        with closing(sqlite3.connect(self.data / "focus.sqlite3")) as db, db:
            self.assertEqual(db.execute("SELECT details FROM recovery_events").fetchone()[0], "preserve me")

    def test_native_switch_splits_saved_activity_at_monday_boundary(self):
        self.now = stamp("2026-11-08T23:59:00")
        self.command("start", category="research")
        self.command("switch", 120, category="reading")
        self.command("stop", 180)
        _, rows = self.state_and_rows()
        self.assertEqual(rows, [("2026-11-08", "research", 60), ("2026-11-09", "research", 60),
                                ("2026-11-09", "reading", 60)])

    def test_discard_restore_is_persistent_and_does_not_replace_active_activity(self):
        self.command("start", category="research")
        self.command("discard", 120)
        self.assertEqual(self.state_and_rows()[1], [])
        self.command("start", 130, category="reading")
        self.command("restore", 140)
        state, rows = self.state_and_rows()
        self.assertEqual(rows, [("2026-11-05", "research", 120)])
        self.assertEqual(state["mode"], "up")
        self.assertEqual(state["category"], "reading")
        self.command("restore", 150)
        self.assertEqual(self.state_and_rows()[1], rows)
        self.command("stop", 160)
        self.assertEqual(self.state_and_rows()[1][-1], ("2026-11-05", "reading", 30))

    def test_fast_reboot_before_sixty_seconds_excludes_powered_off_gap(self):
        self.command("start", category="research")
        self.command("tick", 10)
        self.command("tick", 30, boot_time=self.now + 20)
        state, _ = self.state_and_rows()
        self.assertEqual(state["mode"], "up_paused")
        self.assertEqual(state["elapsed"], 10)
        self.command("stop", 40, boot_time=self.now + 20)
        self.assertEqual(self.state_and_rows()[1], [("2026-11-05", "research", 10)])

    def test_same_boot_missing_heartbeat_pauses_at_last_trusted_tick(self):
        self.command("start", category="research")
        self.command("tick", 10)
        # Simulate quitting/relaunching a standalone app on the same OS boot.
        self.command("tick", 610)
        state, _ = self.state_and_rows()
        self.assertEqual(state["mode"], "up_paused")
        self.assertEqual(state["elapsed"], 10)
        self.command("stop", 611)
        self.assertEqual(self.state_and_rows()[1], [("2026-11-05", "research", 10)])

    def test_sketchybar_event_path_checks_fast_reboot_too(self):
        self.command("start", category="research")
        self.command("tick", 10)
        t = bridge.engine(self.data)
        connect = t.connect
        with patch.object(t, "connect", side_effect=lambda: connect(self.data)), \
                patch.object(t.sys, "argv", ["timer.py", "event"]), \
                patch.dict(t.os.environ, {"NAME": "timer", "SENDER": "routine"}), \
                patch.object(t.time, "time", return_value=self.now + 30), \
                patch.object(t.subprocess, "check_output", return_value=f"{{ sec = {self.now + 20}, usec = 0 }}") as boot, \
                patch.object(t, "render_timer"):
            t.main()
        boot.assert_called_once_with(["sysctl", "-n", "kern.boottime"], text=True)
        state, _ = self.state_and_rows()
        self.assertEqual(state["mode"], "up_paused")
        self.assertEqual(state["elapsed"], 10)

    def test_sleep_wake_fallback_freezes_at_last_trusted_tick(self):
        self.command("start", category="research")
        self.command("tick", 20)
        self.command("wake", 3600)
        self.assertEqual(self.state_and_rows()[0]["elapsed"], 20)
        self.command("resume", 3601)
        self.command("sleep", 3611)
        self.command("wake", 7000)
        self.command("stop", 7001)
        self.assertEqual(self.state_and_rows()[1], [("2026-11-05", "research", 30)])

    def test_start_while_active_and_unknown_category_do_not_lose_existing_state(self):
        self.command("start", category="research")
        original, _ = self.state_and_rows()
        with self.assertRaises(ValueError):
            self.command("start", 30, category="reading")
        with self.assertRaises(ValueError):
            self.command("switch", 40, category="missing")
        self.assertEqual(self.state_and_rows()[0], original)

    def test_concurrent_stop_saves_once(self):
        self.command("start", category="research")
        barrier = threading.Barrier(2)

        def stop():
            barrier.wait(timeout=5)
            return self.command("stop", 60)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: stop(), range(2)))
        self.assertTrue(all(result["ok"] for result in results))
        self.assertEqual(self.state_and_rows()[1], [("2026-11-05", "research", 60)])

    def test_custom_category_configuration_preserves_original_defaults(self):
        categories = [{"id": "biology", "name": "生物学基础"}]
        self.assertTrue(bridge.sync_categories(self.data, categories, refresh=False))
        self.assertFalse(bridge.sync_categories(self.data, categories, refresh=False))
        self.command("start", category="biology")
        self.command("stop", 60)
        self.assertEqual(self.state_and_rows()[1], [("2026-11-05", "biology", 60)])
        self.assertIn("research", bridge.engine(self.data).CATEGORIES)

    def test_backup_is_consistent_with_live_wal_and_preserves_unknown_tables(self):
        self.seed_unknown_table()
        log = self.data / "focus_2026-11-05.log"
        log.write_text("10:00:00 90\n", encoding="utf-8")
        db = sqlite3.connect(self.data / "focus.sqlite3")
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("INSERT INTO sessions(day,category,seconds) VALUES('2026-11-05','research',123)")
            db.commit()
            db.execute("INSERT INTO sessions(day,category,seconds) VALUES('2026-11-05','reading',999)")
            destination = self.root / "backup"
            backup.backup_directory(self.data, destination)
            with closing(sqlite3.connect(destination / "focus.sqlite3")) as saved, saved:
                self.assertEqual(saved.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(saved.execute("SELECT category,seconds FROM sessions").fetchall(), [("research", 123)])
                self.assertEqual(saved.execute("SELECT details FROM recovery_events").fetchone()[0], "preserve me")
            manifest = json.loads((destination / "backup-manifest.json").read_text())
            for name, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), digest)
            self.assertEqual((destination / log.name).read_bytes(), log.read_bytes())
            self.assertFalse((destination / "focus.sqlite3-wal").exists())
        finally:
            db.rollback()
            db.close()

    def test_backup_rejects_missing_source_and_nested_or_existing_destination(self):
        with self.assertRaises(ValueError):
            backup.backup_directory(self.root / "missing", self.root / "unexpected-empty-backup")
        self.assertFalse((self.root / "unexpected-empty-backup").exists())
        with self.assertRaises(ValueError):
            backup.backup_directory(self.data, self.data / "nested")
        destination = self.root / "existing"
        destination.mkdir()
        with self.assertRaises(ValueError):
            backup.backup_directory(self.data, destination)

    def test_export_retains_full_databases_and_refuses_overwrite(self):
        self.seed_unknown_table()
        self.command("start", category="research")
        self.command("stop", 60)
        (self.data / "focus_2026-10-01.log").write_text("10:00:00 300\n", encoding="utf-8")
        app_path = self.root / "app.sqlite3"
        app = domain.connect(app_path)
        try:
            profile = domain.get_profile(app)
            domain.add_manual_activity(app, {"day": "2026-09-01", "category": "reading", "seconds": 1800})
            destination = self.root / "export.json"
            result = backup.export_bundle(app_path, self.data, profile, [], [], [], destination)
            self.assertEqual(result, str(destination))
            payload = json.loads(destination.read_text())
            self.assertEqual(payload["format"], "personal-os-backup")
            restored = self.root / "decoded-app.sqlite3"
            restored.write_bytes(base64.b64decode(payload["app_database_base64"]))
            with closing(sqlite3.connect(restored)) as db, db:
                self.assertEqual(db.execute("SELECT day,seconds FROM manual_activities").fetchall(), [("2026-09-01", 1800)])
            old = self.root / "decoded-legacy.sqlite3"
            old.write_bytes(base64.b64decode(payload["legacy_files"]["focus.sqlite3"]))
            with closing(sqlite3.connect(old)) as db, db:
                self.assertEqual(db.execute("SELECT details FROM recovery_events").fetchone()[0], "preserve me")
                self.assertEqual(db.execute("SELECT category,seconds FROM sessions").fetchall(), [("research", 60)])
            self.assertIn("focus_2026-10-01.log", payload["legacy_files"])
            before = destination.read_bytes()
            with self.assertRaises(ValueError):
                backup.export_bundle(app_path, self.data, profile, [], [], [], destination)
            self.assertEqual(destination.read_bytes(), before)
            with self.assertRaises(ValueError):
                backup.export_bundle(app_path, self.data, profile, [], [], [], self.data / "nested.json")
            self.assertFalse((self.data / "nested.json").exists())
            # A replacement confirmed in the save dialog swaps in a complete new file.
            backup.export_bundle(app_path, self.data, profile, [{"marker": 1}], [], [], destination, overwrite=True)
            self.assertEqual(json.loads(destination.read_text())["activities"], [{"marker": 1}])
            self.assertEqual(sorted(p.name for p in self.root.glob(".personal-os-export-*")), [])
        finally:
            app.close()

    def test_restore_fresh_workspace_preserves_history_reviews_and_freezes_live_timer(self):
        self.seed_unknown_table()
        self.command("start", category="research")
        self.command("tick", 30)
        app_path = self.root / "app.sqlite3"
        app = domain.connect(app_path)
        try:
            profile = domain.get_profile(app)
            manual = domain.add_manual_activity(app, {"day": "2026-11-02", "category": "reading", "seconds": 1800})
            reviews.initialize(app)
            stats = domain.build_statistics(profile, [manual], "2026-11-02", "2026-11-08", "2026-11-08")
            saved_review = reviews.save_weekly_review(app, "2026-11-02", "2026-11-08", "已完成的复盘", True, stats, profile)
            exported = self.root / "export.json"
            backup.export_bundle(app_path, self.data, profile, [manual], [], [saved_review], exported)
        finally:
            app.close()
        restored = backup.restore_bundle(exported, self.root / "restored")
        reopened = domain.connect(restored / "personal_os.sqlite3")
        try:
            self.assertEqual(domain.list_manual_activities(reopened), [manual])
            history = reviews.list_weekly_reviews(reopened)
            self.assertEqual(history, [saved_review])
        finally:
            reopened.close()
        with closing(sqlite3.connect(restored / "legacy/focus.sqlite3")) as db:
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            self.assertEqual(state["mode"], "up_paused")
            self.assertEqual(state["elapsed"], 30)
            self.assertEqual(db.execute("SELECT details FROM recovery_events").fetchone()[0], "preserve me")
        self.assertEqual(self.state_and_rows()[0]["mode"], "up")
        with self.assertRaises(ValueError):
            backup.restore_bundle(exported, restored)

    def test_restore_rejects_traversal_corrupt_db_and_unknown_format_without_partial_workspace(self):
        app_path = self.root / "app.sqlite3"
        app = domain.connect(app_path)
        try:
            profile = domain.get_profile(app)
            original = self.root / "original.json"
            backup.export_bundle(app_path, self.data, profile, [], [], [], original)
        finally:
            app.close()
        payload = json.loads(original.read_text())
        variants = [dict(payload, legacy_files={"../escaped.log": base64.b64encode(b"no").decode()}),
                    dict(payload, app_database_base64=base64.b64encode(b"not SQLite").decode()),
                    dict(payload, legacy_files={"extra.sqlite": base64.b64encode(b"not SQLite").decode()}),
                    dict(payload, version=99)]
        for index, value in enumerate(variants):
            source = self.root / f"bad-{index}.json"
            source.write_text(json.dumps(value))
            target = self.root / f"bad-restore-{index}"
            with self.subTest(index=index), self.assertRaises((ValueError, sqlite3.DatabaseError)):
                backup.restore_bundle(source, target)
            self.assertFalse(target.exists())
        self.assertFalse((self.root / "escaped.log").exists())


if __name__ == "__main__":
    unittest.main()

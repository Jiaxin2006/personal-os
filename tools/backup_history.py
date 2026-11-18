#!/usr/bin/env python3
"""Back up the full SketchyBar configuration with SQLite's Backup API.

Without a destination the backup goes to "Timer Backups" in the app's data
folder (~/Library/Application Support/Personal OS), named by date and time, so
nothing lands on the Desktop. The path is printed for the installer's --backup.
"""
import argparse
import datetime as dt
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_os.backup import backup_directory


def default_destination(now=None):
    root = Path(os.environ.get('PERSONAL_OS_DATA_DIR', Path.home() / 'Library/Application Support/Personal OS')).expanduser()
    return root / 'Timer Backups' / (now or dt.datetime.now()).strftime('before-update-%Y%m%d-%H%M%S')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path, nargs='?')
    parser.add_argument('--source', type=Path, default=Path.home() / '.config/sketchybar')
    args = parser.parse_args()
    print(backup_directory(args.source, args.destination or default_destination()))

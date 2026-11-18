#!/usr/bin/env python3
"""Fetch curated release images or add CC0 paintings to the local gallery."""
import argparse
import fcntl
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'assets/paintings.json'
OUTPUT = ROOT / 'assets/paintings'
LOCAL_GALLERY = Path.home() / 'Library/Application Support/Personal OS/Local Paintings'
API = 'https://collectionapi.metmuseum.org/public/collection/v1/objects/%d'
SEARCH = ('https://collectionapi.metmuseum.org/public/collection/v1.1/search'
          '?hasImages=true&departmentId=11&q=landscape&limit=100&offset=%d')
CREDIT = 'The Metropolitan Museum of Art · CC0'
LONG_SIDE = 2400
QUALITY = 75
TOP_UP_COUNT = 8
MAX_CANDIDATES = 24


def fetch(url, destination=None):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                if destination is None:
                    return response.read()
                with destination.open('wb') as file:
                    shutil.copyfileobj(response, file)
                return
        except OSError as error:
            permanent = isinstance(error, HTTPError) and 400 <= error.code < 500 and error.code != 429
            if permanent or attempt == 3:
                raise
            time.sleep(2)


def object_metadata(met_id):
    meta = json.loads(fetch(API % met_id))
    if meta.get('isPublicDomain') is not True or not meta.get('primaryImage'):
        raise ValueError(f'{met_id} has no public-domain image available through The Met API')
    return meta


def download_image(meta, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    # Construct the JPEG beside the destination so publishing it is atomic.
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        original = Path(temporary) / 'original.jpg'
        resized = Path(temporary) / target.name
        fetch(meta['primaryImage'], original)
        subprocess.run(['sips', '-Z', str(LONG_SIDE), '-s', 'format', 'jpeg',
                        '-s', 'formatOptions', str(QUALITY), str(original), '--out', str(resized)],
                       check=True, stdout=subprocess.DEVNULL)
        if not resized.is_file() or not resized.stat().st_size:
            raise ValueError(f'Unable to resize image for {target.name}')
        resized.replace(target)


def curated_entries(manifest=MANIFEST):
    return json.loads(manifest.read_text(encoding='utf-8'))


def fetch_curated(entries, refresh=False):
    for entry in entries:
        met_id = entry['met_id']
        file = f'{met_id}.jpg'
        if entry['file'] != file:
            raise ValueError(f'Expected {file} in the curated manifest')
        target = OUTPUT / file
        if target.is_file() and target.stat().st_size and not refresh:
            continue
        download_image(object_metadata(met_id), target)
        print(f'Downloaded {met_id} · {entry["title"]}', flush=True)


def write_gallery(manifest, entries):
    with tempfile.TemporaryDirectory(dir=manifest.parent) as temporary:
        pending = Path(temporary) / manifest.name
        pending.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        pending.replace(manifest)


def discover_paintings():
    first = json.loads(fetch(SEARCH % 0))
    offset = random.randrange(max(1, (first['total'] + 99) // 100)) * 100
    page = json.loads(fetch(SEARCH % offset)) if offset else first
    ids = list(dict.fromkeys((page.get('objectIDs') or []) + (first.get('objectIDs') or [])))
    random.shuffle(ids)
    return ids


def add_local_paintings(ids, refresh=False, *, bundled_manifest=MANIFEST):
    bundled = {entry['met_id'] for entry in curated_entries(bundled_manifest)}
    automatic = ids is None
    LOCAL_GALLERY.mkdir(parents=True, exist_ok=True)
    manifest = LOCAL_GALLERY / 'paintings.json'
    failed = False
    with (LOCAL_GALLERY / '.download.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
        local = {entry['met_id']: entry for entry in entries}
        images = LOCAL_GALLERY / 'paintings'
        pending = []
        for met_id in dict.fromkeys(discover_paintings() if automatic else ids):
            target = images / f'{met_id}.jpg'
            if met_id in bundled or (met_id in local and target.is_file() and target.stat().st_size and not refresh):
                if not automatic:
                    print(f'Already available: {met_id}', flush=True)
            else:
                pending.append(met_id)
        added = 0
        for met_id in pending[:MAX_CANDIDATES] if automatic else pending:
            target = images / f'{met_id}.jpg'
            try:
                meta = object_metadata(met_id)
                title = meta['title']
                artist = meta.get('artistDisplayName') or 'Unknown artist'
                entry = dict(met_id=met_id, title=title, artist=artist,
                             date=meta.get('objectDate'), source_url=meta.get('objectURL'),
                             credit=CREDIT, file=target.name)
                download_image(meta, target)
                updated = local | {met_id: entry}
                write_gallery(manifest, list(updated.values()))
                local = updated
                added += 1
                print(f'Downloaded {met_id} · {title}', flush=True)
                if automatic and added >= TOP_UP_COUNT:
                    break
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                print(f'Could not add {met_id}: {error}', flush=True)
                failed = True
    print(f'Local gallery: {len(local)} paintings · {LOCAL_GALLERY}')
    return added > 0 if automatic else not failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='download existing images again')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--local', metavar='MET_ID', type=int, nargs='+',
                      help='download these Met object IDs to the local gallery')
    mode.add_argument('--top-up', metavar='CURATED_MANIFEST', type=Path, help='find and download a new batch')
    args = parser.parse_args()
    try:
        if args.top_up is not None:
            return 0 if add_local_paintings(None, bundled_manifest=args.top_up) else 1
        if args.local is not None:
            if any(met_id <= 0 for met_id in args.local):
                parser.error('Met object IDs must be positive integers')
            return 0 if add_local_paintings(args.local, args.refresh) else 1
        entries = curated_entries()
        fetch_curated(entries, args.refresh)
        print(f'Curated collection: {len(entries)} paintings · {OUTPUT}')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Unable to prepare paintings: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())

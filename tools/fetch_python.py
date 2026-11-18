#!/usr/bin/env python3
"""Download the standalone Python that the app bundles, into vendor/python.

The build is python-build-standalone (the interpreter uv installs), pinned by
release and SHA-256 so every build ships the same runtime. Its python3 is
statically linked against libpython and needs only system libraries, so the app
runs on Macs without any Python installed. Parts the backend never uses (Tk,
IDLE, pip, headers) are removed. tools/build_macos.py copies the result into the
app; without it the app falls back to a Python installed on the machine.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'vendor/python'
RELEASE = '20261026'
ARCHIVE = 'cpython-3.13.18+20261026-aarch64-apple-darwin-install_only_stripped.tar.gz'
SHA256 = '8392b6ea51d94391befb2c31ebe75463f045d0b69dfcf5e1bb3234e1f5fa3405'
URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s' % (RELEASE, urllib.parse.quote(ARCHIVE))
VERSION = 'python3.13'
UNUSED = ['include', 'share', 'lib/pkgconfig', 'lib/libpython3.13.dylib', 'lib/libtcl9.0.dylib',
          'lib/libtcl9tk9.0.dylib', 'lib/itcl4.3.8', 'lib/tcl9', 'lib/tcl9.0', 'lib/thread3.0.6', 'lib/tk9.0',
          'bin/idle3', 'bin/idle3.13', 'bin/pip', 'bin/pip3', 'bin/pip3.13', 'bin/pydoc3', 'bin/pydoc3.13',
          'bin/python3-config', 'bin/python3.13-config']
UNUSED_STDLIB = ['idlelib', 'tkinter', 'turtledemo', 'turtle.py', 'ensurepip', 'pydoc_data', 'site-packages',
                 'config-3.13-darwin', 'lib-dynload/_tkinter.cpython-313-darwin.so']


def download(destination):
    with urllib.request.urlopen(URL, timeout=120) as response, open(destination, 'wb') as file:
        shutil.copyfileobj(response, file)


def prepare(archive):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256:
        raise SystemExit('校验失败：%s 的 SHA-256 是 %s，应为 %s' % (archive.name, digest, SHA256))
    with tempfile.TemporaryDirectory(prefix='personal-os-python-') as temporary:
        temporary = Path(temporary)
        with tarfile.open(archive) as bundle:
            bundle.extractall(temporary, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
        python = temporary / 'python'
        for relative in UNUSED + ['lib/%s/%s' % (VERSION, name) for name in UNUSED_STDLIB]:
            path = python / relative
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        # The backend needs SQLite and time zones; fail here rather than in the app.
        subprocess.run([str(python / 'bin/python3'), '-I', '-c', 'import json, sqlite3, zoneinfo'], check=True)
        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(python), OUTPUT)
    size = sum(path.stat().st_size for path in OUTPUT.rglob('*') if path.is_file() and not path.is_symlink())
    print('%s (%.1f MB)' % (OUTPUT, size / 1e6))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, help='use an already downloaded %s' % ARCHIVE)
    args = parser.parse_args()
    if args.archive:
        prepare(args.archive.expanduser())
    else:
        with tempfile.TemporaryDirectory(prefix='personal-os-python-download-') as folder:
            archive = Path(folder) / ARCHIVE
            download(archive)
            prepare(archive)

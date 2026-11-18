#!/usr/bin/env python3
"""Build an ad-hoc signed native app using the installed macOS SDK."""
import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tempfile

import check_localization
import fetch_paintings

ROOT = Path(__file__).resolve().parents[1]
MACH_O = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe'}


def is_mach_o(path):
    with open(path, 'rb') as file:
        return file.read(4) in MACH_O


def build_icon(temporary, destination):
    """Use checked-in, prevalidated artwork; icon generation is a separate step."""
    icons = ROOT / 'assets/icons'
    for name in ('AppIcon.icns', 'AppIcon.png'):
        source = icons / name
        if not source.is_file():
            raise ValueError('Missing icon resource; run tools/prepare_app_icon.py: ' + name)
        shutil.copy2(source, destination.parent / name)


def build(output, allow_missing_translations=False, *, local_gallery=False, without_paintings=False):
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    paintings = [] if without_paintings else fetch_paintings.curated_entries()
    try:
        fetch_paintings.fetch_curated(paintings)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Unable to prepare bundled paintings: {error}') from error
    with tempfile.TemporaryDirectory(prefix='.personal-os-build-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        app = temporary / 'Personal OS.app'
        contents = app / 'Contents'
        executable = contents / 'MacOS/PersonalOS'
        executable.parent.mkdir(parents=True)
        sources = sorted((ROOT / 'macos/PersonalOS').glob('*.swift'))
        if not sources:
            raise RuntimeError('缺少 SwiftUI 源文件')
        strings = temporary / 'localized-strings'
        strings.mkdir()
        flags = ['-D', 'LOCAL_PAINTINGS'] if local_gallery else []
        subprocess.run(['swiftc', '-swift-version', '5', '-parse-as-library', '-O',
                        '-emit-localized-strings', '-emit-localized-strings-path', str(strings),
                        '-target', platform.machine() + '-apple-macos13.0',
                        '-module-cache-path', str(temporary / 'module-cache'),
                        *flags, *map(str, sources), '-framework', 'SwiftUI', '-framework', 'AppKit', '-framework', 'Charts',
                        '-o', str(executable)], check=True)
        # Every Chinese string needs an English entry in macos/PersonalOS/Localization/en.lproj.
        problems = check_localization.check(strings)
        if os.environ.get('PERSONAL_OS_KEEP_STRINGS'):
            shutil.copytree(strings, os.environ['PERSONAL_OS_KEEP_STRINGS'], dirs_exist_ok=True)
        if problems:
            print('\n'.join(problems))
            if not allow_missing_translations:
                raise SystemExit('有 %d 处中文缺少英文翻译（见上）；补上翻译，或加 --allow-missing-translations' % len(problems))
        for language in sorted((ROOT / 'macos/PersonalOS/Localization').glob('*.lproj')):
            shutil.copytree(language, contents / 'Resources' / language.name)
        backend = contents / 'Resources/backend'
        (backend / 'personal_os').mkdir(parents=True)
        (backend / 'plugins').mkdir()
        for source in (ROOT / 'personal_os').glob('*'):
            if source.is_file() and source.suffix in ('.py', '.json'):
                shutil.copy2(source, backend / 'personal_os' / source.name)
        shutil.copy2(ROOT / 'plugins/timer.py', backend / 'plugins/timer.py')
        # Bundled interpreter (tools/fetch_python.py); without it the app uses a Python on the machine.
        python = ROOT / 'vendor/python'
        if (python / 'bin/python3').is_file():
            shutil.copytree(python, contents / 'Resources/python', symlinks=True)
        else:
            print('未找到 vendor/python，应用将使用本机 Python；发布前运行 tools/fetch_python.py')
        # Copy only the curated files, even if the cache has other images.
        daily = contents / 'Resources/Daily'
        daily.mkdir()
        for name in ('poems.json', 'paintings.json'):
            shutil.copy2(ROOT / 'assets' / name, daily / name)
        if local_gallery:
            shutil.copy2(ROOT / 'tools/fetch_paintings.py', daily / 'fetch_paintings.py')
        if paintings:
            (daily / 'paintings').mkdir()
            for entry in paintings:
                name = entry['file']
                shutil.copy2(fetch_paintings.OUTPUT / name, daily / 'paintings' / name)
        build_icon(temporary, contents / 'Resources/AppIcon.icns')
        info = {
            'CFBundleDevelopmentRegion': 'en', 'CFBundleLocalizations': ['en', 'zh-Hans'],
            'CFBundleExecutable': 'PersonalOS', 'CFBundleIdentifier': 'local.personalos.desktop',
            'CFBundleName': 'Personal OS', 'CFBundleDisplayName': 'Personal OS', 'CFBundleIconFile': 'AppIcon.icns',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.1.3',
            'CFBundleVersion': '4', 'LSMinimumSystemVersion': '13.0',
            'LSUIElement': False,
            'NSHighResolutionCapable': True, 'LSApplicationCategoryType': 'public.app-category.productivity',
        }
        (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
        # Code under Resources is not reached by --deep, so sign each Mach-O file first.
        for path in sorted((contents / 'Resources').rglob('*')):
            if path.is_file() and not path.is_symlink() and is_mach_o(path):
                subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        previous = temporary / 'previous.app'
        if output.exists():
            existing_info = output / 'Contents/Info.plist'
            if not existing_info.exists() or plistlib.loads(existing_info.read_bytes()).get('CFBundleIdentifier') != info['CFBundleIdentifier']:
                raise ValueError('输出位置已存在其他内容，未覆盖')
            output.rename(previous)
        try:
            app.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/Personal OS.app')
    parser.add_argument('--allow-missing-translations', action='store_true')
    parser.add_argument('--local-gallery', action='store_true',
                        help='include support for the local gallery downloaded by fetch_paintings.py --local')
    parser.add_argument('--without-paintings', action='store_true',
                        help='skip bundled images for an offline development or CI build')
    args = parser.parse_args()
    print(build(args.output, args.allow_missing_translations,
                local_gallery=args.local_gallery, without_paintings=args.without_paintings))

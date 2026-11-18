#!/usr/bin/env python3
"""Check that every Chinese string in the SwiftUI sources has an English translation.

swiftc -emit-localized-strings lists each string the app will look up (the key
and where the literal starts). A Chinese literal that is not in that list is
shown as written, so English users would see Chinese; mark it with
String(localized:) or pass it straight to a SwiftUI view. A line ending in
`// l10n: keep` is Chinese on purpose (for example lunar month names).
"""
import json
from pathlib import Path
import plistlib
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'macos/PersonalOS'
ENGLISH = SOURCES / 'Localization/en.lproj'
CJK = re.compile(r'[㐀-鿿　-〿＀-￯]')
STRINGS_ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)";\s*$')


def literals(text):
    """Yield (line, column, body) for each string literal outside comments.

    Lines and columns are 1-based and columns count UTF-8 bytes, as swiftc reports them.
    """
    i, line, column, depth = 0, 1, 1, []

    def advance(count=1):
        nonlocal i, line, column
        for _ in range(count):
            if text[i] == '\n':
                line, column = line + 1, 1
            else:
                column += len(text[i].encode('utf-8'))
            i += 1

    def read_string():
        # The opening quote is at text[i]; returns the literal body with interpolations kept.
        start = (line, column)
        advance()
        body = []
        while i < len(text) and text[i] != '"':
            if text.startswith('\\(', i):
                body.append('\\(')
                advance(2)
                parens = 1
                while i < len(text) and parens:
                    if text[i] == '"':
                        yield from read_string()
                        body.append('""')
                        continue
                    parens += {'(': 1, ')': -1}.get(text[i], 0)
                    body.append(text[i])
                    advance()
            elif text[i] == '\\':
                body.append(text[i:i + 2])
                advance(2)
            else:
                body.append(text[i])
                advance()
        advance()
        yield start + (''.join(body),)

    while i < len(text):
        if text.startswith('//', i):
            while i < len(text) and text[i] != '\n':
                advance()
        elif text.startswith('/*', i):
            while i < len(text) and not text.startswith('*/', i):
                advance()
            advance(2)
        elif text[i] == '"':
            yield from read_string()
        else:
            advance()


def translations():
    keys = set()
    strings = ENGLISH / 'Localizable.strings'
    if strings.exists():
        for raw in strings.read_text(encoding='utf-8').splitlines():
            match = STRINGS_ENTRY.match(raw.strip())
            if match:
                keys.add(re.sub(r'\\(.)', lambda m: '\n' if m.group(1) == 'n' else m.group(1), match.group(1)))
    plurals = ENGLISH / 'Localizable.stringsdict'
    if plurals.exists():
        keys.update(plistlib.loads(plurals.read_bytes()))
    return keys


def check(stringsdata_dir):
    """Return a list of problems (empty when every Chinese string is translated)."""
    extracted, located = set(), set()
    for path in Path(stringsdata_dir).glob('*.stringsdata'):
        data = json.loads(path.read_text(encoding='utf-8'))
        for entry in data.get('tables', {}).get('Localizable', []):
            extracted.add(entry['key'])
            location = entry.get('location', {})
            located.add((Path(data['source']).name, location.get('startingLine'), location.get('startingColumn')))
    problems = []
    known = translations()
    for key in sorted(extracted):
        if CJK.search(key) and key not in known:
            problems.append('缺少英文翻译："%s"' % key)
    for source in sorted(SOURCES.glob('*.swift')):
        lines = source.read_text(encoding='utf-8').splitlines()
        for line, column, body in literals(source.read_text(encoding='utf-8')):
            if CJK.search(body) and (source.name, line, column) not in located and not lines[line - 1].rstrip().endswith('// l10n: keep'):
                problems.append('%s:%d 未标记翻译："%s"' % (source.name, line, body))
    return problems


if __name__ == '__main__':
    found = check(sys.argv[1])
    print('\n'.join(found) or '所有中文文案都有英文翻译')
    sys.exit(1 if found else 0)

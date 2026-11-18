#!/usr/bin/env python3
"""Convert the approved artwork into macOS resources (build-time only).

Requires Pillow. Runtime/build_macos.py only copy the prepared resources and do
not depend on Pillow, AppKit drawing, or iconutil.
"""
from pathlib import Path
import io
import math
import struct
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / 'assets/icons'
# Apple's macOS icon grid: an 824px tile centred on a 1024px canvas.
CANVAS, TILE = 1024, 824


def tile(source):
    """Mask the full-bleed artwork into the rounded macOS tile.

    macOS does not mask a bundle icon or NSApp.applicationIconImage, so an
    unmasked square shows as a hard-cornered square in the Dock.
    """
    scale = 4
    radius = TILE * scale / 2
    # A superellipse (n=5) approximates Apple's continuous-corner tile.
    points = []
    for step in range(1440):
        angle = 2 * math.pi * step / 1440
        x, y = math.cos(angle), math.sin(angle)
        points.append((radius + radius * math.copysign(abs(x) ** 0.4, x), radius + radius * math.copysign(abs(y) ** 0.4, y)))
    mask = Image.new('L', (TILE * scale, TILE * scale), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    mask = mask.resize((TILE, TILE), Image.Resampling.LANCZOS)
    face = source.resize((TILE, TILE), Image.Resampling.LANCZOS)
    face.putalpha(mask)
    offset = (CANVAS - TILE) // 2
    canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste((0, 0, 0, 64), (offset, offset + 10, offset + TILE, offset + 10 + TILE), mask)
    canvas = canvas.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(face, (offset, offset))
    return canvas


def prepare():
    artwork = ICONS / 'personal-os-icon-v3.png'
    with Image.open(artwork) as source:
        if source.width != source.height:
            raise ValueError('Icon artwork must be square')
        master = tile(source.convert('RGBA'))
        master.save(ICONS / 'AppIcon.png', format='PNG')
        # Pillow's default ICNS writer omits the non-Retina 16px entry.
        # Include every native size as well as the Retina variants explicitly.
        types = {b'icp4': 16, b'icp5': 32, b'icp6': 64, b'ic07': 128,
                 b'ic08': 256, b'ic09': 512, b'ic10': 1024,
                 b'ic11': 32, b'ic12': 64, b'ic13': 256, b'ic14': 512}
        entries = []
        for kind, size in types.items():
            stream = io.BytesIO()
            master.resize((size, size), Image.Resampling.LANCZOS).save(stream, format='PNG')
            payload = stream.getvalue()
            entries.append((kind, struct.pack('>I', 8 + len(payload)), payload))
        toc = b''.join(kind + length for kind, length, payload in entries)
        body = b'TOC ' + struct.pack('>I', 8 + len(toc)) + toc
        body += b''.join(kind + length + payload for kind, length, payload in entries)
        (ICONS / 'AppIcon.icns').write_bytes(b'icns' + struct.pack('>I', 8 + len(body)) + body)
    with Image.open(ICONS / 'AppIcon.icns') as icon:
        sizes = {width * scale for width, height, scale in icon.info['sizes']}
        if not {16, 32, 64, 128, 256, 512, 1024} <= sizes:
            raise ValueError('Icon is missing required sizes')
    print(ICONS / 'AppIcon.icns')


if __name__ == '__main__':
    prepare()

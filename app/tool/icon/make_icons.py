"""Writes the launcher icons and the header logo from bust_cut.png (made by icon_cut.py).

    python icon_cut.py bust_source.jpg bust_cut.png
    python make_icons.py

ic_launcher.png: 48 dp legacy icon, head at 94 %. ic_launcher_foreground.png: 108 dp
adaptive layer, head inside the 72 dp safe zone. Background stays transparent.
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
RES = HERE.parents[1] / 'android' / 'app' / 'src' / 'main' / 'res'
LOGO = HERE.parents[1] / 'assets' / 'branding' / 'logo.png'
CROP = (55, 10, 935, 890)  # square around the head in bust_cut.png
DENSITIES = {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}

head = Image.open(HERE / 'bust_cut.png').convert('RGBA').crop(CROP)


def centred(canvas_px, head_px):
    canvas = Image.new('RGBA', (canvas_px, canvas_px), (0, 0, 0, 0))
    scaled = head.resize((head_px, head_px), Image.LANCZOS)
    offset = (canvas_px - head_px) // 2
    canvas.alpha_composite(scaled, (offset, offset))
    return canvas


for name, scale in DENSITIES.items():
    folder = RES / f'mipmap-{name}'
    centred(round(48 * scale), round(48 * scale * 0.94)).save(folder / 'ic_launcher.png')
    centred(round(108 * scale), round(72 * scale)).save(folder / 'ic_launcher_foreground.png')
centred(128, 124).save(LOGO)
print('icons written')

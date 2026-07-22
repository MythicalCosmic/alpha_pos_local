"""Build the AlphaPOS Windows icon from the project brand mark.

``AlphaPOS-mark.png`` is the transparent, high-resolution source mark.  This
script places it on a restrained porcelain tile and emits both a reusable PNG
and a multi-resolution ICO.  Keeping the composition in code makes every
release reproducible and avoids depending on a stale hand-edited icon.

    python desktop/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw


HERE = Path(__file__).resolve().parent
MARK = HERE / 'AlphaPOS-mark.png'
OUT_PNG = HERE / 'AlphaPOS.png'
OUT_ICO = HERE / 'AlphaPOS.ico'
OUT_UI = HERE / 'ui' / 'AlphaPOS.png'
SIZE = 512


def _rounded_mask(size: int) -> Image.Image:
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (1, 1, size - 2, size - 2),
        radius=max(3, round(size * 0.215)),
        fill=255,
    )
    return mask


def _load_mark() -> Image.Image:
    if not MARK.is_file():
        raise FileNotFoundError(
            f'Missing brand source: {MARK}. Keep AlphaPOS-mark.png beside '
            'make_icon.py.'
        )
    mark = Image.open(MARK).convert('RGBA')
    bbox = mark.getchannel('A').getbbox()
    if not bbox:
        raise ValueError(f'Brand source has no visible pixels: {MARK}')
    return mark.crop(bbox)


def render(size: int = SIZE) -> Image.Image:
    # A subtly warm, high-contrast tile works across Windows light/dark themes
    # without fighting the navy + emerald mark.
    tile = Image.new('RGBA', (size, size), (247, 249, 247, 255))
    tile.putalpha(_rounded_mask(size))

    draw = ImageDraw.Draw(tile)
    inset = max(1, round(size * 0.012))
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=max(3, round(size * 0.205)),
        outline=(211, 221, 219, 210),
        width=max(1, round(size * 0.012)),
    )

    mark = _load_mark()
    max_w = round(size * 0.79)
    max_h = round(size * 0.66)
    scale = min(max_w / mark.width, max_h / mark.height)
    mark = mark.resize(
        (max(1, round(mark.width * scale)), max(1, round(mark.height * scale))),
        Image.Resampling.LANCZOS,
    )
    x = (size - mark.width) // 2
    y = (size - mark.height) // 2
    tile.alpha_composite(mark, (x, y))
    return tile


def main() -> None:
    base = render(SIZE)
    base.save(OUT_PNG, format='PNG', optimize=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT_ICO, format='ICO', sizes=[(n, n) for n in sizes])
    # A compact copy is served by the local control panel.  It deliberately
    # keeps the porcelain tile so the mark stays legible in every UI theme.
    OUT_UI.parent.mkdir(parents=True, exist_ok=True)
    render(128).save(OUT_UI, format='PNG', optimize=True)
    print(f'wrote {OUT_PNG}')
    print(f'wrote {OUT_ICO}')
    print(f'wrote {OUT_UI}')


if __name__ == '__main__':
    main()

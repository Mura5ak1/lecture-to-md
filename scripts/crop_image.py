#!/usr/bin/env python3
"""
Crop a rectangular region (e.g. one figure) out of a page render.

Use this when a figure can't be pulled out with pdfimages: scanned PDFs (the whole page
is one embedded image), vector diagrams, or a photo sitting on a page with text. Keeping
only the figure avoids duplicating text/tables that were already transcribed.

Coordinates are fractions of the image (0-1) so they don't depend on dpi:
    python3 crop_image.py <page.png> <x0> <y0> <x1> <y1> <out.png> [--max-dim 1024] [--pad 0.01]

Example: figure occupying the right half of the top 60% of a page:
    python3 crop_image.py pages/page_002.png 0.5 0.0 1.0 0.6 out/doc__page_002_fig1.png

For a sharper crop of a scan, re-render the page at higher dpi first (render_pdf_pages.py --dpi 200)
or run pdftoppm -r 200 -f N -l N yourself, then crop that image.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("x0", type=float)
    ap.add_argument("y0", type=float)
    ap.add_argument("x1", type=float)
    ap.add_argument("y1", type=float)
    ap.add_argument("output")
    ap.add_argument("--max-dim", type=int, default=1024)
    ap.add_argument("--pad", type=float, default=0.01, help="extra margin as a fraction of the image (default 0.01)")
    a = ap.parse_args()
    if not (0 <= a.x0 < a.x1 <= 1 and 0 <= a.y0 < a.y1 <= 1):
        print("FAIL: need 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1", file=sys.stderr)
        sys.exit(1)
    with Image.open(a.input) as im:
        w, h = im.size
        box = (max(0, int((a.x0 - a.pad) * w)), max(0, int((a.y0 - a.pad) * h)),
               min(w, int((a.x1 + a.pad) * w)), min(h, int((a.y1 + a.pad) * h)))
        crop = im.crop(box)
        scale = min(1.0, a.max_dim / max(crop.size))
        if scale < 1.0:
            crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        crop.save(a.output, optimize=True)
        print(f"cropped {box} of {w}x{h} -> {crop.size[0]}x{crop.size[1]}px -> {a.output} "
              f"({crop.width * crop.height / (w * h):.0%} of the page's pixels)")


if __name__ == "__main__":
    main()

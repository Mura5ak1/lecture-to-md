#!/usr/bin/env python3
"""
Re-render ONE page of a PDF at a chosen resolution (for zooming into small print,
handwriting, or a figure you are about to crop from a scan).

    python3 render_page.py <input.pdf> <page> <dpi> <out.png>

Example: python3 render_page.py scan.pdf 4 300 /tmp/work/page_004_300dpi.png
Combine with crop_image.py to get a sharp crop of a single region.
Only poppler's pdftoppm is needed.
"""
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)
    pdf, page, dpi, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        prefix = Path(t) / "p"
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
                        "-singlefile", pdf, str(prefix)], check=True)
        Path(str(prefix) + ".png").replace(out)
    print(f"page {page} @ {dpi}dpi -> {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Extract everything needed to losslessly transcribe a lecture PDF into markdown:
- a full-page PNG render of every page (ground truth for visual reading)
- a layout-preserved text draft of every page (speeds up transcription of plain prose)
- any embedded raster images per page (candidate figures/photos -- NOT all of these
  end up in the final output; the transcription step decides which ones actually
  need to survive as image files vs. get replaced by a text description)

Relies only on poppler command-line tools (pdftoppm, pdftotext, pdfimages, pdfinfo),
which are commonly preinstalled, instead of python PDF libraries that may not be.

Usage:
    python3 render_pdf_pages.py <input.pdf> <output_dir> [--dpi 110]

Produces:
    <output_dir>/pages/page_NNN.png       full-page renders (110dpi by default)
    <output_dir>/text/page_NNN.txt        layout-preserved text draft
    <output_dir>/images/page_NNN_imgK.png candidate embedded raster images (filtered, page-indexed)
    <output_dir>/manifest.json            index of everything above, per page

Note on --dpi: 110 is the default because it's noticeably cheaper (in vision
tokens) than the old 150dpi default while still being readable for normal
slide text. Bump it up (e.g. --dpi 150) for scans with small footnotes/dense
formulas where 110dpi risks being unreadable.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MIN_IMAGE_DIM = 60  # px; filters out bullet icons / decorative dots from pdfimages
DEFAULT_DPI = 110
SCAN_DPI = 150       # used automatically when the PDF has (almost) no text layer
SCAN_TEXT_CHARS_PER_PAGE = 20


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def get_page_count(pdf_path):
    out = subprocess.run(["pdfinfo", pdf_path], check=True, capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    if not m:
        raise RuntimeError("Could not determine page count from pdfinfo output")
    return int(m.group(1))


def render_pages(pdf_path, pages_dir, total_pages, dpi):
    prefix = str(pages_dir / "page")
    run(["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix])
    # pdftoppm names output page-<N>.png (N padded to fit total_pages digits, no leading zero for single-page docs)
    rendered = {}
    for f in pages_dir.glob("page-*.png"):
        n = int(f.stem.split("-")[-1])
        target = pages_dir / f"page_{n:03d}.png"
        f.rename(target)
        rendered[n] = str(target)
    return rendered


def extract_text(pdf_path, text_dir, total_pages):
    text_files = {}
    for n in range(1, total_pages + 1):
        out_path = text_dir / f"page_{n:03d}.txt"
        run(["pdftotext", "-layout", "-f", str(n), "-l", str(n), pdf_path, str(out_path)])
        text_files[n] = str(out_path)
    return text_files


def image_kinds_by_page(pdf_path, total_pages):
    """Return {page: [type, ...]} in the same order pdfimages writes files.

    pdfimages also emits every image's soft mask (`smask`) as a separate file, which
    doubles the count and shifts numbering (img1, img3, ...). We use `pdfimages -list`
    to tell them apart and drop the masks."""
    kinds = {n: [] for n in range(1, total_pages + 1)}
    try:
        out = subprocess.run(["pdfimages", "-list", pdf_path], check=True, capture_output=True, text=True).stdout
    except Exception:
        return kinds
    for line in out.splitlines()[2:]:
        cols = line.split()
        if len(cols) > 2 and cols[0].isdigit():
            kinds.setdefault(int(cols[0]), []).append(cols[2])
    return kinds


def drop_masks(raw_files, kinds):
    """Split raw_files into (images, masks), pairing each smask with the image it belongs to.

    Returns ([(image_file, mask_file_or_None), ...], [all mask files]). If the pdfimages
    listing doesn't line up with the files, keep everything as plain images."""
    if len(kinds) != len(raw_files):
        return [(f, None) for f in raw_files], []
    pairs, masks = [], []
    for f, k in zip(raw_files, kinds):
        if k == "smask" and pairs:
            pairs[-1] = (pairs[-1][0], f)
            masks.append(f)
        elif k != "smask":
            pairs.append((f, None))
    return pairs, masks


def flatten_on_white(image_path, mask_path):
    """Apply a soft mask as transparency and composite onto white.

    pdfimages writes the mask as a separate grayscale PNG; without this step a
    transparent-background figure (black line art on 'nothing') becomes black on
    black and is unreadable."""
    try:
        from PIL import Image
        with Image.open(image_path) as im, Image.open(mask_path) as mk:
            im = im.convert("RGB")
            mk = mk.convert("L").resize(im.size)
            white = Image.new("RGB", im.size, (255, 255, 255))
            white.paste(im, mask=mk)
        white.save(image_path)
    except Exception:
        pass  # keep the raw image rather than lose it


def extract_images(pdf_path, images_dir, total_pages):
    from PIL import Image  # noqa: F401  (only used if Pillow present; fall back gracefully otherwise)

    images_by_page = {n: [] for n in range(1, total_pages + 1)}
    tmp_prefix = str(images_dir / "_raw")
    kinds_by_page = image_kinds_by_page(pdf_path, total_pages)
    for n in range(1, total_pages + 1):
        run(["pdfimages", "-png", "-f", str(n), "-l", str(n), pdf_path, tmp_prefix])
        pairs, masks = drop_masks(sorted(images_dir.glob("_raw-*.png")), kinds_by_page.get(n, []))
        for f, mk in pairs:
            if mk is not None:
                flatten_on_white(f, mk)
        for m in masks:
            m.unlink()
        for idx, (f, _mk) in enumerate(pairs, start=1):
            keep = True
            try:
                from PIL import Image as PILImage

                with PILImage.open(f) as im:
                    if im.width < MIN_IMAGE_DIM or im.height < MIN_IMAGE_DIM:
                        keep = False
            except Exception:
                pass  # Pillow not available; keep image, size filtering skipped
            if keep:
                target = images_dir / f"page_{n:03d}_img{idx}.png"
                f.rename(target)
                images_by_page[n].append(str(target))
            else:
                f.unlink()
    return images_by_page


def extract_images_no_pillow(pdf_path, images_dir, total_pages):
    images_by_page = {n: [] for n in range(1, total_pages + 1)}
    tmp_prefix = str(images_dir / "_raw")
    kinds_by_page = image_kinds_by_page(pdf_path, total_pages)
    for n in range(1, total_pages + 1):
        run(["pdfimages", "-png", "-f", str(n), "-l", str(n), pdf_path, tmp_prefix])
        pairs, masks = drop_masks(sorted(images_dir.glob("_raw-*.png")), kinds_by_page.get(n, []))
        for m in masks:
            m.unlink()
        for idx, (f, _mk) in enumerate(pairs, start=1):
            target = images_dir / f"page_{n:03d}_img{idx}.png"
            f.rename(target)
            images_by_page[n].append(str(target))
    return images_by_page


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("output_dir")
    parser.add_argument("--dpi", type=int, default=None,
                        help=f"render resolution (default {DEFAULT_DPI}; {SCAN_DPI} automatically for scan-like PDFs)")
    args = parser.parse_args()

    pdf_path = os.path.abspath(args.pdf_path)
    output_dir = Path(os.path.abspath(args.output_dir))
    pages_dir = output_dir / "pages"
    text_dir = output_dir / "text"
    images_dir = output_dir / "images"
    for d in (pages_dir, text_dir, images_dir):
        d.mkdir(parents=True, exist_ok=True)

    total_pages = get_page_count(pdf_path)
    print(f"Total pages: {total_pages}")
    if args.dpi is None:
        sample_last = min(total_pages, 5)
        sample = subprocess.run(["pdftotext", "-f", "1", "-l", str(sample_last), pdf_path, "-"],
                                capture_output=True, text=True).stdout
        if len(re.sub(r"\s+", "", sample)) < SCAN_TEXT_CHARS_PER_PAGE * sample_last:
            args.dpi = SCAN_DPI
            print(f"No text layer detected (looks like a scan): rendering at {SCAN_DPI} dpi instead of {DEFAULT_DPI}")
        else:
            args.dpi = DEFAULT_DPI

    rendered = render_pages(pdf_path, pages_dir, total_pages, args.dpi)
    print(f"Rendered {len(rendered)} page images @ {args.dpi}dpi -> {pages_dir}")

    text_files = extract_text(pdf_path, text_dir, total_pages)
    print(f"Extracted text drafts -> {text_dir}")

    try:
        images_by_page = extract_images(pdf_path, images_dir, total_pages)
    except ImportError:
        images_by_page = extract_images_no_pillow(pdf_path, images_dir, total_pages)
    n_images = sum(len(v) for v in images_by_page.values())
    print(f"Extracted {n_images} candidate embedded images -> {images_dir}")
    print("(these are candidates only -- the transcription step decides which ones "
          "actually get kept as files vs. replaced by a text description)")

    manifest = {
        "pdf_path": pdf_path,
        "total_pages": total_pages,
        "dpi": args.dpi,
        "pages": [
            {
                "page": n,
                "render_file": rendered.get(n),
                "text_file": text_files.get(n),
                "embedded_images": images_by_page.get(n, []),
            }
            for n in range(1, total_pages + 1)
        ],
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Wrote manifest -> {manifest_path}")


if __name__ == "__main__":
    main()

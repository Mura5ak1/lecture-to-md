#!/usr/bin/env python3
"""
Heuristic page classifier for lecture-to-md.

Reads manifest.json (produced by render_pdf_pages.py) plus the layout-preserved
text drafts, and outputs a per-page classification used for two purposes:

1. Step 2 (hybrid page classification): pages labeled "pure_text" can skip
   opening render_file; pages labeled "needs_image" or "ambiguous" must be
   opened and read against the image ("애매하면 무조건 연다" rule still applies
   to "ambiguous" pages -- this script is a heuristic pre-filter, not a
   replacement for judgment).
2. Step 7 (mandatory risk-based sample re-check): pure_text pages carry a
   risk_score used to rank which ones are most worth re-opening and
   double-checking against the render image after transcription is done.

This script never calls any LLM -- it's a cheap, deterministic pass meant to
reduce how much per-page reasoning is needed during steps 2 and 7. Besides
regexes over the text drafts it does one pixel check on the page render: long
ruled lines (table borders). Text extraction cannot see borders, so a table
whose cells are left-aligned words looks like plain prose in the draft.

Usage:
    python3 classify_pages.py <추출작업폴더>

Produces:
    <추출작업폴더>/classification.json
"""
import bisect
import json
import re
import sys
from pathlib import Path

# Crude "table-like line" detector: 2+ runs of 3+ spaces separating tokens on
# one line (a real table cell layout usually produces several of these).
TABLE_LINE_RE = re.compile(r"(?:\S+ {3,}){2,}\S+")

# Crude "this line probably contains a formula" detector: math operators,
# subscript-like patterns (x_1), or Greek letters.
MATH_SYMBOL_RE = re.compile(r"[=±√∑Σ∫≈≤≥×÷∆∇]|[a-zA-Z]_[\w{]|[α-ωΑ-Ω]")

# Pages in the top (1 - this) fraction of char_count are flagged "long" for
# risk-scoring purposes -- longer pages have more surface area for a
# transcription slip to hide in.
LONG_PAGE_PERCENTILE = 0.8

# A page with fewer extracted characters than this (and an embedded image) is treated as
# having no text layer -- typical of scans. If most pages look like that, the whole
# document is scan-like.
NO_TEXT_CHARS = 20
SCAN_LIKE_FRACTION = 0.8


# Ruled-line table detector: count pixel rows/columns that contain one long
# contiguous dark run. Real tables measured 5-13 horizontal / 4-9 vertical runs,
# plain text pages measured 0 / 0.
DARK_THRESHOLD = 110
H_LINE_FRACTION = 0.25   # a horizontal rule spans >= 25% of page width
V_LINE_FRACTION = 0.15   # a vertical rule spans >= 15% of page height
MIN_H_LINES = 3
MIN_V_LINES = 2


def ruled_lines(render_path):
    """Return (h_line_rows, v_line_cols) or None if the image can't be analysed."""
    try:
        import numpy as np
        from PIL import Image
        mask = np.array(Image.open(render_path).convert("L")) < DARK_THRESHOLD
    except Exception:
        return None

    def longest_run_per_row(m):
        c = np.cumsum(m, axis=1)
        reset = np.maximum.accumulate(np.where(m, 0, c), axis=1)
        return (c - reset).max(axis=1)

    h, w = mask.shape
    h_lines = int((longest_run_per_row(mask) >= H_LINE_FRACTION * w).sum())
    v_lines = int((longest_run_per_row(mask.T) >= V_LINE_FRACTION * h).sum())
    return h_lines, v_lines


def load_text(path):
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def score_page(page, char_counts_sorted):
    text = load_text(page.get("text_file"))
    char_count = len(text)
    lines = text.splitlines()

    table_hits = sum(1 for l in lines if TABLE_LINE_RE.search(l))
    math_hits = len(MATH_SYMBOL_RE.findall(text))
    n_images = len(page.get("embedded_images") or [])

    reasons = []
    if char_count < NO_TEXT_CHARS and n_images > 0:
        reasons.append("no_text_layer")
    if n_images > 0:
        reasons.append(f"embedded_images={n_images}")
    if table_hits >= 2:
        reasons.append(f"table_like_lines={table_hits}")
    if math_hits >= 3:
        reasons.append(f"math_symbol_hits={math_hits}")

    rules = ruled_lines(page["render_file"]) if page.get("render_file") else None
    has_rules = bool(rules and rules[0] >= MIN_H_LINES and rules[1] >= MIN_V_LINES)
    if has_rules:
        reasons.append(f"ruled_lines_h{rules[0]}_v{rules[1]}")

    if n_images > 0 or table_hits >= 2 or math_hits >= 3 or has_rules:
        label = "needs_image"
    elif char_count == 0 or table_hits == 1 or 1 <= math_hits < 3:
        label = "ambiguous"
        reasons.append("weak_signal_below_threshold")
    else:
        label = "pure_text"

    # percentile rank of this page's char_count among all pages (0=shortest, 1=longest)
    percentile_rank = 0.0
    if char_counts_sorted:
        idx = bisect.bisect_left(char_counts_sorted, char_count)
        percentile_rank = idx / len(char_counts_sorted)

    # risk_score is only meaningful for step 7 sampling among pure_text pages
    # (needs_image/ambiguous pages are already opened and read during step 2-3,
    # so they don't need this secondary risk ranking)
    risk_score = 0
    if label == "pure_text":
        if percentile_rank >= LONG_PAGE_PERCENTILE:
            risk_score += 2
            reasons.append("long_page_top20pct")
        if table_hits >= 1 or math_hits >= 1:
            risk_score += 1
            reasons.append("weak_table_or_math_signal")

    return {
        "page": page["page"],
        "label": label,
        "char_count": char_count,
        "risk_score": risk_score,
        "reasons": reasons,
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 classify_pages.py <추출작업폴더>", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(sys.argv[1])
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"manifest.json not found in {out_dir} -- run render_pdf_pages.py first", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = manifest["pages"]

    char_counts_sorted = sorted(len(load_text(p.get("text_file"))) for p in pages)

    results = [score_page(p, char_counts_sorted) for p in pages]

    n_pure = sum(1 for r in results if r["label"] == "pure_text")
    n_needs = sum(1 for r in results if r["label"] == "needs_image")
    n_amb = sum(1 for r in results if r["label"] == "ambiguous")

    out_path = out_dir / "classification.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    n_notext = sum(1 for r in results if "no_text_layer" in r["reasons"])
    print(f"Classified {len(results)} pages -> {out_path}")
    if results and n_notext >= SCAN_LIKE_FRACTION * len(results):
        print(f"SCAN-LIKE DOCUMENT: {n_notext}/{len(results)} pages have no text layer. There is no text draft to "
              f"lean on -- every page must be read from its image (render at --dpi 150+), and step 7 samples "
              f"from all pages, not from pure_text.")
    print(f"  pure_text={n_pure}  needs_image={n_needs}  ambiguous={n_amb}")
    print("(ambiguous pages must still be opened per the '애매하면 무조건 연다' rule)")


if __name__ == "__main__":
    main()

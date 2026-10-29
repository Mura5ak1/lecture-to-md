#!/usr/bin/env python3
"""
Mechanical checks for a lecture-to-md conversion. Run before calling it done.

Exit codes:
    0  PASS    -- no structural problem, no page flagged for review
    1  FAIL    -- structural problem (missing/duplicate/out-of-order page anchors,
                  bad frontmatter, broken/orphaned images, malformed tables,
                  unbalanced LaTeX, summary-like phrases, leftover TODO markers)
    2  REVIEW  -- structure is fine, but some pages look like they lost content
                  compared to the text draft. These pages MUST be opened against
                  their render image and either fixed or confirmed clean.

Structural checks (FAIL):
  1. Frontmatter has all required keys with non-empty values, and 총페이지
     equals the page count in manifest.json.
  2. Every page 1..N has exactly one `## [p.N]` heading, in ascending order,
     and no section is empty.
  3. Every image link points to a file that exists; every file delivered in
     images/ is referenced (no dead files, no broken links); alt text is non-empty.
  4. Markdown tables: separator row present and every row has the same column
     count as the header.
  5. LaTeX: `$$` blocks and inline `$` are balanced, braces are balanced.
  6. No leftover `TODO` markers or summary-like phrases ("중략", "이하 생략",
     "이하 동일", "(생략)", "등등" as filler) -- those signal dropped content.
  7. No accidental links: source text shaped like `[x](y)` must be escaped as
     `\\[x\\](y)`; every non-image link must target a URL, a #anchor or an existing file.

Content check (REVIEW), using text/page_NNN.txt drafts from render_pdf_pages.py:
  For every page that has a text layer, take the words (Korean >=2 chars,
  Latin >=3 chars) and numbers (>=2 digits, or with a decimal point) found in
  the draft and check that each still appears in that page's md section
  (whitespace-insensitive). Tokens that appear in the draft of many pages
  (repeated running footers/headers) are ignored, matching the rule that
  repeated footers are only transcribed once.
  A page is flagged when word recall < 0.85 or >= 2 numbers are missing.
  Image-only pages (embedded images but a near-empty text draft, e.g. a table or
  handwriting pasted as a picture) are invisible to that recall check, so they
  get their own rule: flagged if the md section is almost empty AND has no image
  link.
  This is a smoke alarm, not a proof: pdftotext drafts can be garbled, so a
  flagged page is not necessarily wrong -- but an unflagged page is also not
  proven right. Pages without a text layer (scans) cannot be checked this way
  and are listed separately.

Usage:
    python3 validate_output.py <output.md> <extraction_dir> [--json report.json]

<extraction_dir> is the directory passed to render_pdf_pages.py.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

REQUIRED_FM_KEYS = ["과목", "강의명/주차", "원본파일", "총페이지", "변환일"]
SUMMARY_PHRASES = ["중략", "이하 생략", "이하 동일", "(생략)", "[생략]", "이하 같음", "…(이하)", "(이하 생략)"]
RECALL_THRESHOLD = 0.85
MISSING_NUMBERS_THRESHOLD = 2
IMAGE_ONLY_DRAFT_CHARS = 60  # text draft shorter than this on a page with embedded images => content is in the image
IMAGE_ONLY_MD_CHARS = 40
FOOTER_PAGE_FRACTION = 0.4  # token seen on >= this fraction of pages => running header/footer

WORD_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)+|\d{2,}")
IMG_LINK_RE = re.compile(r"!\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^##\s*\[p\.(\d+)\]", re.MULTILINE)


def split_sections(md_text):
    """Return {page: section_text} using `## [p.N]` anchors (last one wins on duplicates)."""
    matches = list(HEADING_RE.finditer(md_text))
    sections = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        sections[int(m.group(1))] = md_text[m.end():end]
    return sections, [int(m.group(1)) for m in matches]


def norm(s):
    """NFKC folds subscripts/superscripts and math-italic letters (H₂SO₄ -> H2SO4, 𝑄 -> Q);
    U+2212 minus becomes '-'. Applied to both the draft and the md so that a faithful
    transcription of CO₃²⁻ is not reported as missing 'CO32-'."""
    return unicodedata.normalize("NFKC", s).replace("\u2212", "-")


def squash(s):
    return re.sub(r"\s+", "", norm(s))


_LATEX_CMD_RE = re.compile(r"\\(?:[A-Za-z]+|[,;:! ])")
_MARKUP_RE = re.compile(r"</?(?:sub|sup|b|i|u|s|del|em|strong)>|[_^{}$~*`\\]")


def flatten_markup(s):
    """Strip LaTeX and inline HTML/markdown formatting so a faithfully typeset
    transcription can be compared with the plain-text draft:
    `W<sub>shaft</sub>` -> Wshaft, `lb_f` -> lbf, `v_1^2` -> v12, `\\mathbf{S}\\,dA` -> SdA.
    Deliberately lossy: it only serves the content-loss smoke alarm."""
    return _MARKUP_RE.sub("", _LATEX_CMD_RE.sub("", s))


def _yaml_unsafe_plain(v):
    """True if v would break (or be misread by) a YAML parser as an unquoted scalar.
    Obsidian then shows the whole properties block as red raw text."""
    if not v or v[0] in "\"'":
        return False
    return ": " in v or " #" in v or v.endswith(":") or v[0] in "[]{}&*!|>%@`,"


def check_frontmatter(md_text, total_pages, problems):
    fm = re.match(r"^---\n(.*?)\n---", md_text, re.DOTALL)
    if not fm:
        problems.append("frontmatter block (--- ... ---) not found at top of file")
        return
    values = {}
    for line in fm.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if _yaml_unsafe_plain(v):
                problems.append(
                    f"frontmatter value of {k.strip()} is not valid YAML as a plain scalar "
                    f"(contains `: `, ` #`, or starts with a YAML indicator) - wrap it in double quotes: {v}")
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            values[k.strip()] = v
    for key in REQUIRED_FM_KEYS:
        if key not in values:
            problems.append(f"frontmatter missing key: {key}")
        elif not values[key]:
            problems.append(f"frontmatter key is empty: {key}")
    if values.get("총페이지"):
        m = re.search(r"\d+", values["총페이지"])
        if not m or int(m.group()) != total_pages:
            problems.append(f"frontmatter 총페이지={values['총페이지']} but manifest says {total_pages}")
    if values.get("변환일") and not re.match(r"\d{4}-\d{2}-\d{2}$", values["변환일"]):
        problems.append(f"변환일 not in YYYY-MM-DD form: {values['변환일']}")


def check_anchors(sections, order, total_pages, problems):
    dupes = sorted({n for n in order if order.count(n) > 1})
    if dupes:
        problems.append(f"duplicate `## [p.N]` headings for pages: {dupes}")
    missing = [n for n in range(1, total_pages + 1) if n not in sections]
    if missing:
        problems.append(f"pages with no `## [p.N]` heading: {missing}")
    extra = sorted(n for n in sections if n < 1 or n > total_pages)
    if extra:
        problems.append(f"`## [p.N]` headings outside 1..{total_pages}: {extra}")
    if order != sorted(order):
        problems.append("`## [p.N]` headings are not in ascending page order")
    empty = [n for n, body in sections.items() if not body.strip()]
    if empty:
        problems.append(f"sections with an empty body: {sorted(empty)}")


def check_images(md_text, md_path, problems, skip_files=False):
    links = IMG_LINK_RE.findall(md_text)
    referenced = set()
    for alt, target in links:
        target = target.split()[0].strip("<>")
        if re.match(r"[a-z]+://", target):
            continue
        referenced.add(Path(target).name)
        if not skip_files and not (md_path.parent / target).exists():
            problems.append(f"image link points to a missing file: {target}")
        if not alt.strip():
            problems.append(f"image has empty alt text: {target}")
    if skip_files:
        return len(links), 0
    images_dir = md_path.parent / "images"
    delivered = [p for p in images_dir.iterdir() if p.is_file()] if images_dir.exists() else []
    # A shared images/ folder holds other documents' files too (each is prefixed
    # with its document title), so files prefixed by a *different* document are
    # skipped. This document's own files and unprefixed files must be referenced.
    prefix = md_path.stem + "__"
    orphaned = [p.name for p in delivered
                if (p.name.startswith(prefix) or "__" not in p.name)
                and p.name not in referenced and p.name not in md_text]
    if orphaned:
        problems.append(f"{len(orphaned)} delivered image file(s) never referenced (dead files): " + ", ".join(orphaned))
    return len(links), len(delivered)


def check_tables(md_text, problems):
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            block = lines[i:j]
            i = j
            def cols(row):
                row = row.strip()
                row = row[1:] if row.startswith("|") else row
                row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
                return len(re.split(r"(?<!\\)\|", row))
            if len(block) < 2 or not re.match(r"^\s*\|?\s*:?-{3,}", block[1]):
                problems.append(f"table near line {lines.index(block[0]) + 1} has no header separator row")
                continue
            width = cols(block[0])
            for k, row in enumerate(block):
                if cols(row) != width:
                    problems.append(
                        f"table near line {lines.index(block[0]) + 1}: row {k + 1} has {cols(row)} columns, header has {width}")
                    break
        else:
            i += 1


def check_latex(md_text, problems):
    # strip fenced code blocks so `$` in code isn't counted
    text = re.sub(r"```.*?```", "", md_text, flags=re.DOTALL)
    # image alt text is plain text, never rendered as math: a currency `$934.00`
    # in an alt must not be counted as an inline-math delimiter
    text = IMG_LINK_RE.sub("", text)
    n_block = text.count("$$")
    if n_block % 2:
        problems.append("unbalanced `$$` (odd number of block-math delimiters)")
    inline_text = text.replace("$$", "")
    inline_text = inline_text.replace("\\$", "")
    if inline_text.count("$") % 2:
        problems.append("unbalanced inline `$` (odd number of inline-math delimiters)")
    for m in re.finditer(r"\$\$(.*?)\$\$", text, re.DOTALL):
        body = m.group(1)
        if body.count("{") != body.count("}"):
            problems.append(f"unbalanced braces in a `$$` block: {body.strip()[:50]!r}")
    for m in re.finditer(r"(?<!\$)\$([^$\n]+)\$(?!\$)", text):
        body = m.group(1)
        if body.count("{") != body.count("}"):
            problems.append(f"unbalanced braces in inline math: {body[:50]!r}")


# non-image `[text](target)`; text may hold one level of nested brackets
_LINK_RE = re.compile(r"(?<![!\\])\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\n]*)\)")
_LINK_FILE_EXTS = {".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def check_links(md_text, md_path, problems, skip_files=False):
    """Source text shaped like `[x](y)` (graph-axis units `[O2](mg/L)`, blanks `[ ](..)`,
    formulas) is rendered by Obsidian as a link: the bracket text turns into a link and
    `(y)` disappears. Every non-image link must point to a URL, a `#anchor` or an existing
    file; anything else is source text that has to be escaped as `\\[x\\](y)`.
    Code, math, HTML comments, images, wikilinks and already-escaped brackets are not links."""
    text = re.sub(r"```.*?```", " ", md_text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"(?<!\\)\$[^$\n]+\$", " ", text)
    text = IMG_LINK_RE.sub(" ", text)
    text = re.sub(r"(?<!\\)\[\[[^\]\n]*\]\]", " ", text)  # Obsidian wikilinks, even when followed by "(..)"
    for m in _LINK_RE.finditer(text):
        target = m.group(2).strip()
        target = target.split()[0].strip("<>") if target else ""
        if re.match(r"(?:[a-z][a-z0-9+.-]*://|mailto:|#)", target, re.IGNORECASE):
            continue
        path = unquote(target.split("#")[0])
        if path:
            if skip_files:
                if Path(path).suffix.lower() in _LINK_FILE_EXTS:
                    continue
            else:
                base = md_path.parent / path
                if base.exists() or base.with_name(base.name + ".md").exists():
                    continue
        problems.append(
            f"text parsed as a markdown link whose target is not a URL, #anchor or existing file: "
            f"{m.group(0)[:60]!r} - original text shaped like [x](y) must be escaped as \\[x\\](y)")


def check_markers(md_text, problems, source_text=""):
    if re.search(r"TODO", md_text) and "TODO" not in source_text:
        problems.append("leftover TODO marker in the md")
    for phrase in SUMMARY_PHRASES:
        # a phrase that the source slides themselves contain is legitimate content
        if phrase in md_text and phrase not in source_text:
            problems.append(f"summary-like phrase found (content may have been dropped): {phrase!r}")


def content_check(sections, manifest, extraction_dir):
    pages = manifest["pages"]
    drafts = {}
    for p in pages:
        tf = p.get("text_file")
        text = Path(tf).read_text(encoding="utf-8", errors="replace") if tf and Path(tf).exists() else ""
        drafts[p["page"]] = norm(text)
    no_text = [n for n, t in drafts.items() if len(squash(t)) < 20]
    checkable = [n for n in drafts if n not in no_text]

    # running header/footer tokens: appear in the draft of many pages
    doc_freq = {}
    for n in checkable:
        toks = set(WORD_RE.findall(drafts[n])) | set(NUM_RE.findall(drafts[n]))
        for t in toks:
            doc_freq[t] = doc_freq.get(t, 0) + 1
    limit = max(3, FOOTER_PAGE_FRACTION * len(checkable))
    footer_tokens = {t for t, c in doc_freq.items() if c >= limit} if len(checkable) >= 5 else set()

    flagged, report = [], {}

    # Pages whose content lives in embedded images: the text draft is nearly empty,
    # so the recall check below is blind to them. Flag when the md section is also
    # nearly empty and carries no image link.
    for p in pages:
        n = p["page"]
        if not p.get("embedded_images") or len(squash(drafts[n])) >= IMAGE_ONLY_DRAFT_CHARS:
            continue
        section = sections.get(n, "")
        has_link = bool(IMG_LINK_RE.search(section))
        prose = squash(IMG_LINK_RE.sub("", section))
        if not has_link and len(prose) < IMAGE_ONLY_MD_CHARS:
            report[n] = {"recall": None, "note": "image-only page but the md section is almost empty"}
            flagged.append(n)

    for n in checkable:
        if n in report:
            continue
        body = squash(flatten_markup(sections.get(n, "")))
        words = {w for w in WORD_RE.findall(drafts[n]) if w not in footer_tokens}
        # the slide's own page number is carried by the `## [p.N]` anchor, not by body text
        nums = {x for x in NUM_RE.findall(drafts[n]) if x not in footer_tokens and x != str(n)}
        miss_w = sorted(w for w in words if w not in body)
        miss_n = sorted(x for x in nums if x not in body)
        recall = 1.0 if not words else 1 - len(miss_w) / len(words)
        report[n] = {"recall": round(recall, 3), "missing_words": miss_w[:20], "missing_numbers": miss_n[:20]}
        if recall < RECALL_THRESHOLD or len(miss_n) >= MISSING_NUMBERS_THRESHOLD:
            flagged.append(n)
    return flagged, no_text, report, len(footer_tokens), "\n".join(drafts.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("extraction_dir")
    ap.add_argument("--json", help="write a per-page report to this path")
    ap.add_argument("--skip-image-files", action="store_true",
                    help="the images/ folder is not available (e.g. a golden md stored alone): skip the "
                         "missing-file and orphan-file checks; links and alt text are still checked")
    ap.add_argument("--ack", default="",
                    help="comma-separated pages flagged REVIEW that you have opened against the render image "
                         "and confirmed correct (e.g. --ack 7,8,13). They are listed as acknowledged and no "
                         "longer produce exit code 2. Only ack a page after actually comparing it.")
    args = ap.parse_args()

    md_path = Path(args.md)
    extraction_dir = Path(args.extraction_dir)
    manifest_path = extraction_dir / "manifest.json"
    if not md_path.exists():
        print(f"FAIL: markdown file not found: {md_path}")
        sys.exit(1)
    if not manifest_path.exists():
        print(f"FAIL: manifest not found: {manifest_path}")
        sys.exit(1)

    md_text = md_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    total_pages = manifest["total_pages"]

    problems = []
    check_frontmatter(md_text, total_pages, problems)
    sections, order = split_sections(md_text)
    check_anchors(sections, order, total_pages, problems)
    n_links, n_delivered = check_images(md_text, md_path, problems, skip_files=args.skip_image_files)
    check_tables(md_text, problems)
    check_latex(md_text, problems)
    check_links(md_text, md_path, problems, skip_files=args.skip_image_files)
    flagged, no_text, report, n_footer, source_text = content_check(sections, manifest, extraction_dir)
    check_markers(md_text, problems, source_text)
    flagged = sorted(set(flagged))
    acked = sorted({int(x) for x in args.ack.split(",") if x.strip().isdigit()} & set(flagged))
    flagged = [n for n in flagged if n not in acked]

    print(f"Checked: {md_path}")
    print(f"Pages: source={total_pages}, anchors={len(set(order))}; image links={n_links}, files in images/={n_delivered}")
    print(f"Content check: {len(report)} pages compared with text drafts "
          f"({n_footer} repeated header/footer tokens ignored)")
    if no_text:
        print(f"  almost no text in the draft (<20 chars; cannot be checked mechanically -- verify visually): {sorted(no_text)}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"problems": problems, "review_pages": flagged, "acknowledged_pages": acked,
             "no_text_pages": sorted(no_text), "pages": report},
            ensure_ascii=False, indent=2), encoding="utf-8")

    if problems:
        print("\nFAIL - structural issues:")
        for p in problems:
            print(f"  - {p}")
    if acked:
        print(f"\nACK - {len(acked)} flagged page(s) acknowledged as visually verified: {acked}")
    if flagged:
        print(f"\nREVIEW - {len(flagged)} page(s) may have lost content vs. the text draft:")
        for n in flagged:
            r = report[n]
            if r.get("note"):
                print(f"  p.{n}: {r['note']}")
                continue
            print(f"  p.{n}: recall={r['recall']}  missing words={r['missing_words'][:8]}  missing numbers={r['missing_numbers'][:8]}")
        print("  Open each page's render image, fix the md or confirm the draft was garbled, then re-run.")

    if problems:
        sys.exit(1)
    if flagged:
        sys.exit(2)
    print("\nPASS - structure OK, no page flagged for content loss.")


if __name__ == "__main__":
    main()

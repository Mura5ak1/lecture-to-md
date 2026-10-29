#!/usr/bin/env python3
"""
Resize/compress a single image so it's cheap to load into a vision model later.

Part of the "선택적 이미지 보존" policy: only images that pass the
"생김새(형태·색상·공간관계) 자체가 정보인가?" test get kept as files at all --
everything else is replaced by a text description instead. For the ones that
DO get kept, this script shrinks them first so that re-reading them later
(e.g. when a study-tutor AI needs to visually double-check a diagram) stays
cheap in vision tokens, instead of shipping the full extraction-resolution
file forever.

Tries Pillow first (best control over resize quality). Falls back to macOS
`sips` if Pillow isn't installed. If neither is available, just copies the
file unchanged -- an uncompressed image is still better than a dropped one.

Usage:
    python3 compress_image.py <input_image> <output_image> [--max-dim 1024]
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MAX_DIM = 1024


def compress_with_pillow(src: Path, dst: Path, max_dim: int) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    with Image.open(src) as im:
        w, h = im.size
        scale = min(1.0, max_dim / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, optimize=True)
        print(f"  {w}x{h} -> {im.size[0]}x{im.size[1]}px, {src.stat().st_size // 1024}KB -> {dst.stat().st_size // 1024}KB "
              f"(vision cost depends on pixel size; file bytes matter little)")
    return True


def compress_with_sips(src: Path, dst: Path, max_dim: int) -> bool:
    if shutil.which("sips") is None:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    try:
        subprocess.run(["sips", "-Z", str(max_dim), str(dst)], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--max-dim", type=int, default=DEFAULT_MAX_DIM)
    args = parser.parse_args()

    src, dst = Path(args.input), Path(args.output)
    if not src.exists():
        print(f"FAIL: input not found: {src}")
        sys.exit(1)

    if compress_with_pillow(src, dst, args.max_dim):
        print(f"Compressed via Pillow -> {dst}")
        return
    if compress_with_sips(src, dst, args.max_dim):
        print(f"Compressed via sips -> {dst}")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"WARNING: no resize tool available (Pillow/sips both missing) -- copied uncompressed -> {dst}")


if __name__ == "__main__":
    main()

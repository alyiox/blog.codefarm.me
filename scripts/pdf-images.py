#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pymupdf>=1.24.0",
# ]
# ///
"""Extract raster images and vector illustrations (SVG) from a PDF.

Many illustrated PDFs store diagrams as vector drawings / Form XObjects, not
as embedded image XObjects. This script:

  * extracts raster images (XObject + inline)
  * exports vector illustration regions (or full pages) as SVG

Usage:
  uv run Scripts/extract-pdf-images.py path/to/file.pdf
  uv run Scripts/extract-pdf-images.py path/to/file.pdf -o ./out
  uv run Scripts/extract-pdf-images.py path/to/file.pdf --mode svg
  uv run Scripts/extract-pdf-images.py path/to/file.pdf --mode raster
  uv run Scripts/extract-pdf-images.py path/to/file.pdf --svg-pages
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


EXT_BY_EXT = {
    "png": ".png",
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "jpx": ".jp2",
    "jb2": ".jb2",
    "bmp": ".bmp",
    "tiff": ".tiff",
    "tif": ".tiff",
    "gif": ".gif",
}

# Inline fragments from converted art are often 1–8 px; skip by default.
DEFAULT_MIN_PIXEL_AREA = 2500
DEFAULT_MIN_ILLUSTRATION_AREA = 8000
DEFAULT_MERGE_GAP = 12.0


def extension_for(image_ext: str) -> str:
    return EXT_BY_EXT.get(image_ext.lower(), f".{image_ext.lower()}")


def unique_name(out_dir: Path, stem: str, ext: str, digest: str) -> Path:
    candidate = out_dir / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    return out_dir / f"{stem}-{digest[:8]}{ext}"


def save_bytes(
    out_dir: Path,
    stem: str,
    ext: str,
    data: bytes,
    *,
    seen: set[str],
    dedupe: bool,
) -> Path | None:
    digest = hashlib.sha256(data).hexdigest()
    if dedupe and digest in seen:
        return None
    seen.add(digest)
    dest = unique_name(out_dir, stem, ext, digest)
    dest.write_bytes(data)
    return dest


def save_text(
    out_dir: Path,
    stem: str,
    text: str,
    *,
    seen: set[str],
    dedupe: bool,
) -> Path | None:
    data = text.encode("utf-8")
    return save_bytes(out_dir, stem, ".svg", data, seen=seen, dedupe=dedupe)


def merge_rects(rects: list[fitz.Rect], gap: float) -> list[fitz.Rect]:
    """Merge rectangles that touch or fall within ``gap`` points of each other."""
    pending = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        merged: list[fitz.Rect] = []
        while pending:
            current = pending.pop()
            i = 0
            while i < len(pending):
                other = pending[i]
                expanded = fitz.Rect(
                    current.x0 - gap,
                    current.y0 - gap,
                    current.x1 + gap,
                    current.y1 + gap,
                )
                if expanded.intersects(other):
                    current |= other
                    pending.pop(i)
                    changed = True
                else:
                    i += 1
            merged.append(current)
        pending = merged
    return pending


def illustration_regions(
    page: fitz.Page,
    *,
    min_area: float,
    merge_gap: float,
    min_drawings: int,
) -> list[fitz.Rect]:
    drawings = page.get_drawings()
    if len(drawings) < min_drawings:
        return []

    rects: list[fitz.Rect] = []
    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is None:
            continue
        r = fitz.Rect(rect)
        if r.get_area() > 1:
            rects.append(r)

    # Include medium+ inline image boxes so mixed raster/vector art clusters.
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 1:
            continue
        width = int(block.get("width") or 0)
        height = int(block.get("height") or 0)
        if width * height < DEFAULT_MIN_PIXEL_AREA:
            continue
        rects.append(fitz.Rect(block["bbox"]))

    if not rects:
        return []

    page_area = page.rect.get_area()
    regions = []
    for rect in merge_rects(rects, gap=merge_gap):
        area = rect.get_area()
        if area < min_area:
            continue
        # Full-page unions are better exported with --svg-pages.
        if area >= 0.85 * page_area:
            continue
        # Clamp to page and pad slightly so strokes aren't clipped.
        padded = fitz.Rect(rect) + (-2, -2, 2, 2)
        regions.append(padded & page.rect)
    return regions


def svg_for_clip(doc: fitz.Document, page_index: int, clip: fitz.Rect) -> str:
    """Render a page clip as SVG via a temporary single-page document."""
    clip = fitz.Rect(clip)
    width = max(clip.width, 1.0)
    height = max(clip.height, 1.0)
    tmp = fitz.open()
    try:
        tmp_page = tmp.new_page(width=width, height=height)
        tmp_page.show_pdf_page(tmp_page.rect, doc, page_index, clip=clip)
        return tmp_page.get_svg_image()
    finally:
        tmp.close()


def extract_rasters(
    doc: fitz.Document,
    out_dir: Path,
    *,
    min_bytes: int,
    min_pixel_area: int,
    dedupe: bool,
    seen: set[str],
) -> tuple[int, int]:
    saved = 0
    skipped = 0
    written_xrefs: set[int] = set()

    # Document-wide Image XObjects (covers unused / shared objects).
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Subtype")[1] != "/Image":
                continue
        except Exception:  # noqa: BLE001
            continue
        if xref in written_xrefs:
            continue
        try:
            extracted = doc.extract_image(xref)
        except Exception as exc:  # noqa: BLE001
            print(f"skip xref={xref}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        data: bytes = extracted["image"]
        width = int(extracted.get("width") or 0)
        height = int(extracted.get("height") or 0)
        if len(data) < min_bytes or width * height < min_pixel_area:
            skipped += 1
            continue

        dest = save_bytes(
            out_dir,
            f"xref{xref:05d}",
            extension_for(extracted.get("ext", "bin")),
            data,
            seen=seen,
            dedupe=dedupe,
        )
        written_xrefs.add(xref)
        if dest is None:
            skipped += 1
            continue
        saved += 1
        print(f"wrote {dest} ({len(data)} bytes, {width}x{height})")

    # Inline images (xref 0) only appear via text-dict image blocks.
    for page_index, page in enumerate(doc, start=1):
        img_index = 0
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 1:
                continue
            data = block.get("image") or b""
            width = int(block.get("width") or 0)
            height = int(block.get("height") or 0)
            if not data or len(data) < min_bytes or width * height < min_pixel_area:
                skipped += 1
                continue
            # Skip blocks that are just views of XObjects we already wrote.
            # Inline-only blocks have no stable xref in the dict payload.
            img_index += 1
            dest = save_bytes(
                out_dir,
                f"page{page_index:04d}-inline{img_index:03d}",
                extension_for(block.get("ext", "png")),
                data,
                seen=seen,
                dedupe=dedupe,
            )
            if dest is None:
                skipped += 1
                continue
            saved += 1
            print(f"wrote {dest} ({len(data)} bytes, {width}x{height})")

    return saved, skipped


def extract_svgs(
    doc: fitz.Document,
    out_dir: Path,
    *,
    full_pages: bool,
    min_illustration_area: float,
    merge_gap: float,
    min_drawings: int,
    dedupe: bool,
    seen: set[str],
) -> tuple[int, int]:
    saved = 0
    skipped = 0

    for page_index, page in enumerate(doc, start=1):
        if full_pages:
            drawings = page.get_drawings()
            if len(drawings) < min_drawings and not page.get_images():
                skipped += 1
                continue
            svg = page.get_svg_image()
            dest = save_text(
                out_dir,
                f"page{page_index:04d}",
                svg,
                seen=seen,
                dedupe=dedupe,
            )
            if dest is None:
                skipped += 1
                continue
            saved += 1
            print(f"wrote {dest} ({len(svg)} chars, full page)")
            continue

        regions = illustration_regions(
            page,
            min_area=min_illustration_area,
            merge_gap=merge_gap,
            min_drawings=min_drawings,
        )
        if not regions:
            continue

        for region_index, clip in enumerate(regions, start=1):
            try:
                svg = svg_for_clip(doc, page_index - 1, clip)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"skip page {page_index} region {region_index}: {exc}",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            # Drop nearly-empty SVGs (no path/image content).
            if not re.search(r"<(path|image|use|text)\b", svg):
                skipped += 1
                continue

            dest = save_text(
                out_dir,
                f"page{page_index:04d}-illust{region_index:02d}",
                svg,
                seen=seen,
                dedupe=dedupe,
            )
            if dest is None:
                skipped += 1
                continue
            saved += 1
            print(
                f"wrote {dest} ({len(svg)} chars, "
                f"{clip.width:.0f}x{clip.height:.0f} pt)"
            )

    return saved, skipped


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract raster images and/or vector illustrations (SVG) from a PDF."
        ),
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <pdf-stem>-images next to the PDF)",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "raster", "svg"),
        default="all",
        help="What to extract (default: all)",
    )
    parser.add_argument(
        "--svg-pages",
        action="store_true",
        help="Export each page with drawings as a full-page SVG "
        "(default: crop illustration regions)",
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=1,
        help="Skip rasters smaller than this many bytes (default: 1)",
    )
    parser.add_argument(
        "--min-pixel-area",
        type=int,
        default=DEFAULT_MIN_PIXEL_AREA,
        help=(
            "Skip rasters with width*height below this "
            f"(default: {DEFAULT_MIN_PIXEL_AREA})"
        ),
    )
    parser.add_argument(
        "--min-illustration-area",
        type=float,
        default=DEFAULT_MIN_ILLUSTRATION_AREA,
        help=(
            "Skip SVG regions smaller than this many pt^2 "
            f"(default: {DEFAULT_MIN_ILLUSTRATION_AREA})"
        ),
    )
    parser.add_argument(
        "--merge-gap",
        type=float,
        default=DEFAULT_MERGE_GAP,
        help="Gap (pt) when merging nearby drawing boxes into one region",
    )
    parser.add_argument(
        "--min-drawings",
        type=int,
        default=20,
        help="Minimum path count before treating a page as illustrated",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Keep duplicate outputs that share the same bytes",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pdf_path: Path = args.pdf.expanduser().resolve()

    if not pdf_path.is_file():
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.suffix.lower() != ".pdf":
        print(f"error: not a .pdf file: {pdf_path}", file=sys.stderr)
        return 1

    out_dir = (
        args.output.expanduser().resolve()
        if args.output is not None
        else pdf_path.with_name(f"{pdf_path.stem}-images")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"reading {pdf_path}")
    print(f"writing to {out_dir}")
    print(f"mode={args.mode}")

    seen: set[str] = set()
    raster_saved = raster_skipped = 0
    svg_saved = svg_skipped = 0
    dedupe = not args.no_dedupe

    with fitz.open(pdf_path) as doc:
        if args.mode in ("all", "raster"):
            raster_saved, raster_skipped = extract_rasters(
                doc,
                out_dir,
                min_bytes=args.min_bytes,
                min_pixel_area=args.min_pixel_area,
                dedupe=dedupe,
                seen=seen,
            )
        if args.mode in ("all", "svg"):
            svg_saved, svg_skipped = extract_svgs(
                doc,
                out_dir,
                full_pages=args.svg_pages,
                min_illustration_area=args.min_illustration_area,
                merge_gap=args.merge_gap,
                min_drawings=args.min_drawings,
                dedupe=dedupe,
                seen=seen,
            )

    print(
        f"done: rasters saved={raster_saved} skipped={raster_skipped}; "
        f"svgs saved={svg_saved} skipped={svg_skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

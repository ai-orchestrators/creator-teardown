#!/usr/bin/env python3
"""Lint a rendered teardown before you share it.

Checks the page itself: a viewport meta and a title, no external scripts, no em or en dashes in
visible text, no element showing only "undefined", "NaN", "None" or "null", and a size most hosts accept. With
--spelling au or uk it also flags US spellings in visible text.

Usage: python3 lint_report.py <run>/teardown.html [more.html] [--spelling au]
Exit 0 = clean, 1 = something to fix.
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from report import US_RE

MAX_BYTES = 16 * 1024 * 1024


def visible_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    page = re.sub(r"(?is)<title>.*?</title>", " ", page)
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", page))


def lint(page: str, spelling: str = "as-is") -> list[str]:
    flags = []
    if not re.search(r'<meta[^>]+name="viewport"', page):
        flags.append("no viewport meta: the page will not scale on phones")
    if not re.search(r"<title>[^<]+</title>", page):
        flags.append("no <title>")
    if re.search(r"<script[^>]+\bsrc=", page, re.I):
        flags.append("external <script src>: the page should be self-contained")
    text = visible_text(page)
    dashes = re.findall(r".{0,30}[\u2014\u2013].{0,30}", text)
    if dashes:
        flags.append(f"{len(dashes)} em or en dash(es), e.g. {dashes[0].strip()!r}")
    leaks = re.findall(r">\s*(undefined|NaN|None|null)\s*<", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page))
    if leaks:
        flags.append(f"{len(leaks)} leaked value(s) in visible text: {sorted(set(leaks))}")
    if spelling in ("au", "uk"):
        found = sorted({m.group(0).lower() for m in US_RE.finditer(text)})
        if found:
            flags.append(f"US spelling: {', '.join(found[:10])}")
    size = len(page.encode("utf-8"))
    if size > MAX_BYTES:
        flags.append(f"page is {size / 1_048_576:.1f} MB; many hosts cap a page at 16 MB")
    return flags


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint a rendered teardown page before sharing it.")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--spelling", choices=["as-is", "au", "uk"], default="as-is")
    args = parser.parse_args()
    flagged = 0
    for path in args.files:
        flags = lint(path.read_text(encoding="utf-8"), args.spelling)
        flagged += len(flags)
        print(f"{path}: " + ("clean" if not flags else "\n  " + "\n  ".join(flags)))
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())

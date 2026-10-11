#!/usr/bin/env python3
"""Copy-distance check for a rebuild: how many words in a row does the draft share with the source?

Any shared run of 6+ words fails. Words are compared lower-case with punctuation stripped.

Usage:
    python3 overlap.py --source source.txt --draft draft.txt [--max-run 5]
Exit 0 = pass, 1 = fail. Prints the longest shared run and every failing run.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def shared_runs(source: str, draft: str, min_len: int) -> list[str]:
    """Every maximal run of min_len+ consecutive draft words that also appears in the source."""
    src, dft = words(source), words(draft)
    src_grams = {tuple(src[i:i + min_len]) for i in range(len(src) - min_len + 1)}
    runs, i = [], 0
    while i <= len(dft) - min_len:
        if tuple(dft[i:i + min_len]) not in src_grams:
            i += 1
            continue
        j = i + min_len
        src_text = " " + " ".join(src) + " "
        while j < len(dft) and f" {' '.join(dft[i:j + 1])} " in src_text:
            j += 1
        runs.append(" ".join(dft[i:j]))
        i = j
    return runs


def longest_run(source: str, draft: str) -> int:
    n = 1
    while shared_runs(source, draft, n + 1):
        n += 1
    return n if shared_runs(source, draft, 1) else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--max-run", type=int, default=5, help="longest shared run allowed")
    args = parser.parse_args()
    source = Path(args.source).read_text(encoding="utf-8")
    draft = Path(args.draft).read_text(encoding="utf-8")
    failing = shared_runs(source, draft, args.max_run + 1)
    print(f"longest shared run: {longest_run(source, draft)} words")
    for run in failing:
        print(f"FAIL: \"{run}\"")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())

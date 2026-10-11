#!/usr/bin/env python3
"""Build playbook.review (the Review panel tab) from the checkers' files.

Reads .work/review_challenger.json, .work/review_craft.json and the copy-distance and truth checks
already on playbook.rebuilds. Pass --fixed once every flagged item has been applied: flagged
sections then show as 'fixed', which is the skill's rule (apply every fix, cut every cut).

Usage: python3 merge_review.py <run folder> [--fixed]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


FIELD_PATH = re.compile(r"(?:\b[a-z_]+(?:\.[a-z_]+|\[\d+\])*\[\d+\](?:\.[a-z_]+|\[\d+\])*"
                        r"|\b(?:picture|playbook|patterns)(?:\.[a-z_]+|\[\d+\])+|\b(?:metric_plain|outside_top_shape)\b)\s*[:=]?\s*")


def plain(text):
    """Readers never see field paths like rules[0] or picture.hook[1].text."""
    if not isinstance(text, str):
        return text
    return re.sub(r'\s{2,}', ' ', FIELD_PATH.sub('', text)).strip(" /'\"") or text


def load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def run(run_dir: Path, fixed: bool = False) -> list[dict]:
    work = run_dir / '.work'
    playbook_path = run_dir / 'playbook.json'
    playbook = json.loads(playbook_path.read_text())
    review = []

    challenger = load(work / 'review_challenger.json', [])
    if challenger:
        counts = Counter(item.get('verdict') for item in challenger)
        changed = counts.get('fix', 0) + counts.get('cut', 0)
        review.append({
            'role': 'Challenger',
            'verdict': 'pass' if not changed else ('fixed' if fixed else 'flagged'),
            'summary': (f"Recomputed {len(challenger)} claims from the raw data: {counts.get('keep', 0)} held, "
                        f"{counts.get('fix', 0)} reworded or corrected, {counts.get('cut', 0)} cut."),
            'items': [{'claim': plain(i.get('claim')), 'verdict': i.get('verdict'), 'note': plain(i.get('note') or i.get('check'))}
                      for i in challenger if i.get('verdict') != 'keep']})

    craft = load(work / 'review_craft.json', {})
    for key, role in (('hook', 'Hook check'), ('argument', 'Argument check'), ('ending', 'Ending and CTA check'),
                      ('truth', 'Truth check')):
        part = craft.get(key)
        if not part:
            continue
        verdict = part.get('verdict', 'pass')
        review.append({'role': role, 'verdict': 'fixed' if fixed and verdict == 'flagged' else verdict,
                       'summary': part.get('summary', ''),
                       'items': [i for i in part.get('items', []) if i.get('verdict') != 'pass']})

    rebuilds = playbook.get('rebuilds') or []
    if rebuilds:
        checks = [(r.get('number'), (r.get('checks') or {}).get('copy_distance', '')) for r in rebuilds if r.get('draft')]
        fails = [c for c in checks if 'FAIL' in c[1]]
        review.append({'role': 'Copy distance', 'verdict': 'flagged' if fails else 'pass',
                       'summary': (f"Every draft checked against the creator's own words by script. "
                                   f"{len(checks) - len(fails)} of {len(checks)} share no run of 6 or more words."),
                       'items': [{'claim': f'Rebuild {n}', 'verdict': 'flagged' if 'FAIL' in c else 'pass', 'note': c}
                                 for n, c in checks]})

    playbook['review'] = review
    playbook_path.write_text(json.dumps(playbook, indent=2, ensure_ascii=False))
    return review


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--fixed', action='store_true', help='every flagged item has been applied')
    args = parser.parse_args()
    for entry in run(args.run_dir, args.fixed):
        print(f"{entry['role']}: {entry['verdict']} | {entry['summary'][:100]}")

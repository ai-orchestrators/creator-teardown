#!/usr/bin/env python3
"""Pick the blind sample for step 4: posts spread across bands, with the question forms Jev gets.

Writes <work>/blind_sample.json ({questions, posts}). The blind-label agent reads only this file, so it
never sees Jev's answers. The `instructions` travel with the options: without them the agent would be
judging a different question than Jev does.

Usage: python3 blind_sample.py --work <run>/.work [--n 20] [--seed 7]
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from common import DECISIONS_DIR, read_json, write_json

QUESTIONS = ('hook_type', 'structure', 'evidence', 'ending')
SEGMENTS = ('hook_text', 'opening_text', 'body_text', 'ending_text')


def run(work: Path, *, n: int = 20, seed: int = 7, form_path: Path | None = None) -> dict:
    work = Path(work)
    form = read_json(form_path or DECISIONS_DIR / 'creator.post.v1.json')
    questions = {key: {'instructions': form['questions'][key].get('instructions', ''),
                       'options': form['questions'][key].get('criteria', {})}
                 for key in QUESTIONS if key in form.get('questions', {})}
    features = read_json(work / 'features.json')
    bands = read_json(work / 'outliers.json').get('posts', {})
    rng = random.Random(seed)
    pools = {band: sorted(pid for pid, row in bands.items() if row.get('band') == band and features.get(pid, {}).get('segments'))
             for band in ('outlier', 'normal', 'dud')}
    want = {'outlier': round(n * 0.35), 'dud': round(n * 0.3)}
    want['normal'] = n - want['outlier'] - want['dud']
    picked = []
    for band in ('outlier', 'dud', 'normal'):
        pool = [pid for pid in pools[band] if pid not in picked]
        picked += rng.sample(pool, min(len(pool), want[band]))
    spare = [pid for band in ('normal', 'outlier', 'dud') for pid in pools[band] if pid not in picked]
    picked += spare[:max(0, n - len(picked))]
    rng.shuffle(picked)  # band order would hint at the answer
    posts = [{'post_id': pid, **{key: features[pid]['segments'].get(key, '') for key in SEGMENTS}} for pid in picked]
    payload = {'questions': questions, 'posts': posts}
    write_json(work / 'blind_sample.json', payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description='Pick the blind sample the blind-label agent reads (step 4).')
    parser.add_argument('--work', type=Path, required=True, help='the run .work folder')
    parser.add_argument('--n', type=int, default=20)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    payload = run(args.work, n=args.n, seed=args.seed)
    print(f"blind sample: {len(payload['posts'])} posts, questions {', '.join(payload['questions'])}")


if __name__ == '__main__':
    main()

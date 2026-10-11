#!/usr/bin/env python3
"""Compare blind Claude labels with Jev and seed a golden set.

The sample is appended to config/evals/creator.post.v1/candidates.jsonl (gitignored), so the
set grows across runs. Use it to check the post form before trusting it on a new niche.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from classify import build_post_state
from common import config_dir, read_json, write_json


def run(work: Path, *, candidates_path=None) -> dict:
    work = Path(work)
    candidates_path = Path(candidates_path or config_dir() / 'evals' / 'creator.post.v1' / 'candidates.jsonl')
    features = read_json(work / 'features.json')
    jev = read_json(work / 'labels.json').get('posts', {})
    blind = [json.loads(line) for line in (work / 'claude_labels.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    rows, by_question = [], defaultdict(list)
    for item in blind:
        post_id = str(item['post_id'])
        for qid, claude in item.get('labels', {}).items():
            value = jev.get(post_id, {}).get(qid, {}).get('value', 'unclear')
            agrees = value != 'unclear' and value == claude
            rows.append({'post_id': post_id, 'qid': qid, 'claude': claude, 'jev': value, 'agree': agrees})
            by_question[qid].append(agrees)
    payload = {'n': len(blind), 'by_question': {key: sum(values) / len(values) for key, values in by_question.items()},
               'rows': rows}
    write_json(work / 'agreement.json', payload)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if candidates_path.exists():
        for line in candidates_path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                existing.add(json.loads(line).get('id'))
    with candidates_path.open('a', encoding='utf-8') as target:
        for item in blind:
            post_id = str(item['post_id'])
            feat = features.get(post_id)
            if not feat:
                continue
            identifier = f"{feat.get('platform')}:{post_id}"
            if identifier in existing:
                continue
            candidate = {'id': identifier, 'state': build_post_state(feat), 'labels': item.get('labels', {}),
                         'source': 'claude-blind', 'run': work.name}
            target.write(json.dumps(candidate, ensure_ascii=False) + '\n')
            existing.add(identifier)
    return payload


def main():
    parser = argparse.ArgumentParser(description='Compare the blind Claude sample with Jev.')
    parser.add_argument('--work', type=Path, required=True, help='the run .work folder')
    parser.add_argument('--candidates-path', type=Path, help='default: config/evals/creator.post.v1/candidates.jsonl')
    args = parser.parse_args()
    payload = run(args.work, candidates_path=args.candidates_path)
    print(f"{payload['n']} posts compared")


if __name__ == '__main__':
    main()

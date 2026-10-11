#!/usr/bin/env python3
"""Merge .work/rebuilds/<n>.json into playbook.rebuilds, re-run the copy-distance check on every draft
against its source post, and write rebuild-drafts.md.

Usage: python3 merge_rebuilds.py <run folder>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from overlap import longest_run, shared_runs


def run(run_dir: Path) -> list[dict]:
    work = run_dir / '.work'
    posts = {p['post_id']: p for p in json.loads((work / 'posts.json').read_text())['posts']}
    features = json.loads((work / 'features.json').read_text())
    rebuilds = []
    for path in sorted((work / 'rebuilds').glob('[0-9].json'), key=lambda p: int(p.stem)):
        item = json.loads(path.read_text())
        source_id = str(item.get('source_post_id'))
        feat = features.get(source_id, {})
        source_text = (posts.get(source_id, {}).get('caption') or '') + '\n' + ' '.join(
            s.get('text', '') for s in feat.get('sentences', []))
        draft = item.get('draft') or ''
        if draft:
            fails = shared_runs(source_text, draft, 6)
            run = longest_run(source_text, draft)
            item.setdefault('checks', {})['copy_distance'] = (
                f"longest shared run: {run} word{'' if run == 1 else 's'} "
                + ('(pass)' if not fails else f"(FAIL: {'; '.join(fails[:3])})"))
        item['number'] = int(path.stem)
        rebuilds.append(item)
    playbook_path = run_dir / 'playbook.json'
    playbook = json.loads(playbook_path.read_text())
    playbook['rebuilds'] = rebuilds
    playbook_path.write_text(json.dumps(playbook, indent=2, ensure_ascii=False))
    lines = [f'# Rebuild drafts: {playbook.get("creator", run_dir.name)}', '']
    for item in rebuilds:
        lines += [f'## {item["number"]}. {item.get("title", "")} ({item.get("format", "")})', '',
                  f'Hook: {item.get("chosen_hook", "")}', f'Why: {item.get("chosen_hook_why", "")}', '']
        lines += (['---', '', item['draft'], '', '---'] if item.get('draft') else ['Not drafted. ' + '; '.join(item.get('notes', []))])
        lines += ['', f'CTA: {item.get("cta", "")}', f'Checks: {json.dumps(item.get("checks", {}), ensure_ascii=False)}', '']
    (run_dir / 'rebuild-drafts.md').write_text('\n'.join(lines))
    return rebuilds


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge the rebuild drafts into playbook.json and rebuild-drafts.md.')
    parser.add_argument('run_dir', type=Path, help='the run folder (holds playbook.json and .work/)')
    for r in run(parser.parse_args().run_dir):
        print(r['number'], (r.get('chosen_hook') or 'NOT DRAFTED')[:70], '|', r.get('checks', {}).get('copy_distance'))

#!/usr/bin/env python3
"""Compare post labels and pacing with outlier bands."""
from __future__ import annotations

import argparse
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from common import read_json, write_json


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    for start in range(len(order)):
        if start and values[order[start]] == values[order[start - 1]]:
            continue
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        for pos in order[start:end]:
            result[pos] = (start + 1 + end) / 2
    return result


def spearman(xs, ys):
    if len(xs) < 5 or len(xs) != len(ys) or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    x, y = ranks(xs), ranks(ys)
    mx, my = statistics.mean(x), statistics.mean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return numerator / denominator if denominator else None


def collapse_roles(roles):
    out = []
    for role in roles:
        if role and role != 'unclear' and (not out or role != out[-1]):
            out.append(role)
    return out


def idea_key(text: str) -> str:
    """Posts that open with the same first eight words are one idea posted again."""
    words = re.findall(r"[a-z0-9']+", (text or '').lower())
    return ' '.join(words[:8])


STOPWORDS = set("""the and for you your that this with are was were have has had but not they them what how can
all just get got one from its it's i'm i've don't will more than about when who why our out his her she him their
there then into over most make made like some only also very really because which would could should been being""".split())


def assign_ideas(rows, threshold=0.6):
    """Cluster posts whose first 12 words overlap 60%+ once stopwords go (Jaccard): one idea posted again."""
    clusters = []
    for row in rows:
        words = {w for w in re.findall(r"[a-z0-9']+", (row.get('hook_text') or '').lower())[:12]
                 if len(w) > 2 and w not in STOPWORDS}
        for rep_words, name in clusters:
            # Under 3 real words is too little to call two openings the same idea.
            if len(words) >= 3 and len(rep_words) >= 3 and len(words & rep_words) / len(words | rep_words) >= threshold:
                row['idea'] = name
                break
        else:
            row['idea'] = idea_key(row.get('hook_text')) or row['post_id']
            clusters.append((words, row['idea']))


def lift_table(rows, key, min_n):
    base = sum(r['band'] == 'outlier' for r in rows) / len(rows) if rows else 0
    groups = defaultdict(list)
    for row in rows:
        value = row.get(key)
        groups['unclear' if value is None or value == 'unclear' else str(value)].append(row)
    result = []
    for value, group in groups.items():
        n = len(group)
        outliers = sum(r['band'] == 'outlier' for r in group)
        duds = sum(r['band'] == 'dud' for r in group)
        rate = outliers / n
        multiples = [r['multiple'] for r in group if isinstance(r.get('multiple'), (int, float))]
        ideas = {r.get('idea') for r in group if r['band'] == 'outlier' and r.get('idea')}
        result.append({'value': value, 'n': n, 'outliers': outliers, 'duds': duds,
                       'outlier_ideas': len(ideas) if ideas else outliers,
                       'outlier_rate': rate, 'dud_rate': duds / n,
                       'lift': rate / base if base else None,
                       'median_multiple': statistics.median(multiples) if multiples else None,
                       'tier': 'pattern' if n >= min_n else 'hunch'})
    return sorted(result, key=lambda r: (r['tier'] != 'pattern', -(r['lift'] or 0), -r['n'], r['value']))


def add_outside_top_shape(rows, lifts, min_n):
    """Confound check: does a value still win outside the strongest structure?"""
    patterns = [r for r in lifts.get('structure', []) if r['tier'] == 'pattern' and r['value'] != 'unclear' and r['lift']]
    if not patterns:
        return
    top = patterns[0]['value']
    for key, table in lifts.items():
        if key == 'structure':
            continue
        for entry in table:
            outside = [r for r in rows if str(r.get(key) if r.get(key) not in (None, 'unclear') else 'unclear') == entry['value']
                       and r.get('structure') != top]
            hits = sum(r['band'] == 'outlier' for r in outside)
            entry['outside_top_shape'] = {'shape': top, 'n': len(outside), 'outliers': hits,
                                          'rate': hits / len(outside) if outside else None}


def graduation(source, features, outliers, labels, min_n, now, new_days=7):
    """Two-tier accounts: which trial ideas got re-posted to the main tier?

    One row per idea that has a low-tier post. Graduated = a high-tier post of the same idea on or
    after its first trial. Ideas whose first trial is under new_days old and not yet promoted are
    too new to call and left out. Labels come from the first trial post.
    """
    bands = outliers.get('posts', {})
    rows = []
    for post in source['posts']:
        post_id = str(post['post_id'])
        tier = bands.get(post_id, {}).get('tier')
        if not tier or post_id not in labels.get('posts', {}):
            continue
        feat = features.get(post_id, {})
        rows.append({'post_id': post_id, 'tier': tier, 'posted_at': post.get('posted_at') or '',
                     'hook_text': feat.get('segments', {}).get('hook_text') or (post.get('caption') or '')[:200],
                     'feat': feat, 'labels': labels['posts'][post_id], 'age_h': bands[post_id].get('age_h')})
    if not rows:
        return None
    assign_ideas(rows)
    ideas = defaultdict(list)
    for row in rows:
        ideas[row['idea']].append(row)
    out, too_new, direct = [], 0, 0
    for idea, group in ideas.items():
        group.sort(key=lambda r: r['posted_at'])
        trials = [r for r in group if r['tier'] == 'low']
        if not trials:
            direct += 1
            continue
        first = trials[0]
        promoted = any(r['tier'] == 'high' and r['posted_at'] >= first['posted_at'] for r in group)
        if not promoted and first['age_h'] is not None and first['age_h'] < new_days * 24:
            too_new += 1
            continue
        feat = first['feat']
        row = {'post_id': first['post_id'], 'idea': idea, 'band': 'outlier' if promoted else 'normal',
               'multiple': 1.0 if promoted else 0.0, 'trials': len(trials), 'hook_text': first['hook_text'],
               'format': feat.get('format'), 'length_bucket': feat.get('length_bucket'),
               'weekday': feat.get('weekday'), 'source': feat.get('source'), 'tempo': feat.get('tempo') or {}}
        row.update({key: ('yes' if value else 'no') for key, value in (feat.get('ctas') or {}).items() if key != 'cta_count'})
        row.update({key: label_value(value, key) for key, value in first['labels'].items()})
        out.append(row)
    if not out:
        return None
    keys = sorted({key for r in rows for key in r['labels']}) + ['length_bucket', 'weekday', 'source']
    promoted = [r for r in out if r['band'] == 'outlier']
    return {'ideas': len(out), 'promoted': len(promoted), 'rate': len(promoted) / len(out),
            'too_new': too_new, 'main_tier_only': direct, 'new_days': new_days,
            'lifts': {key: lift_table(out, key, min_n) for key in keys},
            'tempo': tempo_analysis(out),
            'promoted_examples': [{'post_id': r['post_id'], 'trials': r['trials'], 'hook_text': r['hook_text']}
                                  for r in promoted[:10]],
            'stuck_examples': [{'post_id': r['post_id'], 'trials': r['trials'], 'hook_text': r['hook_text']}
                               for r in out if r['band'] != 'outlier'][:10]}


def label_value(label, key):
    if key == 'specificity':
        return label.get('level', 'unclear')
    if key == 'payoff_delivered':
        return 'yes' if label.get('flag') else 'no'
    return label.get('value', 'unclear')


def value_buckets(pairs):
    """Low / mid / high by VALUE cut points, never by position in a sorted list: tied values always share
    a bucket, so a pile of zeros can never be split by outcome. With heavy ties you get fewer buckets."""
    values = sorted(p[0] for p in pairs)
    q1, q2 = values[len(values) // 3], values[(2 * len(values)) // 3]
    edges = [('low', lambda v: v <= q1), ('mid', lambda v: q1 < v <= q2), ('high', lambda v: v > q2)]
    if q1 == q2:
        edges = [('low', lambda v: v <= q1), ('high', lambda v: v > q1)]
    out = []
    for name, inside in edges:
        chunk = [p for p in pairs if inside(p[0])]
        if chunk:
            out.append({'label': name, 'min': min(c[0] for c in chunk), 'max': max(c[0] for c in chunk),
                        'n': len(chunk), 'outlier_rate': sum(c[2] == 'outlier' for c in chunk) / len(chunk)})
    return out


def tempo_analysis(rows):
    keys = sorted({key for row in rows for key, value in row['tempo'].items()
                   if isinstance(value, (int, float)) and not isinstance(value, bool)})
    result = {}
    for key in keys:
        pairs = [(r['tempo'][key], r['multiple'], r['band']) for r in rows
                 if isinstance(r['tempo'].get(key), (int, float)) and not isinstance(r['tempo'][key], bool)
                 and isinstance(r.get('multiple'), (int, float))]
        if len(pairs) < 5:
            continue
        terciles = value_buckets(pairs)
        result[key] = {'spearman': spearman([p[0] for p in pairs], [p[1] for p in pairs]),
                       **{f'median_{band}': statistics.median(p[0] for p in pairs if p[2] == band)
                          if any(p[2] == band for p in pairs) else None for band in ('outlier', 'normal', 'dud')},
                       'terciles': terciles}
    return result


def sentence_analysis(rows, min_n):
    outlier_rows = [r for r in rows if r['band'] == 'outlier']
    other_rows = [r for r in rows if r['band'] != 'outlier']
    sequences = {}
    grams = {}
    for row in rows:
        seq = tuple(collapse_roles([s.get('role', {}).get('value') for s in row['sentence_labels']]))
        sequences[row['post_id']] = seq
        grams[row['post_id']] = {seq[i:i + size] for size in (2, 3) for i in range(len(seq) - size + 1)}
    candidates = set().union(*grams.values()) if grams else set()
    ngrams = []
    for gram in candidates:
        a = sum(gram in grams[r['post_id']] for r in outlier_rows)
        b = sum(gram in grams[r['post_id']] for r in other_rows)
        if a + b < min_n:
            continue
        ngrams.append({'sequence': list(gram), 'outlier_share': a / len(outlier_rows) if outlier_rows else 0,
                       'other_share': b / len(other_rows) if other_rows else 0,
                       'lift': ((a + 1) / (len(outlier_rows) + 2)) / ((b + 1) / (len(other_rows) + 2)),
                       'support': a + b})
    ngrams.sort(key=lambda r: (-r['lift'], -r['support'], r['sequence']))
    mixes = {}
    for field in ('role', 'device'):
        by_band = {}
        for band in ('outlier', 'normal', 'dud'):
            group = [r for r in rows if r['band'] == band and r['sentence_labels']]
            values = {s.get(field, {}).get('value') for r in group for s in r['sentence_labels']}
            by_band[band] = {value: statistics.mean(sum(s.get(field, {}).get('value') == value for s in r['sentence_labels']) /
                                               len(r['sentence_labels']) for r in group)
                             for value in sorted(values) if value}
        mixes[f'{field}_mix'] = by_band
    timing = {}
    for band in ('outlier', 'normal', 'dud'):
        timing[band] = {}
        for role in ('claim', 'evidence', 'payoff', 'cta'):
            values = []
            for row in rows:
                if row['band'] != band:
                    continue
                for i, sentence in enumerate(row['sentence_labels']):
                    if sentence.get('role', {}).get('value') == role:
                        feat_sent = row['sentences']
                        if row['source'] == 'transcript' and i < len(feat_sent) and feat_sent[i].get('start_s') is not None:
                            values.append(feat_sent[i]['start_s'])
                        elif len(row['sentence_labels']) > 1:
                            values.append(i / (len(row['sentence_labels']) - 1))
                        break
            timing[band][role] = statistics.median(values) if values else None
    top = Counter(sequences[r['post_id']] for r in outlier_rows if sequences[r['post_id']])
    return {'ngrams': ngrams, **mixes, 'timing': timing,
            'sequences': [{'sequence': list(seq), 'count': count} for seq, count in top.most_common(10)]}


def run(work: Path, *, min_n=5) -> dict:
    work = Path(work)
    source = read_json(work / 'posts.json')
    features = read_json(work / 'features.json')
    outliers = read_json(work / 'outliers.json')
    labels = read_json(work / 'labels.json')
    rows = []
    for post in source['posts']:
        post_id = str(post['post_id'])
        band_row = outliers.get('posts', {}).get(post_id, {})
        if band_row.get('band') not in ('outlier', 'normal', 'dud') or post_id not in labels.get('posts', {}):
            continue
        feat = features.get(post_id, {})
        row = {'post_id': post_id, 'band': band_row['band'], 'multiple': band_row.get('multiple'),
               'url': post.get('url'), 'format': feat.get('format', post.get('format')),
               'length_bucket': feat.get('length_bucket'), 'weekday': feat.get('weekday'),
               'source': feat.get('source'), 'tempo': feat.get('tempo') or {},
               'sentences': feat.get('sentences') or [], 'sentence_labels': labels.get('sentences', {}).get(post_id, []),
               'hook_text': feat.get('segments', {}).get('hook_text', ''), 'labels': labels['posts'][post_id]}
        row['ctas'] = feat.get('ctas') or {}
        row.update({key: ('yes' if value else 'no') for key, value in row['ctas'].items() if key != 'cta_count'})
        row.update({key: label_value(value, key) for key, value in labels['posts'][post_id].items()})
        rows.append(row)
    assign_ideas(rows)
    n_out = sum(r['band'] == 'outlier' for r in rows)
    keys = sorted({key for r in rows for key in r['labels']})
    cta_keys = sorted({key for r in rows for key in r['ctas'] if key != 'cta_count'})
    lifts = {key: lift_table(rows, key, min_n)
             for key in keys + ['format', 'length_bucket', 'weekday', 'source'] + cta_keys}
    add_outside_top_shape(rows, lifts, min_n)
    repeats = [{'idea': idea, 'posts': len(group), 'bands': Counter(r['band'] for r in group),
                'post_ids': [r['post_id'] for r in group]}
               for idea, group in ((i, [r for r in rows if r['idea'] == i]) for i in {r['idea'] for r in rows})
               if len(group) > 1]
    repeats.sort(key=lambda r: -r['posts'])
    combos = {}
    for left, right in (('hook_type', 'structure'), ('structure', 'ending')):
        key = f'{left} x {right}'
        combo_rows = [{**r, key: f'{r.get(left, "unclear")} x {r.get(right, "unclear")}'} for r in rows]
        combos[key] = [entry for entry in lift_table(combo_rows, key, min_n) if entry['n'] >= min_n]
    def top_row(row):
        return {key: row[key] for key in ('post_id', 'url', 'band', 'multiple', 'format', 'hook_text')} | {
            'labels': {key: label_value(value, key) for key, value in row['labels'].items()}}
    payload = {'overall': {'n': len(rows), 'outliers': n_out,
                           'duds': sum(r['band'] == 'dud' for r in rows),
                           'outlier_rate': n_out / len(rows) if rows else 0,
                           'metric': outliers.get('metric'), 'baseline': outliers.get('baseline')},
               'lifts': lifts, 'combos': combos, 'repeats': repeats, 'tempo': tempo_analysis(rows),
               'tiers': outliers.get('tiers'),
               'graduation': graduation(source, features, outliers, labels, min_n, None) if outliers.get('tiers') else None,
               'sentences': sentence_analysis(rows, min_n),
               'top_outliers': [top_row(r) for r in sorted((r for r in rows if r['band'] == 'outlier'),
                                                           key=lambda r: r['multiple'] or 0, reverse=True)[:10]],
               'top_duds': [top_row(r) for r in sorted((r for r in rows if r['band'] == 'dud'),
                                                       key=lambda r: r['multiple'] or 0)[:5]]}
    write_json(work / 'patterns.json', payload)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--min-n', type=int, default=5)
    args = parser.parse_args()
    result = run(args.work, min_n=args.min_n)
    print(f"{result['overall']['n']} labelled posts, {result['overall']['outliers']} outliers")
    for key, table in result['lifts'].items():
        print(f"{key}: " + ', '.join(f"{r['value']} {r['lift']:.2f}x" for r in table[:5] if r['lift'] is not None))
    for key, row in result['tempo'].items():
        print(f"{key}: spearman {row['spearman']}")
    grad = result.get('graduation')
    if grad:
        print(f"graduation: {grad['promoted']} of {grad['ideas']} trial ideas promoted ({grad['rate']:.0%}), "
              f"{grad['too_new']} too new, {grad['main_tier_only']} main-tier only")


if __name__ == '__main__':
    main()

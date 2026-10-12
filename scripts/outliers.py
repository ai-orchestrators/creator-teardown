#!/usr/bin/env python3
"""Find post outliers against nearby mature posts."""
from __future__ import annotations

import argparse
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from common import read_json, write_json


def date(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc) if value else None
    except (TypeError, ValueError):
        return None


def pick_metric(posts: list[dict]) -> str:
    return 'views' if posts and sum((p.get('metrics') or {}).get('views') is not None and
                                    (p.get('metrics') or {}).get('views') > 0 for p in posts) / len(posts) >= 0.8 else 'likes'


def secondary_metric(posts: list[dict]) -> str | None:
    return 'shares' if posts and sum((p.get('metrics') or {}).get('shares') is not None for p in posts) / len(posts) >= 0.8 else None


def classify_band(multiple, sec_multiple, age_h, hi, lo, min_age):
    if age_h is not None and age_h < min_age:
        return 'climbing'
    if (multiple is not None and multiple >= hi) or (sec_multiple is not None and sec_multiple >= 2):
        return 'outlier'
    if multiple is not None and multiple <= lo:
        return 'dud'
    return 'normal'


def baseline(post, pool, metric, k):
    peers = [p for p in pool if p is not post and (p.get('metrics') or {}).get(metric) is not None]
    target_date = date(post.get('posted_at'))
    if len(peers) >= 10 and target_date and all(date(p.get('posted_at')) for p in peers):
        peers.sort(key=lambda p: abs((date(p['posted_at']) - target_date).total_seconds()))
        peers = peers[:k]
    return statistics.median(p['metrics'][metric] for p in peers) if peers else None


def split_tiers(values, min_share=0.1, min_gap=1.0, min_separation=0.75):
    """Find two distribution tiers (e.g. trial reels vs main-feed reels) by 2-means on log10.

    Returns the cut value, or None when the account is one population. A split needs both tiers
    to hold 10%+ of posts, cluster medians at least 10x apart, and most of the spread between tiers.
    """
    logs = sorted(math.log10(v) for v in values if v and v > 0)
    if len(logs) < 20:
        return None
    lo_c, hi_c = logs[0], logs[-1]
    for _ in range(50):
        low = [x for x in logs if abs(x - lo_c) <= abs(x - hi_c)]
        high = [x for x in logs if abs(x - lo_c) > abs(x - hi_c)]
        if not low or not high:
            return None
        new_lo, new_hi = statistics.mean(low), statistics.mean(high)
        if (new_lo, new_hi) == (lo_c, hi_c):
            break
        lo_c, hi_c = new_lo, new_hi
    share = min(len(low), len(high)) / len(logs)
    gap = statistics.median(high) - statistics.median(low)
    total = sum((x - statistics.mean(logs)) ** 2 for x in logs)
    within = sum((x - lo_c) ** 2 for x in low) + sum((x - hi_c) ** 2 for x in high)
    separation = 1 - within / total if total else 0
    if share < min_share or gap < min_gap or separation < min_separation:
        return None
    return 10 ** ((max(low) + min(high)) / 2)


def run(work: Path, *, formats=None, hi=1.5, lo=0.5, min_age_hours=72, k=30, now=None, tiers=True, tier_by='auto') -> dict:
    work = Path(work)
    source = read_json(work / 'posts.json')
    posts = source['posts']
    judged = [p for p in posts if formats is None or p.get('format') in formats]
    metric, secondary = pick_metric(judged), secondary_metric(judged)
    moment = date(now) if isinstance(now, str) else now
    moment = moment or date(source.get('pulled_at')) or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    ages = {str(p['post_id']): (moment - date(p.get('posted_at'))).total_seconds() / 3600
            if date(p.get('posted_at')) else None for p in posts}
    eligible = [p for p in posts if (formats is None or p.get('format') in formats) and
                (p.get('metrics') or {}).get(metric) is not None]
    mature = [p for p in eligible if ages[str(p['post_id'])] is None or ages[str(p['post_id'])] >= min_age_hours]
    secondary_pool = [p for p in mature if secondary and (p.get('metrics') or {}).get(secondary) is not None]
    platform = (source.get('platform') or '').lower()
    kinds = {p.get('format') for p in eligible}
    by_format = tiers and (tier_by == 'format' or (
        tier_by == 'auto' and platform == 'youtube' and {'short', 'video'} <= kinds
        and min(sum(p.get('format') == f for p in eligible) for f in ('short', 'video')) >= 5))
    cut = None if by_format else (split_tiers([p['metrics'][metric] for p in eligible]) if tiers else None)
    if by_format:  # YouTube Shorts and long videos are different products: each is judged against its own kind
        tier_of = lambda p: 'high' if p.get('format') == 'video' else 'low'
        tier_kind, tier_names = 'format', {'low': 'Shorts', 'high': 'long videos'}
    elif cut:
        tier_of = lambda p: ('high' if p['metrics'][metric] >= cut else 'low')
        tier_kind, tier_names = 'reach', {'low': 'test reels' if platform == 'instagram' else 'test posts', 'high': 'main feed'}
    else:
        tier_of, tier_kind, tier_names = (lambda p: None), None, None
    result, counts = {}, {}
    for post in posts:
        post_id = str(post['post_id'])
        value = (post.get('metrics') or {}).get(metric)
        sec_value = (post.get('metrics') or {}).get(secondary) if secondary else None
        age = ages[post_id]
        if formats is not None and post.get('format') not in formats:
            band = 'excluded'
        elif value is None:
            band = 'no_metric'
        else:
            band = None
        tier = tier_of(post) if band is None else None
        same = (lambda pool: [p for p in pool if tier_of(p) == tier]) if tier else (lambda pool: pool)
        base = baseline(post, same(mature), metric, k) if band is None else None
        sec_base = (baseline(post, same(secondary_pool), secondary, k)
                    if band is None and secondary and sec_value is not None else None)
        multiple = value / base if value is not None and base else None
        sec_multiple = sec_value / sec_base if sec_value is not None and sec_base else None
        band = band or classify_band(multiple, sec_multiple, age, hi, lo, min_age_hours)
        result[post_id] = {'value': value, 'secondary_value': sec_value, 'baseline': base,
                           'multiple': multiple, 'secondary_multiple': sec_multiple,
                           'band': band, 'age_h': age, 'tier': tier}
        counts[band] = counts.get(band, 0) + 1
    global_median = statistics.median(p['metrics'][metric] for p in mature) if mature else None
    payload = {'metric': metric, 'secondary_metric': secondary, 'hi': hi, 'lo': lo,
               'min_age_hours': min_age_hours, 'now': moment.isoformat(),
               'baseline': {'global_median': global_median, 'method': 'rolling_nearest_mature', 'k': k},
               'counts': counts, 'posts': result,
               'tiers': ({'kind': tier_kind, 'names': tier_names, 'cut': cut, **{name: {'n': len(group), 'median': statistics.median(group) if group else None}
                                         for name, group in (('low', [p['metrics'][metric] for p in eligible if tier_of(p) == 'low']),
                                                             ('high', [p['metrics'][metric] for p in eligible if tier_of(p) == 'high']))}}
                         if tier_kind else None)}
    write_json(work / 'outliers.json', payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--formats')
    parser.add_argument('--hi', type=float, default=1.5)
    parser.add_argument('--lo', type=float, default=0.5)
    parser.add_argument('--min-age-hours', type=float, default=72)
    parser.add_argument('--no-tiers', action='store_true', help='judge every post against one baseline')
    parser.add_argument('--tier-by', choices=('auto', 'reach', 'format'), default='auto',
                        help='auto: YouTube Shorts vs long videos by format, everything else by a reach split')
    args = parser.parse_args()
    result = run(args.work, formats=set(args.formats.split(',')) if args.formats else None,
                 hi=args.hi, lo=args.lo, min_age_hours=args.min_age_hours,
                 tiers=not args.no_tiers, tier_by=args.tier_by)
    print(' '.join(f'{band}: {n}' for band, n in result['counts'].items()))
    if result['tiers']:
        t = result['tiers']
        split = f"split at {t['cut']:,.0f}" if t.get('cut') else 'split by format'
        print(f"two tiers {split}: {t['names']['low']} n {t['low']['n']} (median {t['low']['median'] or 0:,.0f}), "
              f"{t['names']['high']} n {t['high']['n']} (median {t['high']['median'] or 0:,.0f}). Each post is judged against its own tier.")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Label every post and every sentence with Jev, using the forms in decisions/.

A label under 0.5 confidence becomes 'unclear' and never counts toward a pattern. Reruns only
pay for posts whose text changed. --dry-run prints the call count and cost without a key.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

import jev_client
from common import ConfigError, DECISIONS_DIR, load_settings, read_json, write_json


class SetupError(Exception):
    pass


class CostCapExceeded(Exception):
    pass


def redact(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[email]', value)
    value = re.sub(r'https?://\S+', '[link]', value)
    value = re.sub(r'(?<!\w)(?:\+?\d[\d\s()\-]{6,}\d)(?!\w)',
                   lambda match: '[phone]' if len(re.findall(r'\d', match.group())) >= 8 else match.group(), value)
    return value


def decision(name):
    return read_json(DECISIONS_DIR / f'{name}.json')


def build_post_state(feat: dict) -> dict:
    fields = decision('creator.post.v1')['state_fields']
    flat = {**feat, **feat.get('segments', {})}
    return {field: redact(flat.get(field) or '') for field in fields}


def post_questions(decision_data, topics):
    questions = copy.deepcopy(decision_data['questions'])
    fallback = questions['topic']['criteria']
    questions['topic']['criteria'] = {**topics, 'other': fallback['other'], 'cannot_tell': fallback['cannot_tell']}
    return questions


def sentence_state(sentences, i):
    return {key: redact(value) for key, value in {
        'position': sentences[i].get('position') or '',
        'sentence': sentences[i].get('text') or '',
        'previous_sentence': sentences[i - 1].get('text') or '' if i else '',
        'next_sentence': sentences[i + 1].get('text') or '' if i + 1 < len(sentences) else ''}.items()}


def normalise_answer(ans):
    kind = ans['type'] if isinstance(ans, dict) else ans.type
    get = ans.get if isinstance(ans, dict) else lambda key, default=None: getattr(ans, key, default)
    confidence = get('confidence', 0)
    if kind == 'choice':
        choice = get('choice')
        return {'value': choice if confidence >= 0.5 else 'unclear', 'raw': choice,
                'confidence': confidence, 'probabilities': get('probabilities', {})}
    if kind == 'score':
        score = get('score')
        return {'value': score, 'level': round(score) if confidence >= 0.5 else 'unclear',
                'confidence': confidence}
    probability = get('noul')
    return {'value': probability, 'flag': probability >= 0.5}


def fingerprint(state, version):
    data = json.dumps(state, sort_keys=True, ensure_ascii=False) + str(version)
    return hashlib.sha256(data.encode()).hexdigest()


def run(work: Path, *, jev, dry_run=False, workers=8, max_usd=1.0, skip_sentences=False) -> dict:
    work = Path(work)
    for name in ('topics.json', 'features.json'):
        if not (work / name).exists():
            raise SetupError(f'Create {name} in {work} before classifying.')
    feats = read_json(work / 'features.json')
    topics = read_json(work / 'topics.json').get('topics', {})
    post_decision, sent_decision = decision('creator.post.v1'), decision('creator.sentence.v1')
    post_q = post_questions(post_decision, topics)
    sent_q = sent_decision['questions']
    old = read_json(work / 'labels.json') if (work / 'labels.json').exists() else {}
    output = {'model': post_decision['model'], 'decisions': {post_decision['id']: post_decision['version'],
              sent_decision['id']: sent_decision['version']}, 'posts': copy.deepcopy(old.get('posts', {})),
              'sentences': copy.deepcopy(old.get('sentences', {})), 'hashes': copy.deepcopy(old.get('hashes', {})),
              'calls': old.get('calls', 0), 'cost_usd': old.get('cost_usd', 0.0), 'errors': []}
    calls_before = output['calls']
    plans = {'post': [], 'sentence': []}
    cached = 0
    for post_id, feat in feats.items():
        if feat.get('error'):
            output['errors'].append({'post_id': post_id, 'error': feat['error']})
            continue
        state = build_post_state(feat)
        key = f'post:{post_id}'
        digest = fingerprint(state, post_decision['version'])
        if output['hashes'].get(key) == digest and post_id in output['posts']:
            cached += 1
        else:
            plans['post'].append((post_id, None, state, key, digest))
        if skip_sentences:
            continue
        sentences = feat.get('sentences', [])
        for i in range(len(sentences)):
            state = sentence_state(sentences, i)
            key = f'sentence:{post_id}:{i}'
            digest = fingerprint(state, sent_decision['version'])
            if output['hashes'].get(key) == digest and len(output['sentences'].get(post_id, [])) > i:
                cached += 1
            else:
                plans['sentence'].append((post_id, i, state, key, digest))
    estimate = sum(jev.estimate_tokens(item[2], post_q if group == 'post' else sent_q)
                   for group, items in plans.items() for item in items) * jev.PRICE_PER_INPUT_TOKEN_USD
    if estimate > max_usd:
        raise CostCapExceeded(f'Estimated cost ${estimate:.4f} exceeds cap ${max_usd:.4f}.')
    if dry_run:
        return {'post_calls': len(plans['post']), 'sentence_calls': len(plans['sentence']),
                'cached': cached, 'est_usd': estimate}
    has_key = getattr(jev, 'has_key', None)
    if any(plans.values()) and callable(has_key) and not has_key():
        raise SetupError('TYPESAFE_API_KEY is not set. Export it, or add it to config/.env (see SETUP.md).')
    for group, dec, questions in (('post', post_decision, post_q), ('sentence', sent_decision, sent_q)):
        items = plans[group]
        if not items:
            continue
        try:
            responses = jev.decide_many([item[2] for item in items], questions, workers=workers,
                                        decision_id=dec['id'], model=dec['model'])
        except Exception as exc:
            if isinstance(exc, getattr(jev, 'JevDisabled', ())):
                raise SetupError(f'Jev kill switch is active: {exc}') from exc
            raise
        for item, response in zip(items, responses):
            post_id, i, _, key, digest = item
            output['calls'] += 1
            if isinstance(response, Exception):
                if isinstance(response, getattr(jev, 'JevDisabled', ())):
                    raise SetupError(f'Jev kill switch is active: {response}') from response
                output['errors'].append({'post_id': post_id, **({'i': i} if i is not None else {}), 'error': str(response)})
                continue
            try:
                answers = {qid: normalise_answer(ans) for qid, ans in response.answers.items()}
                if group == 'post':
                    output['posts'][post_id] = answers
                else:
                    rows = output['sentences'].setdefault(post_id, [])
                    while len(rows) <= i:
                        rows.append({})
                    rows[i] = {'i': i, **answers}
                output['hashes'][key] = digest
                usage = response.usage or {}
                output['cost_usd'] += usage.get('cost', usage.get('input_tokens', 0) * jev.PRICE_PER_INPUT_TOKEN_USD)
            except Exception as exc:
                output['errors'].append({'post_id': post_id, **({'i': i} if i is not None else {}), 'error': str(exc)})
    output['run_calls'] = output['calls'] - calls_before
    write_json(work / 'labels.json', output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description='Label posts and sentences with Jev.')
    parser.add_argument('--work', type=Path, required=True, help='the run .work folder')
    parser.add_argument('--dry-run', action='store_true', help='count calls and estimate cost; no key needed')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--max-usd', type=float, help='hard cost cap in US$ (default: jev_max_usd in settings)')
    parser.add_argument('--skip-sentences', action='store_true')
    args = parser.parse_args()
    try:
        max_usd = args.max_usd if args.max_usd is not None else load_settings()['jev_max_usd']
        result = run(args.work, jev=jev_client, dry_run=args.dry_run, workers=args.workers,
                     max_usd=max_usd, skip_sentences=args.skip_sentences)
    except (SetupError, CostCapExceeded, ConfigError) as exc:
        print(f'ERROR: {exc}')
        return 2
    if args.dry_run:
        print(f"{result['post_calls']} post calls, {result['sentence_calls']} sentence calls, "
              f"{result['cached']} cached, about US${result['est_usd']:.4f} (cap US${max_usd:.2f})")
        print(f"TYPESAFE_API_KEY: {'set' if jev_client.has_key() else 'missing (needed for the real run)'}")
        return 0
    run_calls = result.get('run_calls', 0)
    print(f"{run_calls} calls this run, {len(result['errors'])} errors, total cost US${result['cost_usd']:.4f}")
    return 2 if run_calls and len(result['errors']) / run_calls > 0.1 else 0


if __name__ == '__main__':
    raise SystemExit(main())

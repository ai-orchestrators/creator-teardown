#!/usr/bin/env python3
"""Measure text, timing and pace for every post."""
from __future__ import annotations

import argparse
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from common import VIDEO_FORMATS, read_json, write_json

def count_words(text: str) -> int:
    return sum(bool(re.search(r'[^\W_]', token, re.UNICODE)) for token in text.split())


LIST_MARKER = re.compile(r'^\(?\d{1,3}[.)]$')
ABBREV_END = re.compile(r'(?:\b(?:[A-Z]\.){2,}|\b(?:Mr|Mrs|Ms|Dr|St|vs|etc)\.)$')  # "U.S.", "Dr.": not a sentence end


def split_sentences(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        pending = ''
        for part in re.split(r'(?<!P\.S\.)(?<![A-Z]\.[A-Z]\.)(?<!\bMr\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\bvs\.)(?<!Mrs\.)(?<=[.!?…])\s+', line.strip()):
            part = part.strip()
            if LIST_MARKER.match(part):
                pending = part  # "1." on its own is a list number: keep it with its item
                continue
            if re.search(r'[^\W_]', part, re.UNICODE):
                result.append(f'{pending} {part}'.strip())
                pending = ''
    return result


def sentences_from_captions(captions: list[dict]) -> list[dict]:
    result, open_tokens = [], []

    def close():
        if open_tokens:
            first, last = open_tokens[0], open_tokens[-1]
            # Whisper tokens carry their own leading space, so "'s" and "," glue to the word before.
            text = re.sub(r'^[-\u2013\s]+', '', ''.join(t['text'] for t in open_tokens)).strip()
            # Whisper tags like (upbeat music) or [Music] arrive split over several tokens: drop them here.
            text = re.sub(r'\s*[\[(][^\])]{0,40}[\])]', '', text).strip()
            if not re.search(r'[^\W_]', text):
                open_tokens.clear()
                return
            result.append({'text': re.sub(r'\s+', ' ', text), 'start_s': round(first['startMs'] / 1000, 3),
                           'end_s': round(last['endMs'] / 1000, 3), 'words': count_words(text)})
            open_tokens.clear()

    previous, number_hold, letter_hold = None, False, False
    for token in captions:
        if not token.get('text', '').strip() or re.fullmatch(r'\s*[\[(][^\])]*[\])]\s*', token['text']):
            continue  # blank tokens and whisper tags like [Music] or (upbeat music)
        if number_hold:
            number_hold = False
            if not re.match(r'\d', token['text']):
                close()  # "1." really did end the sentence
        if letter_hold:
            letter_hold = False
            if not re.match(r'\s*[A-Z]\.', token['text']):
                close()  # a lone "A." ended the sentence after all
        if previous and open_tokens and token.get('startMs', 0) - previous.get('endMs', 0) >= 1000 and count_words(' '.join(t['text'] for t in open_tokens)) >= 3:
            close()
        open_tokens.append(token)
        if token['text'].strip().endswith(('.', '!', '?')):
            if re.search(r'\d\.$', token['text'].strip()):
                number_hold = True  # "1." may be the start of "1.2 million": decide on the next token
            elif re.fullmatch(r'[A-Z]\.', token['text'].strip()):
                letter_hold = True  # "L." may be the start of "L. A.": decide on the next token
            elif not ABBREV_END.search(''.join(t['text'] for t in open_tokens).strip()):
                close()
        previous = token
    close()
    return result


def tag_positions(sentences: list[dict], duration_s=None) -> list[dict]:
    n = len(sentences)
    if not n:
        return []
    timed = all(s.get('start_s') is not None for s in sentences)
    speech_end = sentences[-1].get('end_s') or duration_s or 0 if timed else 0
    out = []
    for i, sentence in enumerate(sentences):
        if timed:
            start = sentence['start_s']
            if i == 0 or start < 3:
                position = 'hook'
            elif i == n - 1 or start >= 0.85 * speech_end:
                position = 'ending'
            elif start < 0.25 * speech_end:
                position = 'opening'
            else:
                position = 'body'
        elif i == 0:
            position = 'hook'
        elif i >= n - (2 if n >= 10 else 1):
            position = 'ending'
        elif i < max(2, math.ceil(0.2 * n)):
            position = 'opening'
        else:
            position = 'body'
        out.append({**sentence, 'i': i, 'position': position})
    return out


CTA_PATTERNS = {
    'cta_share': r'\b(repost|reshare|share this|share it|save this|save it|bookmark)\b|♻',
    'cta_follow': r'\b(follow|subscribe|turn on notifications|hit the bell)\b',
    'cta_comment_keyword': r'\b(?i:comment)\s+(?i:the word\s+)?["“\']?[A-Z][A-Z0-9]{1,}\b',
    'cta_link': r'https?://|lnkd\.in|\blink in (the )?(first )?(comment|bio)\b|\bfirst comment\b',
}


def detect_ctas(caption: str, ending_text: str) -> dict:
    """Standard asks, by regex over the caption tail and the spoken ending. Never a Jev question."""
    tail = caption[-500:] + '\n' + (ending_text or '')
    found = {key: bool(re.search(pattern, tail, re.IGNORECASE if key != 'cta_comment_keyword' else 0))
             for key, pattern in CTA_PATTERNS.items()}
    last_lines = [line.strip() for line in tail.splitlines() if line.strip()][-3:]
    found['cta_question'] = any(line.endswith('?') for line in last_lines)
    found['cta_count'] = sum(found[key] for key in CTA_PATTERNS)
    return found


def build_features(post: dict, media_entry: dict | None, transcript: dict | None) -> dict:
    caption = post.get('caption') or ''
    captions = (transcript or {}).get('captions') or []
    spoken = sentences_from_captions(captions)
    source = 'transcript' if sum(s['words'] for s in spoken) >= 8 else 'caption'
    sentences = tag_positions(spoken if source == 'transcript' else
                              [{'text': t, 'words': count_words(t)} for t in split_sentences(caption)],
                              (media_entry or {}).get('duration_s'))
    duration = (media_entry or {}).get('duration_s')
    if duration is None:
        duration = post.get('duration_s')
    if post.get('format') in VIDEO_FORMATS and duration is not None:
        length_bucket = ('under_15s' if duration < 15 else '15_to_30s' if duration < 30 else
                         '30_to_60s' if duration < 60 else '60_to_90s' if duration < 90 else 'over_90s')
    else:
        length_bucket = 'short' if len(caption) < 500 else 'medium' if len(caption) < 1300 else 'long'
    try:
        posted = datetime.fromisoformat(post['posted_at'].replace('Z', '+00:00'))
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        posted = posted.astimezone(timezone.utc)
        weekday, hour = posted.strftime('%a'), posted.hour
    except (TypeError, ValueError, KeyError):
        weekday, hour = None, None
    segments = {f'{position}_text': ' '.join(s['text'] for s in sentences if s['position'] == position)
                for position in ('hook', 'opening', 'body', 'ending')}
    segments['body_text'] = segments['body_text'][:4000]
    words = sum(s['words'] for s in sentences)
    speech_minutes = ((sentences[-1]['end_s'] - sentences[0]['start_s']) / 60
                      if source == 'transcript' and sentences else None)
    cuts = (media_entry or {}).get('cuts')
    hook = [s for s in sentences if s['position'] == 'hook']
    tempo = {'duration_s': duration, 'words': words, 'sentences': len(sentences),
             'wpm': words / speech_minutes if speech_minutes else None,
             'sentences_per_min': len(sentences) / speech_minutes if speech_minutes else None,
             'avg_sentence_words': words / len(sentences) if sentences else None,
             'hook_words': sum(s['words'] for s in hook),
             'hook_seconds': hook[-1]['end_s'] if hook and source == 'transcript' else None,
             'cuts': cuts, 'cuts_per_min': cuts / (duration / 60) if cuts is not None and duration else None,
             'chars': len(caption), 'lines': len(caption.splitlines()), 'arrows': caption.count('→'),
             'has_ps': bool(re.search(r'(?im)^\s*P\.?S\.?\b', caption)),
             'hashtags': len(re.findall(r'#\w+', caption)), 'has_link': bool(re.search(r'https?://', caption))}
    return {'post_id': post['post_id'], 'platform': post.get('platform'), 'format': post.get('format'),
            'posted_at': post.get('posted_at'), 'weekday': weekday, 'hour_utc': hour, 'source': source,
            'sentences': sentences, 'segments': segments, 'caption_head': caption[:300],
            'length_bucket': length_bucket, 'tempo': tempo,
            'ctas': detect_ctas(caption, segments['ending_text'])}


def run(work: Path) -> dict:
    work = Path(work)
    media = read_json(work / 'media.json') if (work / 'media.json').exists() else {}
    result = {}
    for post in read_json(work / 'posts.json')['posts']:
        post_id = str(post['post_id'])
        entry = media.get(post_id)
        transcript = None
        if entry and entry.get('transcript_path'):
            try:
                transcript = read_json(entry['transcript_path'])
            except (OSError, ValueError):
                pass
        try:
            result[post_id] = build_features(post, entry, transcript)
        except Exception as exc:
            result[post_id] = {'post_id': post_id, 'error': str(exc)}
    write_json(work / 'features.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.work)
    print(f'{len(result)} posts measured')


if __name__ == '__main__':
    main()

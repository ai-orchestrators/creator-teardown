#!/usr/bin/env python3
"""Download, probe and transcribe video posts.

Transcription runs locally with whisper.cpp (`whisper-cli`), set up by SETUP.md in
config/settings.json under `transcriber`. Nothing is uploaded. To use another tool, set
`transcriber.command` to an argv list with {input} and {output} placeholders; it must write
{"text": ..., "captions": [{"text", "startMs", "endMs"}]} to {output}.

YouTube: each video's own captions come first when the optional youtube-transcript-api package is
installed (free, punctuated); whisper covers any video without them. A long video is judged on its
opening, so only its first 4 minutes are downloaded and transcribed.

Resumable: rerun after a stop and finished posts are skipped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import re
import threading
import subprocess
import time
import urllib.request
from pathlib import Path

from common import ConfigError, VIDEO_FORMATS, load_settings, read_json, safe_id, write_json


def scene_cuts_from_ffmpeg(stderr: str) -> int:
    return sum('pts_time:' in line for line in stderr.splitlines() if 'showinfo' in line)


def is_stream(url: str | None) -> bool:
    """HLS playlists (LinkedIn video) need yt-dlp, not a plain download."""
    return bool(url) and ('.m3u8' in url or '/playlist/' in url)


INTRO_SECONDS = 240  # a long YouTube video is judged on its opening: title, thumbnail and the first 4 minutes


def is_long_youtube(post: dict) -> bool:
    return post.get('platform') == 'youtube' and (post.get('duration_s') or 0) > 180


def download_command(post: dict, dest_dir: Path) -> list[str] | None:
    media_url = post.get('media_url')
    if media_url and not is_stream(media_url):
        return None
    section = ['--download-sections', f'*0-{INTRO_SECONDS}'] if is_long_youtube(post) else []
    return ['yt-dlp', '--no-warnings', '-f', 'b/bv*+ba', '-S', 'res:720,vcodec:avc', '--no-playlist', *section, '-o', str(dest_dir / 'media.%(ext)s'),
            media_url or post['url']]


def captions_available() -> bool:
    """youtube-transcript-api is optional: with it, YouTube videos use their own captions before whisper."""
    return importlib.util.find_spec('youtube_transcript_api') is not None


CAPTION_PACE = threading.Semaphore(1)
CAPTIONS = {'blocked': False}  # YouTube blocks caption pulls from one IP after a burst: then every video goes to whisper


def youtube_captions(video_id: str, out_json: Path, max_start: float | None = None, attempts: int = 4) -> None:
    """YouTube's own captions, written in the same shape as a whisper transcript: word tokens with times.
    Captions are free and punctuated, so YouTube never needs whisper unless a video has none."""
    if CAPTIONS['blocked']:
        raise RuntimeError('captions blocked for this run')
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise RuntimeError('youtube-transcript-api is not installed (optional), so whisper transcribes instead') from None
    for attempt in range(attempts):
        try:
            with CAPTION_PACE:
                segments = list(YouTubeTranscriptApi().fetch(video_id, languages=['en', 'en-US', 'en-GB']))
                time.sleep(0.6)
            break
        except Exception as exc:
            text = str(exc) + type(exc).__name__
            if re.search(r'blocking requests|IpBlocked|RequestBlocked', text):
                CAPTIONS['blocked'] = True
                raise
            if attempt == attempts - 1 or not re.search(r'429|Too Many', text):
                raise
            time.sleep(10 * (attempt + 1))
    tokens = []
    for segment in segments:
        if max_start is not None and segment.start >= max_start:
            break
        words = re.sub(r'\s+', ' ', segment.text.replace('\n', ' ')).strip().split(' ')
        words = [w for w in words if w]
        if not words or re.fullmatch(r'\[[^\]]*\]', ' '.join(words)):
            continue
        step = max(segment.duration, 0.05) / len(words)
        for n, word in enumerate(words):
            start = segment.start + n * step
            tokens.append({'text': ' ' + word, 'startMs': round(start * 1000), 'endMs': round((start + step) * 1000)})
    if not tokens:
        raise RuntimeError('captions were empty')
    write_json(out_json, {'text': ''.join(t['text'] for t in tokens).strip(), 'captions': tokens, 'source': 'youtube_captions'})


def download(post: dict, dest_dir: Path) -> Path:
    if post.get('platform') == 'instagram' and not post.get('media_url'):
        # yt-dlp on Instagram needs a logged-in cookie, and this skill never uses one.
        raise RuntimeError('no media_url in the Apify item (Instagram never falls back to yt-dlp)')
    if post.get('media_url') and not is_stream(post['media_url']):
        request = urllib.request.Request(post['media_url'], headers={'User-Agent': 'Mozilla/5.0'})
        path = dest_dir / 'media.mp4'
        with urllib.request.urlopen(request, timeout=60) as response, path.open('wb') as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        return path
    result = subprocess.run(download_command(post, dest_dir), capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'yt-dlp failed')
    files = sorted(dest_dir.glob('media.*'))
    if not files:
        raise FileNotFoundError('yt-dlp produced no media file')
    return files[0]


def captions_from_whisper(data: dict) -> dict:
    """whisper.cpp full JSON (-ojf) to {text, captions}. One caption per word, times in ms.

    Special tokens such as [_BEG_] are dropped. A token with no leading space is part of the
    word before it (whisper splits long words), so it is glued back on.
    """
    captions = []
    for segment in data.get('transcription') or []:
        tokens = segment.get('tokens')
        if not tokens:
            tokens = [{'text': segment.get('text') or '', 'offsets': segment.get('offsets') or {}}]
        for token in tokens:
            text = token.get('text') or ''
            if not text.strip() or text.lstrip().startswith('[_'):
                continue
            offsets = token.get('offsets') or {}
            start, end = int(offsets.get('from') or 0), int(offsets.get('to') or 0)
            if captions and not text.startswith(' '):
                captions[-1]['text'] += text
                captions[-1]['endMs'] = max(captions[-1]['endMs'], end)
                continue
            captions.append({'text': text if text.startswith(' ') else ' ' + text, 'startMs': start, 'endMs': end,
                             'timestampMs': start, 'confidence': token.get('p')})
    return {'text': re.sub(r'\s+', ' ', ''.join(c['text'] for c in captions)).strip(), 'captions': captions}


def whisper_command(wav: Path, out_base: Path, transcriber: dict) -> list[str]:
    model = transcriber.get('model')
    if not model:
        raise ConfigError('No whisper model set. Run SETUP.md, or set transcriber.model in config/settings.json.')
    command = [transcriber.get('binary') or 'whisper-cli', '-m', str(Path(model).expanduser()), '-f', str(wav),
               '-ojf', '-of', str(out_base), '-np']
    if transcriber.get('language'):
        command += ['-l', str(transcriber['language'])]
    return command + [str(arg) for arg in transcriber.get('extra_args') or []]


def custom_command(path: Path, out_json: Path, transcriber: dict) -> list[str]:
    return [str(part).replace('{input}', str(path)).replace('{output}', str(out_json))
            for part in transcriber['command']]


def transcribe(path: Path, out_json: Path, timeout_s: float = 900, transcriber: dict | None = None) -> None:
    transcriber = transcriber or load_settings()['transcriber']
    path, out_json = Path(path), Path(out_json)
    if transcriber.get('command'):
        result = subprocess.run(custom_command(path, out_json, transcriber), capture_output=True, text=True,
                                timeout=timeout_s)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-500:] or 'transcription command failed')
        return
    wav = path.with_name(path.stem + '.whisper.wav')
    out_base = path.with_name('whisper')
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', str(path), '-ar', '16000', '-ac', '1',
                        '-c:a', 'pcm_s16le', str(wav)], capture_output=True, text=True, timeout=600, check=True)
        result = subprocess.run(whisper_command(wav, out_base, transcriber), capture_output=True, text=True,
                                timeout=timeout_s)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-500:] or 'whisper failed')
        raw = Path(str(out_base) + '.json')
        data = json.loads(raw.read_text(encoding='utf-8', errors='replace'))
        transcript = captions_from_whisper(data)
        if transcript['captions']:
            write_json(out_json, transcript)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'ffmpeg could not read the audio: {(exc.stderr or "")[-300:]}') from None
    finally:
        wav.unlink(missing_ok=True)
        Path(str(out_base) + '.json').unlink(missing_ok=True)


def probe(path: Path) -> tuple[float, int]:
    duration = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                               '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                              capture_output=True, text=True, timeout=60, check=True)
    scene = subprocess.run(['ffmpeg', '-nostdin', '-i', str(path), '-vf', "select='gt(scene,0.3)',showinfo",
                            '-an', '-f', 'null', '-'], capture_output=True, text=True, timeout=600)
    if scene.returncode:
        raise RuntimeError(scene.stderr[-500:] or 'scene probe failed')
    return float(duration.stdout.strip()), scene_cuts_from_ffmpeg(scene.stderr)


DONE = ('ok', 'no_speech', 'too_long')
WHISPER = threading.Semaphore(1)  # whisper.cpp runs on the GPU: parallel jobs only queue behind each other


def process(post: dict, dest: Path, downloader, transcriber, probe, keep_media: bool,
            max_seconds: float = 180) -> dict:
    """One video: download, measure, transcribe. Silent or overlong videos keep duration and cuts."""
    entry = {'status': None, 'duration_s': None, 'cuts': None, 'transcript_path': None,
             'media_path': None, 'error': None}
    dest.mkdir(parents=True, exist_ok=True)
    try:
        path = Path(downloader(post, dest))
        entry['media_path'] = str(path)
    except Exception as exc:
        entry.update(status='download_failed', error=str(exc))
        return entry
    try:
        entry['duration_s'], entry['cuts'] = probe(path)
    except Exception as exc:
        entry['error'] = str(exc)[-500:]
    duration = entry['duration_s']
    if post.get('platform') == 'youtube':
        transcript_path = dest / 'transcript.json'
        long_video = is_long_youtube(post)
        if long_video:
            entry['intro_only_s'] = INTRO_SECONDS  # cuts, pace and the script cover the opening, not the whole video
        try:
            youtube_captions(str(post['post_id']), transcript_path, INTRO_SECONDS if long_video else None)
            entry['transcript_path'] = str(transcript_path)
        except Exception as exc:
            entry['error'] = f'captions: {exc}'[:500]
            try:  # no captions: whisper the downloaded file (a Short, or the first 4 minutes of a long video)
                with WHISPER:
                    transcriber(path, transcript_path, **({'timeout_s': 900} if transcriber is transcribe else {}))
                if transcript_path.exists():
                    entry['transcript_path'] = str(transcript_path)
            except Exception as whisper_exc:
                entry['error'] += f' | whisper: {whisper_exc}'[:300]
        entry['status'] = ('ok' if duration is not None else 'probe_failed') if entry['transcript_path'] else \
            ('no_speech' if duration is not None else 'transcribe_failed')
    elif duration and duration > max_seconds:
        entry['status'] = 'too_long'  # a webinar or long video is not short-form: the caption stands in
    else:
        transcript_path = dest / 'transcript.json'
        extra = {'timeout_s': max(120, 4 * duration) if duration else 900} if transcriber is transcribe else {}
        try:
            with WHISPER:
                transcriber(path, transcript_path, **extra)
            if not transcript_path.exists():
                raise FileNotFoundError('transcriber produced no transcript')
            entry['transcript_path'] = str(transcript_path)
        except Exception as exc:
            entry['error'] = str(exc)[-500:]
        if entry['transcript_path']:
            entry['status'] = 'ok' if duration is not None else 'probe_failed'
        else:
            entry['status'] = 'no_speech' if duration is not None else 'transcribe_failed'
    if entry['status'] in DONE and not keep_media:
        # Keep the transcript, drop the video and the wav: they are large and not needed again.
        for leftover in list(dest.glob('media.*')):
            leftover.unlink(missing_ok=True)
        entry['media_path'] = None
    return entry


def run(work: Path, *, downloader=None, transcriber=None, probe=None, workers=2, limit=None,
        keep_media=False, max_seconds=180) -> dict:
    work = Path(work)
    posts = read_json(work / 'posts.json')['posts']
    if limit is not None:
        posts = posts[:limit]
    output = read_json(work / 'media.json') if (work / 'media.json').exists() else {}
    downloader, transcriber, probe = downloader or download, transcriber or transcribe, probe or globals()['probe']
    lock = threading.Lock()
    todo = []
    for post in posts:
        post_id = str(post['post_id'])
        if post.get('format') not in VIDEO_FORMATS:
            output[post_id] = {'status': 'text_only'}
            continue
        existing = output.get(post_id, {})
        if existing.get('status') in DONE and (existing['status'] in ('no_speech', 'too_long') or (
                existing.get('transcript_path') and Path(existing['transcript_path']).exists())):
            continue
        todo.append(post)

    def one(post):
        post_id = str(post['post_id'])
        entry = process(post, work / 'media' / safe_id(post_id), downloader, transcriber, probe, keep_media,
                        max_seconds)
        with lock:
            output[post_id] = entry
            write_json(work / 'media.json', output)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    write_json(work / 'media.json', output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description='Download, measure and transcribe every video post.')
    parser.add_argument('--work', type=Path, required=True, help='the run .work folder')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--keep-media', action='store_true', help='keep downloaded videos after transcribing')
    parser.add_argument('--max-seconds', type=float, default=180, help='longer videos are measured, not transcribed')
    args = parser.parse_args()
    try:
        transcriber = load_settings()['transcriber']
    except ConfigError as exc:
        parser.exit(2, f'ERROR: {exc}\n')
    if not transcriber.get('command') and not transcriber.get('model'):
        posts = args.work / 'posts.json'
        platform = read_json(posts).get('platform') if posts.exists() else None
        if platform != 'youtube' or not captions_available():
            parser.exit(2, 'ERROR: no whisper model set. Run SETUP.md, or set transcriber.model in config/settings.json.\n')
        print('No whisper model set: YouTube captions only. A video with no captions stays no_speech.')
    result = run(args.work, workers=args.workers, limit=args.limit, keep_media=args.keep_media,
                 max_seconds=args.max_seconds)
    counts = {status: sum(row['status'] == status for row in result.values()) for status in sorted({r['status'] for r in result.values()})}
    print(' '.join(f'{key}: {value}' for key, value in counts.items()))


if __name__ == '__main__':
    main()

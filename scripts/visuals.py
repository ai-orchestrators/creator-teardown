#!/usr/bin/env python3
"""Capture what each post looked like.

Every post gets a small thumbnail (for the 'every post in one picture' chart). The best and
worst posts also get their real images, carousel or document pages, and four frames from the
video. Everything is resized small and saved under .work/visuals/, never the full video.

Usage:
    python3 visuals.py --work WORK [--top 8] [--flops 3] [--ids id1,id2]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from common import read_json, safe_id, write_json

UA = {'User-Agent': 'Mozilla/5.0'}
THUMB_W, FULL_W, MAX_IMAGES = 120, 560, 6


def fetch(url: str, dest: Path, timeout: int = 60) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
        dest.write_bytes(response.read())
    return dest


def shrink(src: Path, dest: Path, width: int) -> Path:
    """Any image or video frame in, a small JPEG out."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', str(src), '-frames:v', '1',
                    '-vf', f"scale='min({width},iw)':-2", '-q:v', '6', str(dest)], check=True, timeout=60)
    return dest


def video_frames(video_url: str, out_dir: Path, count: int = 4) -> list[str]:
    """Download the video to a temp folder, keep `count` evenly spaced frames, drop the video."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if '.m3u8' in video_url or '/playlist/' in video_url:
            subprocess.run(['yt-dlp', '-q', '-f', 'b[height<=720]/b', '-o', str(tmp / 'v.%(ext)s'), video_url],
                           check=True, timeout=600)
            video = next(tmp.glob('v.*'))
        else:
            video = fetch(video_url, tmp / 'v.mp4', timeout=120)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                                'default=noprint_wrappers=1:nokey=1', str(video)], capture_output=True, text=True)
        duration = float(probe.stdout.strip() or 0)
        frames = []
        for i in range(count):
            at = duration * (0.08 + 0.84 * i / max(1, count - 1))
            frame = out_dir / f'frame_{i + 1}.jpg'
            out_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-ss', f'{at:.2f}', '-i', str(video),
                            '-frames:v', '1', '-vf', f"scale='min({FULL_W},iw)':-2", '-q:v', '6', str(frame)],
                           check=True, timeout=120)
            frames.append(frame)
        return [str(f) for f in frames if f.exists()]


# --------------------------------------------------------------------------- where each platform keeps media


def instagram_media(raw: list[dict]) -> dict[str, dict]:
    """Apify items already carry displayUrl, images and videoUrl."""
    by_id = {}
    for item in raw:
        pid = str(item.get('shortCode') or item.get('id'))
        by_id[pid] = {'thumb': item.get('displayUrl'), 'video': item.get('videoUrl'),
                      'images': item.get('images') or ([item['displayUrl']] if item.get('displayUrl') else [])}
    return by_id


def linkedin_media(raw: list[dict]) -> dict[str, dict]:
    by_id = {}
    for item in raw:
        pid = str(item.get('id') or item.get('urn') or item.get('entityId') or '')
        images = [i.get('url') for i in item.get('postImages') or [] if i.get('url')]
        doc = item.get('document') or {}
        pages = [u for page in doc.get('coverPages') or [] for u in (page.get('imageUrls') or [])[:1]]
        video = item.get('postVideo') or {}
        thumb = (images or pages or [video.get('thumbnailUrl')])[0] if (images or pages or video) else None
        by_id[pid] = {'thumb': thumb, 'video': video.get('videoUrl'), 'images': images or pages}
    return by_id


def tiktok_media(raw: list[dict]) -> dict[str, dict]:
    return {str(i.get('id')): {'thumb': (i.get('videoMeta') or {}).get('coverUrl'), 'video': None, 'images': []}
            for i in raw}


def youtube_media(raw: list[dict]) -> dict[str, dict]:
    out = {}
    for i in raw:
        thumbs = [t.get('url') for t in i.get('thumbnails') or [] if t.get('url')]
        out[str(i.get('id'))] = {'thumb': thumbs[-1] if thumbs else f"https://i.ytimg.com/vi/{i.get('id')}/hqdefault.jpg",
                                 'video': None, 'images': []}
    return out


def pick(work: Path, top: int, flops: int, ids: list[str]) -> list[str]:
    patterns = read_json(work / 'patterns.json') if (work / 'patterns.json').exists() else {}
    chosen = [r['post_id'] for r in patterns.get('top_outliers', [])[:top]]
    chosen += [r['post_id'] for r in patterns.get('top_duds', [])[:flops]]
    for pid in ids:
        if pid not in chosen:
            chosen.append(pid)
    return chosen


def run(work: Path, *, top=8, flops=3, ids=(), media_lookup=None) -> dict:
    work = Path(work)
    source = read_json(work / 'posts.json')
    raw = read_json(work / 'raw.json') if (work / 'raw.json').exists() else []
    platform = source['platform']
    if media_lookup is None:
        media_lookup = {'instagram': lambda: instagram_media(raw),
                        'linkedin': lambda: linkedin_media(raw), 'tiktok': lambda: tiktok_media(raw),
                        'youtube': lambda: youtube_media(raw)}[platform]()
    out_root = work / 'visuals'
    manifest = read_json(work / 'visuals.json') if (work / 'visuals.json').exists() else {}
    full = set(pick(work, top, flops, list(ids)))
    for post in source['posts']:
        pid = str(post['post_id'])
        media = media_lookup.get(pid) or {}
        entry = manifest.get(pid, {'thumb': None, 'images': [], 'frames': [], 'errors': []})
        entry.setdefault('errors', [])
        thumb_path = out_root / 'thumbs' / f'{safe_id(pid)}.jpg'
        if not entry.get('thumb') and media.get('thumb'):
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    shrink(fetch(media['thumb'], Path(tmp) / 'in'), thumb_path, THUMB_W)
                entry['thumb'] = str(thumb_path.relative_to(work))
            except Exception as exc:
                entry['errors'].append(f'thumb: {exc}')
        if pid in full and not (entry.get('images') or entry.get('frames')):
            post_dir = out_root / safe_id(pid)
            try:
                if media.get('video'):
                    entry['frames'] = [str(Path(f).relative_to(work)) for f in video_frames(media['video'], post_dir)]
                for n, url in enumerate((media.get('images') or [])[:MAX_IMAGES], 1):
                    with tempfile.TemporaryDirectory() as tmp:
                        img = shrink(fetch(url, Path(tmp) / 'in'), post_dir / f'image_{n}.jpg', FULL_W)
                    entry['images'].append(str(img.relative_to(work)))
            except Exception as exc:
                entry['errors'].append(f'media: {exc}')
        manifest[pid] = entry
    write_json(work / 'visuals.json', manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description='Save small images of every post, and full media for the best and worst.')
    parser.add_argument('--work', type=Path, required=True, help='the run .work folder')
    parser.add_argument('--top', type=int, default=8)
    parser.add_argument('--flops', type=int, default=3)
    parser.add_argument('--ids', default='', help='extra post ids that need full media')
    args = parser.parse_args()
    result = run(args.work, top=args.top, flops=args.flops, ids=[i for i in args.ids.split(',') if i])
    thumbs = sum(1 for v in result.values() if v.get('thumb'))
    full = sum(1 for v in result.values() if v.get('images') or v.get('frames'))
    errors = sum(1 for v in result.values() if v.get('errors'))
    print(f'{thumbs} thumbnails, {full} posts with full media, {errors} posts with errors')


if __name__ == '__main__':
    main()

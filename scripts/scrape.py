#!/usr/bin/env python3
"""Pull a creator's recent posts into one normalised posts.json.

Platforms: instagram, tiktok, linkedin (Apify public actors, APIFY_TOKEN), youtube (the YouTube Data API
with YOUTUBE_API_KEY, free quota; without a key, yt-dlp lists the Shorts tab, without dates).
Every Apify run is capped twice: --limit (maxItems) and --max-cost-usd (maxTotalChargeUsd), so a
run can never spend past the cap you set. Nothing logs in as you and no cookie is ever used.

Usage:
    python3 scrape.py --platform instagram --handle some_creator --limit 280 --work RUN/.work
    python3 scrape.py ... --raw RUN/.work/raw.json      # keep the raw items to debug field names
    python3 scrape.py ... --from-raw RUN/.work/raw.json # re-normalise without paying again
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from common import ConfigError, die, load_env, load_settings, write_json
from normalise import NORMALISERS

APIFY_RUN = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

# Public Apify store actors, and how to build each one's input.
ACTORS = {
    "instagram": ("shu8hvrXbJbY3Eb9W", lambda h, n: {  # apify/instagram-scraper
        "directUrls": [h if h.startswith("http") else f"https://www.instagram.com/{h}/"],
        "resultsType": "posts", "resultsLimit": n, "addParentData": False}),
    "tiktok": ("clockworks~tiktok-scraper", lambda h, n: {
        "profiles": [h], "resultsPerPage": n, "shouldDownloadVideos": False}),
    "linkedin": ("harvestapi~linkedin-profile-posts", lambda h, n: {
        "targetUrls": [h if h.startswith("http") else f"https://www.linkedin.com/in/{h}/"],
        "maxPosts": n}),
}


def apify_request(platform: str, handle: str, limit: int, max_cost: float, token: str) -> urllib.request.Request:
    actor, build_input = ACTORS[platform]
    query = urllib.parse.urlencode({"maxItems": limit, "maxTotalChargeUsd": max_cost})
    return urllib.request.Request(
        f"{APIFY_RUN.format(actor=actor)}?{query}",
        data=json.dumps(build_input(handle, limit)).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})


def run_apify(platform: str, handle: str, limit: int, max_cost: float) -> list[dict]:
    load_env()
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        die("APIFY_TOKEN is not set. Export it, or add it to config/.env (see SETUP.md).")
    actor = ACTORS[platform][0]
    try:
        with urllib.request.urlopen(apify_request(platform, handle, limit, max_cost, token), timeout=600) as response:
            items = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300].replace(token, "[redacted]")
        die(f"Apify {actor} returned HTTP {exc.code}: {body}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        die(f"Could not reach Apify: {exc}")
    if not isinstance(items, list):
        die(f"Apify {actor} returned no item list: {str(items)[:300]}")
    return items


def youtube_handle(handle: str) -> str:
    """'@SomeChannel', 'SomeChannel' or a channel URL in, 'SomeChannel' out."""
    match = re.search(r'youtube\.com/@([^/?#]+)', handle)
    return (match.group(1) if match else handle).lstrip('@').strip('/')


def youtube_api_request(path: str, key: str, **query) -> urllib.request.Request:
    """The key goes in a header, never in the URL, so it cannot leak into a log or an error."""
    return urllib.request.Request(f"https://www.googleapis.com/youtube/v3/{path}?{urllib.parse.urlencode(query)}",
                                  headers={"X-goog-api-key": key})


def run_youtube_api(handle: str, limit: int) -> list[dict]:
    """The YouTube Data API (free quota): the channel's last `limit` uploads, Shorts and long videos,
    with publish time, duration, views, likes, comments, title, description and thumbnails."""
    load_env()
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set")

    def api(path: str, **query) -> dict:
        try:
            with urllib.request.urlopen(youtube_api_request(path, key, **query), timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"YouTube Data API HTTP {exc.code}: {exc.read().decode(errors='replace')[:200].replace(key, '[redacted]')}") from None

    channels = api("channels", part="contentDetails", forHandle="@" + youtube_handle(handle)).get("items") or []
    if not channels:
        raise RuntimeError(f"no YouTube channel for @{youtube_handle(handle)}")
    uploads = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], ""
    while len(ids) < limit:
        data = api("playlistItems", part="contentDetails", playlistId=uploads, maxResults=50, **({"pageToken": page} if page else {}))
        ids += [item["contentDetails"]["videoId"] for item in data.get("items", [])]
        page = data.get("nextPageToken") or ""
        if not page:
            break
    items = []
    for start in range(0, min(limit, len(ids)), 50):
        batch = ids[start:min(limit, start + 50)]
        items += api("videos", part="snippet,contentDetails,statistics", id=",".join(batch)).get("items", [])
    return items


def run_ytdlp(handle: str, limit: int) -> list[dict]:
    """Flat listing of a channel's Shorts tab. Newest first; no upload dates in flat mode."""
    channel = f"https://www.youtube.com/@{youtube_handle(handle)}/shorts"
    try:
        completed = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(limit), channel],
            capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        die("yt-dlp is not installed. Install it (see SETUP.md) to read YouTube Shorts.")
    if completed.returncode != 0:
        die(f"yt-dlp failed: {completed.stderr.strip()[:300]}")
    return json.loads(completed.stdout).get("entries", [])


def run(work: Path, *, platform: str, handle: str, limit: int = 200,
        max_cost_usd: float = 5.0, raw: Path | None = None, from_raw: Path | None = None) -> dict:
    handle = handle.strip().lstrip("@")
    if platform == "youtube":
        handle = youtube_handle(handle)
    if from_raw:
        raw_items = json.loads(Path(from_raw).read_text(encoding="utf-8"))
        raw = None
    elif platform == "youtube":
        try:
            raw_items = run_youtube_api(handle, limit)
        except Exception as exc:  # no key or an API error: the Shorts listing still works, without dates
            print(f"YouTube Data API said no ({exc}). Falling back to the yt-dlp Shorts listing.", file=sys.stderr)
            raw_items = run_ytdlp(handle, limit)
    else:
        raw_items = run_apify(platform, handle, limit, max_cost_usd)
    if raw:
        write_json(raw, raw_items)
    normalise = NORMALISERS[platform]
    posts, errors, seen = [], [], set()
    for index, item in enumerate(raw_items):
        try:
            post = normalise(item, handle)
            if post and post['post_id'] in seen:
                continue
            if post:
                seen.add(post['post_id'])
                posts.append(post)
            else:
                errors.append({'index': index, 'error': 'missing post id or unsupported post'})
        except Exception as exc:
            errors.append({'index': index, 'error': str(exc)})
    if not posts:
        die(f"{len(raw_items)} raw items, 0 usable posts. Re-run with --raw and check field names.")
    payload = {"platform": platform, "handle": handle,
               "pulled_at": datetime.now(timezone.utc).isoformat(), "posts": posts, "errors": errors}
    write_json(Path(work) / "posts.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull a creator's recent posts into posts.json.")
    parser.add_argument("--platform", required=True, choices=["instagram", "tiktok", "linkedin", "youtube"])
    parser.add_argument("--handle", required=True, help="handle, profile URL or single post URL")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-cost-usd", type=float,
                        help="hard Apify spend cap in US$ (default: apify_max_cost_usd in settings, else 5)")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--raw", help="also write the raw items here")
    parser.add_argument("--from-raw", type=Path, help="re-normalise a saved raw file instead of pulling again")
    args = parser.parse_args()

    work = args.work or (args.out.parent if args.out else None)
    if work is None:
        parser.error("--work or --out is required")
    try:
        max_cost = args.max_cost_usd if args.max_cost_usd is not None else load_settings()["apify_max_cost_usd"]
    except ConfigError as exc:
        die(str(exc))
    if args.platform != "youtube" and not args.from_raw:
        print(f"Apify spend is capped at US${max_cost:.2f} for this pull.")
    payload = run(work, platform=args.platform, handle=args.handle, limit=args.limit,
                  max_cost_usd=max_cost, raw=Path(args.raw) if args.raw else None, from_raw=args.from_raw)
    if args.out and args.out != work / "posts.json":
        write_json(args.out, payload)
    print(f"{len(payload['posts'])} posts -> {work / 'posts.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

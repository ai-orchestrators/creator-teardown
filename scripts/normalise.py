"""Turn each platform's raw item into one post shape.

Post shape:
    post_id, url, platform, format (video|image|carousel|text|document),
    posted_at (ISO or None), duration_s, caption, media_url,
    metrics {views, likes, comments, shares, saves}

Field names differ by actor version, so every read tries a few keys and a
missing value stays None. Never guess a metric.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone


def first(item: dict, *keys, default=None):
    """Return the first present, non-empty value among dotted keys."""
    for key in keys:
        value = item
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value not in (None, "", [], {}):
            return value
    return default


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_iso(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    text = str(value).replace("Z", "+00:00")
    # Some APIs send "+0000"; Python 3.9's fromisoformat only reads "+00:00".
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return str(value)


def instagram(item: dict, handle: str):
    """Apify's public Instagram scraper (apify/instagram-scraper) items."""
    kind = (item.get("type") or "").lower()
    post_format = {"video": "video", "sidecar": "carousel", "image": "image"}.get(kind, "video" if item.get("videoUrl") else "image")
    return {
        "post_id": str(item.get("shortCode") or item.get("id") or ""),
        "url": item.get("url"),
        "platform": "instagram",
        "format": post_format,
        "posted_at": as_iso(item.get("timestamp")),
        "duration_s": item.get("videoDuration"),
        "caption": item.get("caption") or "",
        "media_url": item.get("videoUrl") if post_format == "video" else None,
        "metrics": {
            "views": as_int(first(item, "videoPlayCount", "videoViewCount")),
            "likes": as_int(item.get("likesCount")),
            "comments": as_int(item.get("commentsCount")),
            "shares": None, "saves": None,
        },
    }


def tiktok(item: dict, handle: str):
    return {
        "post_id": str(item.get("id") or ""),
        "url": first(item, "webVideoUrl", "url"),
        "platform": "tiktok",
        "format": "carousel" if item.get("isSlideshow") else "video",
        "posted_at": as_iso(first(item, "createTimeISO", "createTime")),
        "duration_s": first(item, "videoMeta.duration", "duration"),
        "caption": item.get("text") or "",
        "media_url": None,
        "metrics": {
            "views": as_int(item.get("playCount")),
            "likes": as_int(item.get("diggCount")),
            "comments": as_int(item.get("commentCount")),
            "shares": as_int(item.get("shareCount")),
            "saves": as_int(item.get("collectCount")),
        },
    }


def linkedin(item: dict, handle: str):
    if first(item, "type") == "repost" or item.get("isRepost") or item.get("repostedBy"):
        return None  # a repost is someone else's post or a re-share; it would poison the baseline
    author = first(item, "author.publicIdentifier")
    if author and handle and not handle.startswith("http") and author.lower() != handle.lower():
        return None
    if first(item, "postVideo", "video"):
        post_format = "video"
    elif first(item, "document"):
        post_format = "document"
    elif first(item, "postImages", "images"):
        images = first(item, "postImages", "images")
        post_format = "carousel" if isinstance(images, list) and len(images) > 1 else "image"
    else:
        post_format = "text"
    return {
        "post_id": str(first(item, "id", "urn", "entityId", default="")),
        "url": first(item, "linkedinUrl", "url", "postUrl"),
        "platform": "linkedin",
        "format": post_format,
        "posted_at": as_iso(first(item, "postedAt.date", "postedAt.timestamp", "postedAt", "date")),
        "duration_s": None,
        "caption": first(item, "content", "text", "commentary", default=""),
        "media_url": first(item, "postVideo.videoUrl") if post_format == "video" else None,
        "metrics": {
            "views": as_int(first(item, "engagement.impressions", "impressions")),
            "likes": as_int(first(item, "engagement.likes", "engagement.reactions_count", "numLikes")),
            "comments": as_int(first(item, "engagement.comments", "numComments")),
            "shares": as_int(first(item, "engagement.shares", "numShares")),
            "saves": None,
        },
    }


def youtube(item: dict, handle: str):
    video_id = item.get("id")
    return {
        "post_id": video_id,
        "url": item.get("url") or f"https://www.youtube.com/shorts/{video_id}",
        "platform": "youtube",
        "format": "video",
        "posted_at": as_iso(item.get("timestamp")),
        "duration_s": item.get("duration"),
        "caption": item.get("title") or "",
        "media_url": None,
        "metrics": {"views": as_int(item.get("view_count")), "likes": None,
                    "comments": None, "shares": None, "saves": None},
    }


def keep_if_identified(build):
    def wrapped(item, handle):
        post = build(item, handle)
        return post if post and post.get("post_id") else None
    return wrapped


NORMALISERS = {name: keep_if_identified(fn) for name, fn in
               {"instagram": instagram, "tiktok": tiktok, "linkedin": linkedin, "youtube": youtube}.items()}

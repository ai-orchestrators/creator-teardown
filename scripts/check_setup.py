#!/usr/bin/env python3
"""Check the toolchain, keys and config for creator-teardown.

Prints what is there and what is missing. For a key it only ever says set or missing: a key's
value is never read into the output, never printed and never written.

Usage:
    python3 check_setup.py            # a table
    python3 check_setup.py --json     # the same, as JSON (SETUP.md reads this)
Exit 0 when everything the configured platforms need is present, else 1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

from common import ConfigError, KEY_NAMES, brand_profiles, config_dir, key_present, load_settings

VIDEO_PLATFORMS = {"instagram", "tiktok", "youtube", "linkedin"}
APIFY_PLATFORMS = {"instagram", "tiktok", "linkedin"}


def tool(name: str) -> dict:
    path = shutil.which(name) if name else None
    return {"found": bool(path), "path": path}


def key_status() -> dict[str, bool]:
    return {name: key_present(name) for name in KEY_NAMES}


def run() -> dict:
    report = {"config_dir": str(config_dir()), "problems": [], "notes": []}
    try:
        settings = load_settings()
    except ConfigError as exc:
        report["problems"].append(str(exc))
        return report
    platforms = set(settings.get("platforms") or [])
    folder = config_dir()
    report["config"] = {name: (folder / name).exists() for name in ("settings.json", "profile.md", "brand.json", ".env")}
    report["keys"] = key_status()
    transcriber = settings["transcriber"]
    model = transcriber.get("model")
    report["tools"] = {name: tool(name) for name in ("ffmpeg", "ffprobe", "yt-dlp")}
    report["tools"]["whisper"] = tool(transcriber.get("binary") or "whisper-cli")
    report["whisper_model"] = {"path": model, "found": bool(model) and Path(model).expanduser().is_file()}
    report["custom_transcriber"] = bool(transcriber.get("command"))
    report["optional"] = {"youtube-transcript-api": importlib.util.find_spec("youtube_transcript_api") is not None}
    captions_only = platforms == {"youtube"} and report["optional"]["youtube-transcript-api"]

    for name in ("settings.json", "profile.md"):
        if not report["config"][name]:
            report["problems"].append(f"config/{name} is missing. Run SETUP.md.")
    report["brand_profiles"] = sorted(brand_profiles())
    client_dir = settings.get("client_files_dir")
    if client_dir and not Path(client_dir).expanduser().is_dir():
        report["notes"].append(f"client_files_dir {client_dir} does not exist. Client runs will use their posts and notes only.")
    if not report["keys"]["TYPESAFE_API_KEY"]:
        report["problems"].append("TYPESAFE_API_KEY is missing. Jev labels every post, so a run cannot finish without it.")
    if not report["keys"]["OPENROUTER_API_KEY"]:
        report["notes"].append("OPENROUTER_API_KEY is missing. Optional: it is only the fallback when TypeSafe is busy.")
    if platforms & APIFY_PLATFORMS and not report["keys"]["APIFY_TOKEN"]:
        report["problems"].append(f"APIFY_TOKEN is missing. Needed for {', '.join(sorted(platforms & APIFY_PLATFORMS))}.")
    if platforms & VIDEO_PLATFORMS:
        for name in ("ffmpeg", "ffprobe"):
            if not report["tools"][name]["found"]:
                report["problems"].append(f"{name} is not installed. Needed to measure and transcribe video.")
        if not report["custom_transcriber"]:
            # YouTube-only with captions available: whisper only covers videos that have no captions.
            whisper_gaps = (report["notes"] if captions_only else report["problems"])
            if not report["tools"]["whisper"]["found"]:
                whisper_gaps.append(f"{transcriber.get('binary') or 'whisper-cli'} is not installed (whisper.cpp).")
            if not report["whisper_model"]["found"]:
                whisper_gaps.append("No whisper model file found. Set transcriber.model in config/settings.json.")
    if "youtube" in platforms and not report["keys"]["YOUTUBE_API_KEY"]:
        report["notes"].append("YOUTUBE_API_KEY is missing. Optional: without it YouTube falls back to the Shorts tab "
                               "listing, with no upload dates, likes or long videos.")
    if "youtube" in platforms and not report["optional"]["youtube-transcript-api"]:
        report["notes"].append("youtube-transcript-api is not installed. Optional (pip install youtube-transcript-api): "
                               "without it whisper transcribes every YouTube video.")
    if platforms & {"youtube", "tiktok", "linkedin"} and not report["tools"]["yt-dlp"]["found"]:
        report["problems"].append("yt-dlp is not installed. Needed for YouTube Shorts and for TikTok and LinkedIn video.")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check tools, keys and config. Never prints a key's value.")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    report = run()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if not report["problems"] else 1
    print(f"config folder: {report['config_dir']}")
    for name, present in (report.get("config") or {}).items():
        print(f"  {name:<14} {'ok' if present else 'missing'}")
    for name, present in (report.get("keys") or {}).items():
        print(f"  {name:<19} {'set' if present else 'missing'}")
    if report.get("brand_profiles"):
        print(f"  brand profiles {', '.join(report['brand_profiles'])}")
    for name, status in (report.get("tools") or {}).items():
        print(f"  {name:<14} {status['path'] if status['found'] else 'missing'}")
    for name, present in (report.get("optional") or {}).items():
        print(f"  {name:<14} {'installed' if present else 'not installed (optional)'}")
    if "whisper_model" in report:
        model = report["whisper_model"]
        print(f"  whisper model  {model['path'] if model['found'] else 'missing'}")
    for note in report["notes"]:
        print(f"note: {note}")
    for problem in report["problems"]:
        print(f"MISSING: {problem}")
    print("ready" if not report["problems"] else f"{len(report['problems'])} thing(s) to fix")
    return 0 if not report["problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

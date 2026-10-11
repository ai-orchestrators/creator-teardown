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
import json
import shutil
from pathlib import Path

from common import ConfigError, KEY_NAMES, config_dir, key_present, load_settings

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

    for name in ("settings.json", "profile.md"):
        if not report["config"][name]:
            report["problems"].append(f"config/{name} is missing. Run SETUP.md.")
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
            if not report["tools"]["whisper"]["found"]:
                report["problems"].append(f"{transcriber.get('binary') or 'whisper-cli'} is not installed (whisper.cpp).")
            if not report["whisper_model"]["found"]:
                report["problems"].append("No whisper model file found. Set transcriber.model in config/settings.json.")
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
    for name, status in (report.get("tools") or {}).items():
        print(f"  {name:<14} {status['path'] if status['found'] else 'missing'}")
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

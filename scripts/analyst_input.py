#!/usr/bin/env python3
"""Build .work/analyst_input.json for the per-post analyst agent: the top outliers, the worst duds and any
post the playbook names, each with its caption, timed sentences with Jev roles, stats and image paths.

Usage: python3 analyst_input.py <run folder>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_json, write_json


def run(run_dir: Path, top: int = 8, flops: int = 3) -> list[dict]:
    work = Path(run_dir) / ".work"
    posts = {str(p["post_id"]): p for p in read_json(work / "posts.json")["posts"]}
    features, outliers = read_json(work / "features.json"), read_json(work / "outliers.json")
    labels, patterns = read_json(work / "labels.json"), read_json(work / "patterns.json")
    visuals = read_json(work / "visuals.json") if (work / "visuals.json").exists() else {}
    ids = [str(r["post_id"]) for r in patterns.get("top_outliers", [])[:top]]
    ids += [str(r["post_id"]) for r in patterns.get("top_duds", [])[:flops]]
    playbook_path = Path(run_dir) / "playbook.json"
    playbook = read_json(playbook_path) if playbook_path.exists() else {}
    for item in playbook.get("best_posts", []) + playbook.get("misses", []):
        if str(item["post_id"]) not in ids:
            ids.append(str(item["post_id"]))
    out = []
    for post_id in ids:
        post, feat, band = posts[post_id], features[post_id], outliers["posts"][post_id]
        roles = labels.get("sentences", {}).get(post_id, [])
        sentences = [{"t": s.get("start_s"), "position": s["position"],
                      "role": roles[i].get("role", {}).get("value") if i < len(roles) else None, "text": s["text"]}
                     for i, s in enumerate(feat["sentences"])]
        media = visuals.get(post_id, {})
        out.append({"post_id": post_id, "band": band["band"], "multiple": round(band["multiple"] or 0, 2),
                    "tier": band.get("tier"), "format": feat["format"], "date": (post["posted_at"] or "")[:10],
                    "metrics": post["metrics"], "url": post["url"], "caption": post["caption"][:3000],
                    "source": feat["source"], "sentences": sentences[:60],
                    "images": [str((work / x).resolve()) for x in media.get("images", []) + media.get("frames", [])]})
    write_json(work / "analyst_input.json", out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the analyst agent's input file.")
    parser.add_argument("run_dir", type=Path, help="the run folder (holds .work/)")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--flops", type=int, default=3)
    args = parser.parse_args()
    out = run(args.run_dir, args.top, args.flops)
    print(len(out), "posts,", sum(len(x["images"]) for x in out), "images")


if __name__ == "__main__":
    main()

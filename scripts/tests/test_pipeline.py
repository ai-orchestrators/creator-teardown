"""Acceptance tests for the creator-teardown pipeline. Offline: no network, no real Jev, no keys.

Every post, caption and id here is synthetic. config/ is pointed at an empty temp folder, so your
own settings never change a result.

Run from the repo root: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
_CONFIG = tempfile.mkdtemp(prefix="ct-config-")
atexit.register(shutil.rmtree, _CONFIG, True)
os.environ["CREATOR_TEARDOWN_CONFIG"] = _CONFIG

import agree  # noqa: E402
import classify  # noqa: E402
import features  # noqa: E402
import media  # noqa: E402
import normalise  # noqa: E402
import outliers  # noqa: E402
import patterns  # noqa: E402
import report  # noqa: E402

NOW = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def post(i: int, *, views=1000, likes=100, shares=None, fmt="video", days_ago=None,
         caption="Caption line one.\nSecond line here.", platform="instagram", media_url="https://cdn/x.mp4"):
    posted = NOW - timedelta(days=days_ago if days_ago is not None else 60 - i)
    return {"post_id": f"p{i}", "url": f"https://example.com/p{i}", "platform": platform, "format": fmt,
            "posted_at": posted.isoformat(), "duration_s": 30, "caption": caption,
            "media_url": media_url if fmt == "video" else None,
            "metrics": {"views": views, "likes": likes, "comments": 10, "shares": shares, "saves": None}}


def tokens(*words_with_times):
    """(" word", start_ms, end_ms) -> remotion caption tokens."""
    return [{"text": w, "startMs": s, "endMs": e, "timestampMs": s, "confidence": 0.9}
            for w, s, e in words_with_times]


# ---------------------------------------------------------------------------
# normalise: Instagram comes from Apify's public scraper
# ---------------------------------------------------------------------------


class InstagramApifyFormats(unittest.TestCase):
    def test_carousel_and_image(self):
        base = {"shortCode": "SynthPost01", "url": "https://example.com/p/SynthPost01/", "caption": "Hi",
                "timestamp": "2026-10-10T19:00:08.000Z", "likesCount": 10, "commentsCount": 2,
                "displayUrl": "https://example.com/img.jpg"}
        album = normalise.NORMALISERS["instagram"](dict(base, type="Sidecar"), "example_creator")
        self.assertEqual(album["format"], "carousel")
        self.assertIsNone(album["media_url"])
        self.assertIsNone(album["metrics"]["views"])
        image = normalise.NORMALISERS["instagram"](dict(base, type="Image"), "example_creator")
        self.assertEqual(image["format"], "image")
        self.assertTrue(image["posted_at"].startswith("2026-10-10T19:00:08"))
        self.assertIsNone(normalise.NORMALISERS["instagram"](dict(base, shortCode=None), "example_creator"))


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------


class InstagramApify(unittest.TestCase):
    def test_apify_item(self):
        item = {"shortCode": "SynthReel02", "url": "https://example.com/p/SynthReel02/", "type": "Video",
                "timestamp": "2026-10-01T00:04:43.000Z", "videoDuration": 37.8, "caption": "comment GUIDE",
                "videoUrl": "https://cdn/v.mp4", "videoPlayCount": 120000, "likesCount": 4000, "commentsCount": 900}
        out = normalise.NORMALISERS["instagram"](item, "example_creator")
        self.assertEqual(out["post_id"], "SynthReel02")
        self.assertEqual(out["format"], "video")
        self.assertEqual(out["metrics"]["views"], 120000)
        self.assertEqual(out["media_url"], "https://cdn/v.mp4")
        self.assertTrue(out["posted_at"].startswith("2026-10-01T00:04:43"))


class SplitSentences(unittest.TestCase):
    def test_lines_and_punctuation(self):
        text = "Line one hook.\n\nSecond line. Third sentence!\n→ Arrow item\nP.S. Question?"
        self.assertEqual(features.split_sentences(text),
                         ["Line one hook.", "Second line.", "Third sentence!", "→ Arrow item", "P.S. Question?"])

    def test_drops_empty_and_symbol_only(self):
        self.assertEqual(features.split_sentences("Hi there.\n\n---\n→\nBye."), ["Hi there.", "Bye."])


class CaptionSentences(unittest.TestCase):
    def test_punctuation_and_timing(self):
        caps = tokens((" Most", 0, 200), (" people", 200, 400), (" fail.", 400, 700),
                      (" Here's", 1000, 1200), (" why.", 1200, 1500))
        out = features.sentences_from_captions(caps)
        self.assertEqual([s["text"] for s in out], ["Most people fail.", "Here's why."])
        self.assertEqual(out[0]["start_s"], 0.0)
        self.assertEqual(out[0]["end_s"], 0.7)
        self.assertEqual(out[0]["words"], 3)
        self.assertEqual(out[1]["start_s"], 1.0)

    def test_long_pause_splits_unpunctuated_speech(self):
        caps = tokens((" so", 0, 200), (" this", 200, 400), (" works", 400, 600),
                      (" and", 2000, 2200), (" then", 2200, 2400), (" more", 2400, 2600))
        out = features.sentences_from_captions(caps)
        self.assertEqual([s["text"] for s in out], ["so this works", "and then more"])

    def test_skips_empty_tokens(self):
        caps = tokens((" ", 0, 10), (" Hi.", 10, 300))
        self.assertEqual([s["text"] for s in features.sentences_from_captions(caps)], ["Hi."])


    def test_decimal_and_abbreviation_stay_whole(self):
        caps = tokens((" We", 0, 100), (" made", 100, 200), (" 1.", 200, 300), ("2", 300, 350), (" million", 350, 500),
                      (" in", 500, 600), (" the", 600, 700), (" U.S.", 700, 900), (" market.", 900, 1100),
                      (" Then", 1300, 1400), (" I", 1400, 1500), (" sold", 1500, 1600), (" 3.", 1600, 1800),
                      (" Done.", 2000, 2200))
        self.assertEqual([s["text"] for s in features.sentences_from_captions(caps)],
                         ["We made 1.2 million in the U.S. market.", "Then I sold 3.", "Done."])

    def test_spaced_initials_stay_whole(self):
        caps = tokens((" I", 0, 100), (" have", 100, 200), (" a", 200, 300), (" salon", 300, 400), (" in", 400, 500),
                      (" L.", 500, 600), (" A.", 600, 700), (" Perfect.", 900, 1100))
        self.assertEqual([s["text"] for s in features.sentences_from_captions(caps)], ["I have a salon in L. A.", "Perfect."])

    def test_caption_split_keeps_abbreviations(self):
        self.assertEqual(features.split_sentences("We grew 1.2x in the U.S. last year. Dr. Lee agreed."),
                         ["We grew 1.2x in the U.S. last year.", "Dr. Lee agreed."])


class YouTube(unittest.TestCase):
    def test_api_item_normalises_short_and_long(self):
        base = {'snippet': {'title': 'How I price', 'publishedAt': '2026-10-11T02:00:00Z', 'description': 'd',
                            'thumbnails': {'high': {'url': 'https://example.com/h.jpg'}}},
                'statistics': {'viewCount': '1200', 'likeCount': '30', 'commentCount': '4'}}
        short = normalise.youtube(dict(base, id='s1', contentDetails={'duration': 'PT58S'}), 'x')
        long = normalise.youtube(dict(base, id='l1', contentDetails={'duration': 'PT37M14S'}), 'x')
        self.assertEqual((short['format'], short['url']), ('short', 'https://www.youtube.com/shorts/s1'))
        self.assertEqual((long['format'], long['duration_s']), ('video', 2234.0))
        self.assertEqual(long['metrics']['likes'], 30)
        self.assertEqual(long['thumbnail_url'], 'https://example.com/h.jpg')

    def test_captions_become_timed_word_tokens(self):
        import sys, types
        seg = lambda start, duration, text: SimpleNamespace(start=start, duration=duration, text=text)
        fake = types.ModuleType('youtube_transcript_api')
        fake.YouTubeTranscriptApi = lambda: SimpleNamespace(fetch=lambda vid, languages: [
            seg(0.0, 1.0, "Here's the deal."), seg(1.0, 1.0, '[Music]'), seg(300.0, 1.0, 'Too late.')])
        sys.modules['youtube_transcript_api'] = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / 't.json'
                media.youtube_captions('v1', out, max_start=240)
                tokens = read(out)['captions']
        finally:
            del sys.modules['youtube_transcript_api']
        self.assertEqual([t['text'] for t in tokens], [" Here's", ' the', ' deal.'])
        self.assertEqual([s['text'] for s in features.sentences_from_captions(tokens)], ["Here's the deal."])


class BlindSample(unittest.TestCase):
    def test_spread_across_bands_with_instructions(self):
        import blind_sample
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            bands = ['outlier'] * 10 + ['normal'] * 20 + ['dud'] * 10
            write(work / 'features.json', {f'p{i}': {'segments': {'hook_text': f'hook {i}', 'opening_text': '', 'body_text': '', 'ending_text': ''}} for i in range(40)})
            write(work / 'outliers.json', {'posts': {f'p{i}': {'band': b} for i, b in enumerate(bands)}})
            form = work / 'form.json'
            write(form, {'questions': {k: {'instructions': f'judge {k}', 'criteria': {'a': 'A', 'b': 'B'}} for k in ('hook_type', 'structure', 'evidence', 'ending')}})
            out = blind_sample.run(work, n=20, form_path=form)
            picked = [p['post_id'] for p in out['posts']]
            self.assertEqual(len(set(picked)), 20)
            counts = {b: sum(bands[int(pid[1:])] == b for pid in picked) for b in ('outlier', 'normal', 'dud')}
            self.assertEqual(counts, {'outlier': 7, 'normal': 7, 'dud': 6})
            self.assertEqual(out['questions']['hook_type']['instructions'], 'judge hook_type')
            self.assertIn('hook_text', out['posts'][0])


class TranscriptStore(unittest.TestCase):
    def test_reuses_stored_transcript_without_download(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / 'transcripts.db'
            with sqlite3.connect(db) as con:
                con.execute('create table transcripts (video_id text, transcript text)')
                con.execute('insert into transcripts values (?, ?)', ('v1', '[0:00:00] Here is the deal. [0:00:30] Second block. [0:05:00] Too late.'))
            post = {'post_id': 'v1', 'platform': 'youtube', 'duration_s': 1800, 'url': 'https://example.com/v1'}
            boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError('should not download'))
            entry = media.process(post, Path(d) / 'out', boom, boom, boom, False, store=db)
            self.assertEqual((entry['status'], entry['from_store'], entry['intro_only_s']), ('ok', True, 240))
            tokens = read(Path(d) / 'out' / 'transcript.json')['captions']
            self.assertEqual(' '.join(t['text'].strip() for t in tokens), 'Here is the deal. Second block.')
            self.assertEqual(tokens[4]['startMs'], 30000)
            missing = dict(post, post_id='v2')
            calls = []
            media.process(missing, Path(d) / 'out2', lambda *a: calls.append('download') or (_ for _ in ()).throw(RuntimeError('x')), boom, boom, False, store=db)
            self.assertEqual(calls, ['download'])


class Positions(unittest.TestCase):
    def test_text_positions(self):
        sents = [{"text": t} for t in ["a1 b.", "c2 d.", "e3 f.", "g4 h.", "i5 j."]]
        out = features.tag_positions(sents, None)
        self.assertEqual([s["position"] for s in out], ["hook", "opening", "body", "body", "ending"])

    def test_short_text(self):
        self.assertEqual([s["position"] for s in features.tag_positions([{"text": "x"}], None)], ["hook"])
        self.assertEqual([s["position"] for s in features.tag_positions([{"text": "x"}, {"text": "y"}], None)],
                         ["hook", "ending"])

    def test_video_positions(self):
        starts = [0.0, 1.5, 4.0, 6.0, 12.0, 18.0, 26.0, 28.5]
        sents = [{"text": f"s{i}", "start_s": s, "end_s": s + 1.0} for i, s in enumerate(starts)]
        out = features.tag_positions(sents, 30.0)
        # hook: first sentence plus anything starting before 3s.
        # ending: start >= 0.85 x speech end (29.5 -> 25.075), always includes the last.
        # opening: start < 0.25 x speech end (7.375). body: the rest.
        self.assertEqual([s["position"] for s in out],
                         ["hook", "hook", "opening", "opening", "body", "body", "ending", "ending"])


class BuildFeatures(unittest.TestCase):
    def test_video_post(self):
        p = post(1)
        caps = tokens((" Most", 0, 200), (" people", 200, 400), (" fail", 400, 600), (" at", 600, 700),
                      (" this.", 700, 900), (" Here's", 1000, 1200), (" the", 1200, 1300), (" fix.", 1300, 1500),
                      (" Step", 5000, 5200), (" one", 5200, 5400), (" is", 5400, 5500), (" simple.", 5500, 6000),
                      (" Follow", 28000, 28300), (" for", 28300, 28500), (" more.", 28500, 29000))
        f = features.build_features(p, {"status": "ok", "duration_s": 30.0, "cuts": 15},
                                    {"text": "x", "captions": caps})
        self.assertEqual(f["source"], "transcript")
        self.assertEqual(f["segments"]["hook_text"], "Most people fail at this. Here's the fix.")
        self.assertEqual(f["segments"]["ending_text"], "Follow for more.")
        self.assertEqual(f["length_bucket"], "30_to_60s")
        t = f["tempo"]
        self.assertEqual(t["words"], 15)
        self.assertEqual(t["sentences"], 4)
        self.assertAlmostEqual(t["wpm"], 15 / (29.0 / 60), places=1)
        self.assertEqual(t["hook_words"], 8)
        self.assertEqual(t["hook_seconds"], 1.5)
        self.assertAlmostEqual(t["cuts_per_min"], 30.0, places=1)
        self.assertEqual(f["weekday"], (NOW - timedelta(days=59)).strftime("%a"))
        self.assertEqual(f["caption_head"], p["caption"][:300])

    def test_thin_transcript_falls_back_to_caption(self):
        p = post(2, caption="Big claim here.\nProof line.\nP.S. Comment GUIDE → https://x.co #ai")
        f = features.build_features(p, {"status": "ok", "duration_s": 12.0, "cuts": 0},
                                    {"text": "music", "captions": tokens((" music", 0, 500))})
        self.assertEqual(f["source"], "caption")
        self.assertIsNone(f["tempo"]["wpm"])
        self.assertTrue(f["tempo"]["has_ps"])
        self.assertTrue(f["tempo"]["has_link"])
        self.assertEqual(f["tempo"]["arrows"], 1)
        self.assertEqual(f["tempo"]["hashtags"], 1)
        self.assertEqual(f["length_bucket"], "under_15s")

    def test_cta_detection(self):
        ctas = features.detect_ctas("Big list.\n\nRepost ♻️ to help someone.\nP.S. Which one first?", "")
        self.assertTrue(ctas["cta_share"])
        self.assertTrue(ctas["cta_question"])
        self.assertFalse(ctas["cta_link"])
        self.assertFalse(ctas["cta_comment_keyword"])
        ctas = features.detect_ctas("Comment GUIDE and I'll send it. Follow for more. Guide → https://lnkd.in/x", "")
        self.assertTrue(ctas["cta_comment_keyword"] and ctas["cta_follow"] and ctas["cta_link"])
        self.assertEqual(ctas["cta_count"], 3)
        self.assertFalse(features.detect_ctas("I comment on this daily.", "")["cta_comment_keyword"])

    def test_text_length_buckets(self):
        self.assertEqual(features.build_features(post(3, fmt="text", caption="x." * 100), None, None)["length_bucket"], "short")
        self.assertEqual(features.build_features(post(3, fmt="text", caption="x " * 400), None, None)["length_bucket"], "medium")
        self.assertEqual(features.build_features(post(3, fmt="text", caption="x " * 700), None, None)["length_bucket"], "long")

    def test_run_writes_features(self):
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            write(w / "posts.json", {"platform": "linkedin", "handle": "h", "pulled_at": NOW.isoformat(),
                                     "posts": [post(1, fmt="text", platform="linkedin")]})
            out = features.run(w)
            self.assertIn("p1", out)
            self.assertEqual(read(w / "features.json")["p1"]["source"], "caption")


# ---------------------------------------------------------------------------
# outliers
# ---------------------------------------------------------------------------


class Outliers(unittest.TestCase):
    def _work(self, posts, d):
        w = Path(d)
        write(w / "posts.json", {"platform": "instagram", "handle": "h", "pulled_at": NOW.isoformat(), "posts": posts})
        return w

    def test_bands_and_metric(self):
        posts = [post(i) for i in range(40)]
        posts[5]["metrics"]["views"] = 5000
        posts[6]["metrics"]["views"] = 200
        posts.append(post(99, views=100, days_ago=1))
        with tempfile.TemporaryDirectory() as d:
            out = outliers.run(self._work(posts, d))
            self.assertEqual(out["metric"], "views")
            bands = {k: v["band"] for k, v in out["posts"].items()}
            self.assertEqual(bands["p5"], "outlier")
            self.assertEqual(bands["p6"], "dud")
            self.assertEqual(bands["p10"], "normal")
            self.assertEqual(bands["p99"], "climbing")
            self.assertAlmostEqual(out["posts"]["p5"]["multiple"], 5.0, places=1)

    def test_likes_and_shares_secondary(self):
        posts = [post(i, views=None, likes=100, shares=10, fmt="image", platform="linkedin") for i in range(20)]
        posts[3]["metrics"]["shares"] = 30
        with tempfile.TemporaryDirectory() as d:
            out = outliers.run(self._work(posts, d))
            self.assertEqual(out["metric"], "likes")
            self.assertEqual(out["secondary_metric"], "shares")
            self.assertEqual(out["posts"]["p3"]["band"], "outlier")

    def test_rolling_baseline_follows_account_growth(self):
        posts = [post(i, views=100 if i < 20 else 1000) for i in range(40)]
        with tempfile.TemporaryDirectory() as d:
            out = outliers.run(self._work(posts, d))
            self.assertEqual(out["posts"]["p2"]["band"], "normal")
            self.assertEqual(out["posts"]["p37"]["band"], "normal")
            self.assertEqual(out["posts"]["p2"]["baseline"], 100)

    def test_formats_filter_and_missing_metric(self):
        posts = [post(i) for i in range(12)]
        posts.append(post(50, fmt="carousel"))
        posts[0]["metrics"]["views"] = None
        posts[0]["metrics"]["likes"] = None
        with tempfile.TemporaryDirectory() as d:
            out = outliers.run(self._work(posts, d), formats={"video"})
            self.assertEqual(out["posts"]["p50"]["band"], "excluded")
            self.assertEqual(out["posts"]["p0"]["band"], "no_metric")

    def test_band_rule(self):
        self.assertEqual(outliers.classify_band(1.6, None, 100, 1.5, 0.5, 72), "outlier")
        self.assertEqual(outliers.classify_band(1.0, 2.1, 100, 1.5, 0.5, 72), "outlier")
        self.assertEqual(outliers.classify_band(0.4, None, 100, 1.5, 0.5, 72), "dud")
        self.assertEqual(outliers.classify_band(3.0, None, 10, 1.5, 0.5, 72), "climbing")
        self.assertEqual(outliers.classify_band(1.0, None, None, 1.5, 0.5, 72), "normal")


# ---------------------------------------------------------------------------
# classify (fake Jev)
# ---------------------------------------------------------------------------


class FakeJev:
    PRICE_PER_INPUT_TOKEN_USD = 0.042 / 1_000_000
    MODEL_PIN = "jev-1.13.0"

    class JevError(Exception):
        pass

    class JevDisabled(JevError):
        pass

    def __init__(self, low_conf=("hook_type",)):
        self.calls = []
        self.low_conf = set(low_conf)

    def estimate_tokens(self, state, questions):
        return 1000

    def validate_form(self, form):
        return form

    def _answer(self, qid, q):
        if q["type"] == "choice":
            opts = list(q["criteria"])
            conf = 0.3 if qid in self.low_conf else 0.9
            return {"type": "choice", "choice": opts[0], "probabilities": {opts[0]: 0.9}, "confidence": conf}
        if q["type"] == "score":
            return {"type": "score", "score": 1.8, "probabilities": {}, "confidence": 0.8}
        return {"type": "noul", "noul": 0.8}

    def decide_many(self, rows, questions, *, workers=8, **kw):
        out = []
        for state in rows:
            self.calls.append((kw.get("decision_id"), state, questions))
            out.append(SimpleNamespace(answers={k: self._answer(k, q) for k, q in questions.items()},
                                       usage={"input_tokens": 1000, "cost": 0.000042}, latency_ms=5.0,
                                       provider="typesafe", request_id="r", model="jev-1.13.0"))
        return out


def classify_work(d) -> Path:
    w = Path(d)
    p = post(1)
    caps = tokens((" Most", 0, 200), (" people", 200, 400), (" fail", 400, 600), (" at", 600, 650),
                  (" this.", 650, 700), (" Here's", 1000, 1200), (" why.", 1200, 1500),
                  (" Follow", 9000, 9200), (" now.", 9200, 9500))
    f = features.build_features(p, {"status": "ok", "duration_s": 10.0, "cuts": 2}, {"text": "x", "captions": caps})
    assert f["source"] == "transcript"
    write(w / "features.json", {"p1": f})
    write(w / "topics.json", {"topics": {"sales": "Selling and closing.", "offers": "Building offers."}})
    return w


class Classify(unittest.TestCase):
    def test_labels_topic_injection_and_unclear(self):
        with tempfile.TemporaryDirectory() as d:
            w = classify_work(d)
            jev = FakeJev()
            out = classify.run(w, jev=jev)
            post_calls = [c for c in jev.calls if c[0] == "creator.post.v1"]
            self.assertEqual(len(post_calls), 1)
            state, questions = post_calls[0][1], post_calls[0][2]
            self.assertEqual(set(state), {"platform", "format", "length_bucket", "hook_text", "opening_text",
                                          "body_text", "ending_text", "caption_head"})
            self.assertEqual(list(questions["topic"]["criteria"])[:2], ["sales", "offers"])
            self.assertEqual(list(questions["topic"]["criteria"])[-2:], ["other", "cannot_tell"])
            labels = read(w / "labels.json")
            self.assertEqual(labels["posts"]["p1"]["hook_type"]["value"], "unclear")
            self.assertEqual(labels["posts"]["p1"]["hook_type"]["raw"], "curiosity_gap")
            self.assertEqual(labels["posts"]["p1"]["structure"]["value"], "list_steps")
            self.assertTrue(labels["posts"]["p1"]["payoff_delivered"]["flag"])
            self.assertEqual(len(labels["sentences"]["p1"]), 3)
            self.assertEqual(labels["sentences"]["p1"][0]["role"]["value"], "hook")
            sent_calls = [c for c in jev.calls if c[0] == "creator.sentence.v1"]
            self.assertEqual(set(sent_calls[0][1]), {"position", "sentence", "previous_sentence", "next_sentence"})
            self.assertEqual(sent_calls[0][1]["previous_sentence"], "")
            self.assertGreater(out["cost_usd"], 0)

    def test_rerun_uses_cache(self):
        with tempfile.TemporaryDirectory() as d:
            w = classify_work(d)
            classify.run(w, jev=FakeJev())
            jev = FakeJev()
            classify.run(w, jev=jev)
            self.assertEqual(jev.calls, [])

    def test_cost_cap_and_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            w = classify_work(d)
            with self.assertRaises(classify.CostCapExceeded):
                classify.run(w, jev=FakeJev(), max_usd=0.00001)
            jev = FakeJev()
            plan = classify.run(w, jev=jev, dry_run=True)
            self.assertEqual(jev.calls, [])
            self.assertEqual(plan["post_calls"], 1)
            self.assertEqual(plan["sentence_calls"], 3)
            self.assertGreater(plan["est_usd"], 0)
            self.assertFalse((w / "labels.json").exists())

    def test_missing_topics(self):
        with tempfile.TemporaryDirectory() as d:
            w = classify_work(d)
            (w / "topics.json").unlink()
            with self.assertRaises(classify.SetupError):
                classify.run(w, jev=FakeJev())

    def test_untrusted_text_is_redacted(self):
        state = classify.build_post_state({
            "platform": "instagram", "format": "video", "length_bucket": "under_15s",
            "segments": {"hook_text": "Email me at a@b.org", "opening_text": "", "body_text": "see https://x.co/y",
                         "ending_text": ""}, "caption_head": "call 0412 345 678"})
        self.assertNotIn("a@b.org", json.dumps(state))
        self.assertNotIn("https://x.co/y", json.dumps(state))
        self.assertNotIn("0412 345 678", json.dumps(state))


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------


class PatternMaths(unittest.TestCase):
    def test_spearman(self):
        self.assertAlmostEqual(patterns.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]), 1.0)
        self.assertAlmostEqual(patterns.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)
        self.assertIsNone(patterns.spearman([1, 2, 3], [1, 2, 3]))
        self.assertIsNone(patterns.spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]))
        self.assertAlmostEqual(patterns.spearman([1, 2, 2, 3, 4], [1, 2, 3, 4, 5]), 0.9747, places=3)

    def test_collapse_roles(self):
        self.assertEqual(patterns.collapse_roles(["hook", "hook", "claim", "unclear", "evidence", "evidence", "cta"]),
                         ["hook", "claim", "evidence", "cta"])

    def test_lift_table(self):
        rows = ([{"band": "outlier", "multiple": 3.0, "hook_type": "result"}] * 3
                + [{"band": "normal", "multiple": 1.0, "hook_type": "result"}] * 2
                + [{"band": "normal", "multiple": 1.0, "hook_type": "story"}] * 3
                + [{"band": "dud", "multiple": 0.3, "hook_type": "story"}] * 2)
        table = patterns.lift_table(rows, "hook_type", min_n=5)
        top = table[0]
        self.assertEqual(top["value"], "result")
        self.assertEqual(top["n"], 5)
        self.assertEqual(top["outliers"], 3)
        self.assertAlmostEqual(top["outlier_rate"], 0.6)
        self.assertAlmostEqual(top["lift"], 2.0)
        self.assertEqual(top["tier"], "pattern")
        story = [r for r in table if r["value"] == "story"][0]
        self.assertAlmostEqual(story["dud_rate"], 0.4)
        self.assertEqual(patterns.lift_table(rows, "hook_type", min_n=6)[0]["tier"], "hunch")


def full_work(d) -> Path:
    """Twelve labelled posts with features and outliers: enough for every patterns.py section."""
    w = Path(d)
    posts, feats, bands, post_labels, sent_labels = [], {}, {}, {}, {}
    for i in range(12):
        p = post(i, caption=f"Hook {i} <script>alert(1)</script>.\nBody line.\nEnd line?")
        posts.append(p)
        is_out = i < 4
        sents = [{"i": 0, "text": f"Hook {i}.", "position": "hook", "start_s": 0.0, "end_s": 1.0, "words": 2},
                 {"i": 1, "text": "Claim.", "position": "opening", "start_s": 1.5, "end_s": 2.0, "words": 1},
                 {"i": 2, "text": "Proof.", "position": "body", "start_s": 5.0, "end_s": 6.0, "words": 1},
                 {"i": 3, "text": "Follow.", "position": "ending", "start_s": 28.0, "end_s": 29.0, "words": 1}]
        feats[p["post_id"]] = {"post_id": p["post_id"], "platform": "instagram", "format": "video",
                               "weekday": "Mon", "length_bucket": "30_to_60s", "source": "transcript",
                               "sentences": sents, "caption_head": p["caption"][:300],
                               "segments": {"hook_text": f"Hook {i}.", "opening_text": "Claim.", "body_text": "Proof.",
                                            "ending_text": "Follow."},
                               "tempo": {"wpm": 200 if is_out else 140, "cuts_per_min": 30 if is_out else 10,
                                         "hook_seconds": 1.0, "words": 5, "sentences": 4, "duration_s": 30.0}}
        bands[p["post_id"]] = {"value": 3000 if is_out else 1000, "baseline": 1000, "multiple": 3.0 if is_out else 1.0,
                               "band": "outlier" if is_out else ("dud" if i > 9 else "normal"), "age_h": 500}
        hook = "result" if i % 2 == 0 else "story"
        post_labels[p["post_id"]] = {
            "hook_type": {"value": hook, "confidence": 0.9}, "structure": {"value": "list_steps", "confidence": 0.9},
            "topic": {"value": "sales", "confidence": 0.9}, "evidence": {"value": "personal_result", "confidence": 0.9},
            "emotion": {"value": "curiosity", "confidence": 0.9}, "advice": {"value": "steps", "confidence": 0.9},
            "identity": {"value": "established_owner", "confidence": 0.9}, "ending": {"value": "follow_cta", "confidence": 0.9},
            "payoff_delivered": {"value": 0.8, "flag": True}, "specificity": {"value": 1.8, "level": 2, "confidence": 0.8}}
        roles = ["hook", "claim", "evidence", "cta"] if is_out else ["hook", "setup", "setup", "cta"]
        sent_labels[p["post_id"]] = [{"i": j, "role": {"value": r, "confidence": 0.9},
                                      "device": {"value": "number", "confidence": 0.9}} for j, r in enumerate(roles)]
    write(w / "posts.json", {"platform": "instagram", "handle": "example_creator", "pulled_at": NOW.isoformat(), "posts": posts})
    write(w / "features.json", feats)
    write(w / "outliers.json", {"metric": "views", "secondary_metric": None, "hi": 1.5, "lo": 0.5, "min_age_hours": 72,
                                "baseline": {"global_median": 1000, "method": "rolling"}, "posts": bands})
    write(w / "labels.json", {"model": "jev-1.13.0", "posts": post_labels, "sentences": sent_labels,
                              "calls": 60, "cost_usd": 0.01, "errors": []})
    return w


class PatternChecks(unittest.TestCase):
    def test_idea_key(self):
        self.assertEqual(patterns.idea_key("Three ways to (finally) fix your morning routine."),
                         patterns.idea_key("Three ways to (finally) fix your morning routine"))

    def test_repeats_and_outside_shape(self):
        with tempfile.TemporaryDirectory() as d:
            w = full_work(d)
            feats = read(w / "features.json")
            for pid in ("p0", "p1", "p2"):
                feats[pid]["segments"]["hook_text"] = "Same idea posted again and again here today."
            write(w / "features.json", feats)
            out = patterns.run(w, min_n=3)
            self.assertEqual(out["repeats"][0]["posts"], 3)
            hook = out["lifts"]["hook_type"][0]
            self.assertLess(hook["outlier_ideas"], hook["outliers"] + 1)
            self.assertIn("outside_top_shape", hook)


class Tiers(unittest.TestCase):
    def test_split_and_graduation(self):
        import random
        random.seed(3)
        posts = []
        for i in range(60):
            trial = i % 2 == 0
            views = int(random.lognormvariate(8.5, 0.5)) if trial else int(random.lognormvariate(13.0, 0.4))
            p = post(i, views=views, days_ago=40 - i // 2)
            idea = i // 2 if i < 40 else i
            p["caption"] = f"Idea alpha{idea} beta{idea} gamma{idea} delta{idea} selling."
            posts.append(p)
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            write(w / "posts.json", {"platform": "instagram", "handle": "h", "pulled_at": NOW.isoformat(), "posts": posts})
            out = outliers.run(w)
            self.assertIsNotNone(out["tiers"])
            self.assertEqual({out["posts"]["p0"]["tier"], out["posts"]["p1"]["tier"]}, {"low", "high"})
            self.assertNotEqual(out["posts"]["p1"]["band"], "outlier")  # judged against its own tier
            feats = {p["post_id"]: features.build_features(p, None, None) for p in posts}
            write(w / "features.json", feats)
            lab = {"value": "result", "confidence": 0.9}
            write(w / "labels.json", {"posts": {p["post_id"]: {"hook_type": lab} for p in posts}, "sentences": {}})
            res = patterns.run(w, min_n=3)
            grad = res["graduation"]
            self.assertEqual(grad["promoted"], 20)
            self.assertGreaterEqual(grad["ideas"], 20)
            self.assertIn("hook_type", grad["lifts"])

    def test_one_population_does_not_split(self):
        self.assertIsNone(outliers.split_tiers([1000 + i * 7 for i in range(60)]))


class Buckets(unittest.TestCase):
    def test_ties_never_split_by_outcome(self):
        pairs = [(0, 1.0, "outlier")] * 10 + [(0, 0.0, "normal")] * 30 + [(2.0, 1.0, "outlier")] * 20 + [(5.0, 0.0, "normal")] * 20
        buckets = patterns.value_buckets(pairs)
        zero = buckets[0]
        self.assertEqual((zero["min"], zero["max"], zero["n"]), (0, 0, 40))
        self.assertAlmostEqual(zero["outlier_rate"], 0.25)


class PatternsRun(unittest.TestCase):
    def test_sections(self):
        with tempfile.TemporaryDirectory() as d:
            w = full_work(d)
            out = patterns.run(w, min_n=3)
            self.assertEqual(set(out) >= {"overall", "lifts", "combos", "tempo", "sentences", "top_outliers", "top_duds"}, True)
            self.assertEqual(out["overall"]["n"], 12)
            self.assertAlmostEqual(out["overall"]["outlier_rate"], 4 / 12)
            self.assertIn("hook_type", out["lifts"])
            self.assertGreater(out["tempo"]["wpm"]["spearman"], 0.5)
            grams = {tuple(g["sequence"]): g for g in out["sentences"]["ngrams"]}
            self.assertIn(("claim", "evidence"), grams)
            self.assertGreater(grams[("claim", "evidence")]["lift"], 1.0)
            self.assertEqual(out["top_outliers"][0]["band"], "outlier")
            self.assertTrue((w / "patterns.json").exists())


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


class Report(unittest.TestCase):
    def test_renders_without_playbook_and_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            w = full_work(d)
            patterns.run(w, min_n=3)
            html = report.render(w, None, "Example Teardown")
            self.assertIn("<title>Example Teardown</title>", html)
            self.assertIn("Playbook not written yet", html)
            self.assertIn(":root", html)
            self.assertIn("prefers-color-scheme", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertNotIn("<script src", html)
            self.assertNotIn("<html", html.lower())

    def test_renders_playbook(self):
        with tempfile.TemporaryDirectory() as d:
            w = full_work(d)
            patterns.run(w, min_n=3)
            playbook = {"headline": "Results hooks win.",
                        "picture": {"hook": ["Lead with a number"], "argument": ["Claim then proof"],
                                    "ending": ["Follow ask"], "tempo": ["200 wpm"]},
                        "rules": [], "hook_templates": [], "skeletons": [], "script_templates": [],
                        "rebuilds": [{"source_post_id": "p0", "title": "My rebuild", "format": "reel",
                                      "draft": "Line one.\nLine two.", "notes": []}],
                        "red_team": [], "limits": []}
            html = report.render(w, playbook, "Example Teardown")
            self.assertIn("Lead with a number", html)
            self.assertIn("My rebuild", html)
            self.assertNotIn("Playbook not written yet", html)


# ---------------------------------------------------------------------------
# agree (golden-set seed)
# ---------------------------------------------------------------------------


class Agree(unittest.TestCase):
    def test_agreement_and_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            w = full_work(d)
            with (w / "claude_labels.jsonl").open("w") as f:
                f.write(json.dumps({"post_id": "p0", "labels": {"hook_type": "result", "structure": "story_arc"}}) + "\n")
                f.write(json.dumps({"post_id": "p1", "labels": {"hook_type": "story", "structure": "list_steps"}}) + "\n")
            cand = Path(d) / "candidates.jsonl"
            out = agree.run(w, candidates_path=cand)
            self.assertAlmostEqual(out["by_question"]["hook_type"], 1.0)
            self.assertAlmostEqual(out["by_question"]["structure"], 0.5)
            self.assertEqual(out["n"], 2)
            agree.run(w, candidates_path=cand)
            rows = [json.loads(x) for x in cand.read_text().splitlines() if x.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["source"], "claude-blind")
            self.assertIn("hook_text", rows[0]["state"])
            self.assertTrue((w / "agreement.json").exists())


# ---------------------------------------------------------------------------
# media (injected download / transcribe / cut counter)
# ---------------------------------------------------------------------------


class Media(unittest.TestCase):
    def test_scene_cut_parse(self):
        stderr = ("[Parsed_showinfo_1 @ 0x1] n:   0 pts:  1000 pts_time:1.0 duration...\n"
                  "frame= 10\n[Parsed_showinfo_1 @ 0x1] n:   1 pts:  5000 pts_time:5.0 ...\n")
        self.assertEqual(media.scene_cuts_from_ffmpeg(stderr), 2)

    def test_download_command(self):
        self.assertIsNone(media.download_command({"media_url": "https://cdn/x.mp4", "url": "u"}, Path("/tmp/a")))
        cmd = media.download_command({"media_url": None, "url": "https://www.tiktok.com/@h/video/1"}, Path("/tmp/a"))
        self.assertEqual(cmd[0], "yt-dlp")
        self.assertIn("https://www.tiktok.com/@h/video/1", cmd)

    def test_run_with_fakes(self):
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            ok, bad, img = post(1), post(2), post(3, fmt="image")
            write(w / "posts.json", {"platform": "instagram", "handle": "h", "pulled_at": NOW.isoformat(),
                                     "posts": [ok, bad, img]})

            def downloader(p, dest_dir):
                if p["post_id"] == "p2":
                    raise RuntimeError("403")
                f = dest_dir / "media.mp4"
                f.write_bytes(b"x")
                return f

            def transcriber(path, out_json):
                Path(out_json).write_text(json.dumps({"text": "hi", "captions": tokens((" hi.", 0, 300))}))

            out = media.run(w, downloader=downloader, transcriber=transcriber,
                            probe=lambda path: (31.5, 7))
            self.assertEqual(out["p1"]["status"], "ok")
            self.assertEqual(out["p1"]["duration_s"], 31.5)
            self.assertEqual(out["p1"]["cuts"], 7)
            self.assertTrue(Path(out["p1"]["transcript_path"]).exists())
            self.assertEqual(out["p2"]["status"], "download_failed")
            self.assertIn("403", out["p2"]["error"])
            self.assertEqual(out["p3"]["status"], "text_only")
            self.assertTrue((w / "media.json").exists())
            calls = []
            media.run(w, downloader=lambda p, dd: calls.append(p["post_id"]), transcriber=transcriber,
                      probe=lambda path: (1.0, 0))
            self.assertNotIn("p1", calls)  # resumable: ok posts are skipped


class ReportV2(unittest.TestCase):
    def page(self, directory, playbook):
        work = full_work(directory)
        patterns.run(work, min_n=3)
        return report.render(work, playbook, "Creator teardown")

    def test_tabs_are_in_order_and_start_first(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d, {})
            ids = ("start", "wins", "build", "best", "yours", "sure", "data")
            positions = [page.index(f'id="tab-{tab_id}"') for tab_id in ids]
            self.assertEqual(positions, sorted(positions))
            self.assertEqual(page.count('role="tabpanel"'), 7)
            self.assertIn('<section class="tab-panel" id="start"', page)
            self.assertIn('id="tab-start" data-tab="start" aria-controls="start" aria-selected="true"', page)
            self.assertLess(page.index('id="start" data-tab="start"'), page.index('id="wins" data-tab="wins"'))

    def test_finding_shows_numbers_and_chart(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d, {"findings": [{"title": "The list wins", "plain": "People save it.",
                                                "number_line": "3 of 4 took off", "numbers": {"hits": 3, "n": 4, "base": 0.25},
                                                "confidence": "strong"}]})
            wins = page.split('id="wins" data-tab="wins"', 1)[1].split('id="build" data-tab="build"', 1)[0]
            self.assertIn("The list wins", wins)
            self.assertIn("3 of 4 took off", wins)
            self.assertIn("<svg", wins)

    def test_best_post_uses_referenced_opening_line(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d, {"best_posts": [{"post_id": "p0", "why": "It worked.", "borrow": "Try it."}]})
            best = page.split('id="best" data-tab="best"', 1)[1].split('id="yours" data-tab="yours"', 1)[0]
            work = Path(d)
            expected = read(work / "features.json")["p0"]["segments"]["hook_text"]
            self.assertIn(expected, best)
            self.assertIn("https://example.com/p0", best)

    def test_missing_playbook_keeps_all_guided_tabs(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d, None)
            ids = ("start", "wins", "build", "best", "yours", "sure", "data")
            self.assertEqual(page.count('role="tabpanel"'), len(ids))
            self.assertGreaterEqual(page.count("Not written yet"), 6)

    def test_raw_data_keeps_chart_and_every_post(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d, None)
            raw = page.split('id="data" data-tab="data"', 1)[1]
            self.assertIn("<svg", raw)
            self.assertEqual(raw.count("<details>"), len(read(Path(d) / "posts.json")["posts"]))


class ReportV3(unittest.TestCase):
    def page(self, directory, playbook=None):
        work = full_work(directory)
        patterns.run(work, min_n=3)
        return report.render(work, playbook, "Creator teardown")

    def test_header_tiles_and_cost(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d)
            header = page.split('</header>', 1)[0]
            self.assertEqual(header.count('class="stat'), 6)
            self.assertIn('US$', header)
            work = Path(d)
            data = read(work / 'patterns.json')
            data['graduation'] = {'promoted': 36, 'ideas': 127, 'lifts': {}}
            write(work / 'patterns.json', data)
            header = report.render(work, None, 'Creator teardown').split('</header>', 1)[0]
            self.assertEqual(header.count('class="stat'), 7)
            self.assertIn('36 of 127', header)

    def test_byline_brand_and_footer(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d)
            header = page.split('</header>', 1)[0]
            self.assertIn('class="byline"', header)
            self.assertIn('Prepared ', header)
            footer = page.split('<footer', 1)[1].split('</footer>', 1)[0]
            self.assertIn('Jev', footer)
            work = Path(d)
            pinned = report.render(work, None, 'Creator teardown', prepared='2026-10-12')
            self.assertIn('Prepared 12 October 2026', pinned)
            brand = report.load_brand()
            if brand['name']:
                self.assertIn(f'by <a href="{brand["url"]}">{brand["name"]}</a>', pinned)

    def test_audience_modes(self):
        with tempfile.TemporaryDirectory() as d:
            self.page(d)
            work = Path(d)
            rebuild = {'rebuilds': [{'source_post_id': 'p0', 'title': 'A version', 'draft': 'Draft line'}]}
            mine = report.render(work, dict(rebuild, audience={'mode': 'me', 'brand': 'brand-a'}), 'Creator teardown')
            self.assertIn('id="tab-yours"', mine)
            self.assertIn('Copy this', mine)
            client = report.render(work, dict(rebuild, audience={'mode': 'client', 'name': 'Client Co'}), 'Creator teardown')
            self.assertIn('id="tab-yours"', client)
            self.assertNotIn(' for Client Co', client.split('</header>', 1)[0])  # one byline for every run
            creator = report.render(work, {'audience': {'mode': 'creator', 'name': 'The Creator'}}, 'Creator teardown')
            self.assertNotIn('id="tab-yours"', creator)
            self.assertNotIn('id="yours"', creator)
            self.assertIn('Your best posts', creator)
            self.assertIn('Keep doing this', creator)
            self.assertNotIn(' for The Creator', creator.split('</header>', 1)[0])
            self.assertEqual(report.audience_of({'audience': {'mode': 'odd'}})['mode'], 'me')

    def test_two_channels_share_one_header(self):
        import shutil
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            self.page(d)
            second = Path(e) / 'work'
            shutil.copytree(d, second)
            data = read(second / 'posts.json')
            data['platform'], data['handle'] = 'youtube', 'SecondHandle'
            write(second / 'posts.json', data)
            page = report.render(Path(d), None, 'Creator teardown', also=[(second, None)])
            header = page.split('</header>', 1)[0]
            self.assertEqual(header.count('class="channel-switch"'), 2)
            self.assertIn('data-channel-only="youtube" hidden', header)
            self.assertIn('id="start-youtube" data-tab="start" data-channel="youtube"', page)
            self.assertIn('id="wins-instagram"', page)
            self.assertIn('Posts analysed', header)
            self.assertNotIn('class="channel-icon"', header)
            single = report.render(Path(d), None, 'Creator teardown')
            self.assertIn('class="channel-icon"', single.split('</header>', 1)[0])
            self.assertIn('id="start" data-tab="start"', single)

    def test_clock_and_day_text(self):
        self.assertEqual(report.clock(147.002676), '2:27')
        self.assertEqual(report.clock(38.4), '38s')
        self.assertIsNone(report.clock(None))
        self.assertEqual(report.day_text('2026-09-21T10:00:00Z'), '21 Sep 2026')

    def test_visual_thumb_in_chart_and_analysis_media(self):
        with tempfile.TemporaryDirectory() as d:
            work = full_work(d)
            patterns.run(work, min_n=3)
            thumb = work / 'visuals' / 'thumbs' / 'p0.jpg'
            thumb.parent.mkdir(parents=True)
            thumb.write_bytes(b'fake jpeg')
            write(work / 'visuals.json', {'p0': {'thumb': 'visuals/thumbs/p0.jpg',
                                                'images': ['visuals/thumbs/p0.jpg'], 'frames': [], 'errors': []}})
            write(work / 'analyses.json', {'p0': {'hook': {'line': 'A line', 'why': 'A reason'},
                                                  'argument': {'summary': 'A point', 'beats': ['A beat']},
                                                  'ending': {'line': 'Last line', 'cta': 'Follow', 'why': 'Clear ask'}}})
            page = report.render(work, {'best_posts': [{'post_id': 'p0'}]}, 'Creator teardown')
            self.assertIn('<image href="data:image/jpeg;base64,', page)
            best = page.split('id="best" data-tab="best"', 1)[1].split('id="yours" data-tab="yours"', 1)[0]
            for heading in ('Hook', 'Argument', 'Ending'):
                self.assertIn(f'<h4>{heading}</h4>', best)
            self.assertIn('class="media-strip"', best)

    def test_oversized_visual_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            work = full_work(d)
            patterns.run(work, min_n=3)
            thumb = work / 'visuals' / 'thumbs' / 'p0.jpg'
            thumb.parent.mkdir(parents=True)
            thumb.write_bytes(b'x' * 250_001)
            write(work / 'visuals.json', {'p0': {'thumb': 'visuals/thumbs/p0.jpg'}})
            page = report.render(work, {}, 'Creator teardown')
            self.assertNotIn('data:image/jpeg;base64,', page)

    def test_picture_quote_and_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            playbook = {'picture': {'hook': [{'text': 'Lead with proof', 'tag': 'opening',
                                             'stat': {'hits': 9, 'n': 17}, 'quote_post_id': 'p0'}]},
                        'rebuilds': [{'source_post_id': 'p0', 'title': 'A version', 'draft': 'Draft line',
                                      'hook_options': ['Option one', 'Option two'], 'chosen_hook': 'Option two',
                                      'chosen_hook_why': 'Clearer'}]}
            page = self.page(d, playbook)
            self.assertIn('class="quote-chip">“Hook 0.”', page)
            yours = page.split('id="yours" data-tab="yours"', 1)[1].split('id="sure" data-tab="sure"', 1)[0]
            self.assertIn('Option one', yours)
            self.assertIn('class="hook-option chosen">Option two', yours)
            self.assertIn('>Copy</button>', yours)
            empty = self.page(d, {})
            self.assertNotIn('waiting', empty.split('id="yours" data-tab="yours"', 1)[1].split('id="sure" data-tab="sure"', 1)[0].lower())

    def test_review_and_inline_script_only(self):
        with tempfile.TemporaryDirectory() as d:
            page = self.page(d, {'review': [{'role': 'Hook check', 'verdict': 'pass', 'summary': 'Clear',
                                              'items': [{'claim': 'It opens well', 'verdict': 'pass', 'note': 'Yes'}]},
                                             {'role': 'Truth check', 'verdict': 'flagged', 'summary': 'Check source'}]})
            review = page.split('id="sure" data-tab="sure"', 1)[1].split('id="data" data-tab="data"', 1)[0]
            self.assertIn('Hook check', review)
            self.assertIn('Truth check', review)
            self.assertIn('flagged', review)
            self.assertNotIn('<script src', page)
            self.assertNotIn('\u2014', page)


if __name__ == "__main__":
    unittest.main()

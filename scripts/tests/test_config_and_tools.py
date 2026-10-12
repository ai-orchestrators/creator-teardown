"""Config loading, the report's config-driven parts, the transcriber, the lint and every CLI.

Offline and key-free: config/ is a temp folder per test, keys are stripped from the environment,
and subprocesses only run this repo's own scripts with --help or --dry-run.
"""
from __future__ import annotations

import atexit
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
_CONFIG = tempfile.mkdtemp(prefix="ct-config-")
atexit.register(shutil.rmtree, _CONFIG, True)
os.environ["CREATOR_TEARDOWN_CONFIG"] = _CONFIG

import check_setup  # noqa: E402
import common  # noqa: E402
import lint_report  # noqa: E402
import media  # noqa: E402
import patterns  # noqa: E402
import report  # noqa: E402
import scrape  # noqa: E402
from test_pipeline import classify_work, full_work  # noqa: E402

KEYS = ("APIFY_TOKEN", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "YOUTUBE_API_KEY")
PIXEL = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                      "1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082")


class ConfigCase(unittest.TestCase):
    def setUp(self):
        self.config = Path(tempfile.mkdtemp(prefix="ct-cfg-"))
        self.addCleanup(shutil.rmtree, self.config, True)
        env = {k: v for k, v in os.environ.items() if k not in KEYS}
        env["CREATOR_TEARDOWN_CONFIG"] = str(self.config)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, payload):
        path = self.config / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return path


class Settings(ConfigCase):
    def test_defaults_without_config(self):
        settings = common.load_settings()
        self.assertEqual(settings["currency"]["code"], "USD")
        self.assertEqual(settings["apify_max_cost_usd"], 5.0)
        self.assertEqual(settings["spelling"], "as-is")
        self.assertEqual(settings["transcriber"]["binary"], "whisper-cli")
        self.assertEqual(common.config_dir(), self.config)

    def test_partial_settings_merge(self):
        self.write("settings.json", {"platforms": ["linkedin"], "currency": {"code": "AUD", "usd_rate": 1.5},
                                     "transcriber": {"model": "~/models/ggml-base.en.bin"}})
        settings = common.load_settings()
        self.assertEqual(settings["platforms"], ["linkedin"])
        self.assertEqual(settings["currency"]["usd_rate"], 1.5)
        self.assertEqual(settings["transcriber"]["binary"], "whisper-cli")
        self.assertEqual(settings["transcriber"]["model"], "~/models/ggml-base.en.bin")

    def test_bad_settings_name_the_fix(self):
        self.write("settings.json", "{not json")
        with self.assertRaises(common.ConfigError) as caught:
            common.load_settings()
        self.assertIn("settings.json", str(caught.exception))
        for bad in ({"platforms": ["myspace"]}, {"currency": {"usd_rate": 0}}, {"spelling": "pirate"},
                    {"apify_max_cost_usd": -1}):
            self.write("settings.json", bad)
            with self.assertRaises(common.ConfigError):
                common.load_settings()

    def test_brand_profiles_and_client_folder(self):
        self.assertEqual(common.brand_profiles(), {})
        self.write("profile.md", "# Default brand")
        (self.config / "profiles").mkdir()
        (self.config / "profiles" / "side-project.md").write_text("# Second brand")
        self.assertEqual(sorted(common.brand_profiles()), ["default", "side-project"])
        self.assertIsNone(common.load_settings()["client_files_dir"])
        self.write("settings.json", {"client_files_dir": str(self.config / "no-such-folder")})
        notes = check_setup.run()["notes"]
        self.assertTrue(any("client_files_dir" in note for note in notes))
        self.assertEqual(check_setup.run()["brand_profiles"], ["default", "side-project"])
        self.write("settings.json", {"client_files_dir": 7})
        with self.assertRaises(common.ConfigError):
            common.load_settings()

    def test_env_file_fills_but_never_overrides(self):
        self.write(".env", "# comment\nexport APIFY_TOKEN='apify-test-value'\nTYPESAFE_API_KEY=\"from-file\"\nBROKEN LINE\n")
        os.environ["TYPESAFE_API_KEY"] = "from-shell"
        loaded = common.load_env()
        self.assertEqual(loaded, ["APIFY_TOKEN"])
        self.assertEqual(os.environ["APIFY_TOKEN"], "apify-test-value")
        self.assertEqual(os.environ["TYPESAFE_API_KEY"], "from-shell")

    def test_money(self):
        self.assertEqual(common.format_money(0.1234), "US$0.12")
        self.assertEqual(common.format_money(0.1, {"code": "AUD", "usd_rate": 1.5}), "A$0.15 (US$0.10)")
        self.assertEqual(common.format_money(1, {"code": "GBP", "symbol": "£", "usd_rate": 0.8}), "£0.80 (US$1.00)")
        self.assertEqual(common.format_money(1, {"code": "ZAR", "usd_rate": 18}), "ZAR 18.00 (US$1.00)")


class Brand(ConfigCase):
    def page(self, playbook=None, **kw):
        work = full_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        patterns.run(work, min_n=3)
        return report.render(work, playbook, "Example Teardown", **kw)

    def test_no_brand_means_date_only_byline(self):
        brand = common.load_brand()
        self.assertEqual((brand["name"], brand["url"], brand["logo"]), ("", "", ""))
        header = self.page(prepared="2026-10-12").split("</header>", 1)[0]
        byline = header.split('class="byline"', 1)[1].split("</p>", 1)[0]
        self.assertIn("Prepared 12 October 2026", byline)
        self.assertNotIn(" by ", byline)
        self.assertIn("Labelled by Jev", header)
        self.assertNotIn("<img", header.split('class="stat cost"', 1)[1])

    def test_brand_from_config(self):
        (self.config / "logo.png").write_bytes(PIXEL)
        self.write("brand.json", {"name": "Example Studio", "url": "https://example.com", "logo": "logo.png"})
        brand = common.load_brand()
        self.assertTrue(brand["logo"].startswith("data:image/png;base64,"))
        page = self.page(prepared="2026-10-12")
        self.assertIn('Prepared 12 October 2026 by <a href="https://example.com">Example Studio</a>', page)
        footer = page.split("<footer", 1)[1]
        self.assertIn("Example Studio", footer)
        self.assertIn("data:image/png;base64,", footer)
        self.assertIn('class="menu-foot"', page)

    def test_missing_logo_file_is_skipped(self):
        self.write("brand.json", {"name": "Example Studio", "logo": "nowhere.png"})
        self.assertEqual(common.load_brand()["logo"], "")

    def test_currency_and_spelling_from_settings(self):
        page = self.page()
        cost = page.split('class="stat cost"', 1)[1].split("</div>", 1)[0]
        self.assertIn("US$0.01", cost)
        self.assertNotIn("A$", page)
        self.write("settings.json", {"currency": {"code": "AUD", "usd_rate": 1.5}, "spelling": "au"})
        page = self.page({"headline": "They organize every post by color."})
        cost = page.split('class="stat cost"', 1)[1].split("</div>", 1)[0]
        self.assertIn("A$0.01", cost)
        self.assertIn("(US$0.01)", cost)
        self.assertIn('data-rate="1.5"', cost)
        self.assertIn("They organise every post by colour.", page)


    def test_two_channels_cost_in_configured_currency(self):
        self.write("settings.json", {"currency": {"code": "AUD", "usd_rate": 1.5}})
        first = full_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        patterns.run(first, min_n=3)
        second = Path(tempfile.mkdtemp(prefix="ct-work-", dir=self.config)) / "work"
        shutil.copytree(first, second)
        data = json.loads((second / "posts.json").read_text())
        data["platform"] = "youtube"
        (second / "posts.json").write_text(json.dumps(data))
        page = report.render(first, None, "Example Teardown", also=[(second, None)])
        cost = page.split('class="stat cost"', 1)[1].split("</div>", 1)[0]
        self.assertIn("A$0.03", cost)
        self.assertIn("(US$0.02)", cost)
        self.assertIn("SYM=costEl?.dataset.symbol", page)
        self.assertNotIn("1.55", page.split("<script>", 1)[1])

    def test_dates_follow_the_timezone_setting(self):
        self.page()
        self.assertEqual(report.day_text("2026-09-21T20:00:00Z"), "21 Sep 2026")
        self.write("settings.json", {"timezone": "Pacific/Auckland"})
        self.page()
        self.assertEqual(report.day_text("2026-09-21T20:00:00Z"), "22 Sep 2026")
        self.write("settings.json", {"timezone": "Not/A_Zone"})
        self.page()
        self.assertEqual(report.day_text("2026-09-21T20:00:00Z"), "21 Sep 2026")

class Transcriber(ConfigCase):
    def test_whisper_tokens_become_word_captions(self):
        data = {"transcription": [
            {"offsets": {"from": 0, "to": 2000}, "text": " Most people fail.",
             "tokens": [{"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
                        {"text": " Most", "offsets": {"from": 0, "to": 300}, "p": 0.9},
                        {"text": " peo", "offsets": {"from": 300, "to": 450}, "p": 0.8},
                        {"text": "ple", "offsets": {"from": 450, "to": 600}, "p": 0.8},
                        {"text": " fail.", "offsets": {"from": 600, "to": 900}, "p": 0.9},
                        {"text": "[_TT_45]", "offsets": {"from": 900, "to": 900}}]},
            {"offsets": {"from": 2000, "to": 3000}, "text": " Here's why.", "tokens": []}]}
        out = media.captions_from_whisper(data)
        self.assertEqual([c["text"] for c in out["captions"]], [" Most", " people", " fail.", " Here's why."])
        self.assertEqual((out["captions"][1]["startMs"], out["captions"][1]["endMs"]), (300, 600))
        self.assertEqual(out["text"], "Most people fail. Here's why.")

    def test_whisper_command_and_missing_model(self):
        command = media.whisper_command(Path("/tmp/a.wav"), Path("/tmp/whisper"),
                                        {"binary": "whisper-cli", "model": "/models/ggml-base.en.bin", "language": "en"})
        self.assertEqual(command[:3], ["whisper-cli", "-m", "/models/ggml-base.en.bin"])
        self.assertIn("-ojf", command)
        self.assertEqual(command[command.index("-of") + 1], "/tmp/whisper")
        with self.assertRaises(common.ConfigError):
            media.whisper_command(Path("a.wav"), Path("w"), {"binary": "whisper-cli", "model": None})

    def test_custom_command_template(self):
        command = media.custom_command(Path("/v/media.mp4"), Path("/v/transcript.json"),
                                       {"command": ["my-tool", "--in", "{input}", "--out={output}"]})
        self.assertEqual(command, ["my-tool", "--in", "/v/media.mp4", "--out=/v/transcript.json"])


class SetupCheck(ConfigCase):
    def test_reports_presence_never_values(self):
        os.environ["APIFY_TOKEN"] = "apify-secret-value-123"
        report_data = check_setup.run()
        self.assertEqual(report_data["keys"], {"APIFY_TOKEN": True, "TYPESAFE_API_KEY": False,
                                               "OPENROUTER_API_KEY": False, "YOUTUBE_API_KEY": False})
        self.assertIn("youtube-transcript-api", report_data["optional"])
        self.assertNotIn("apify-secret-value-123", json.dumps(report_data))
        self.assertTrue(any("TYPESAFE_API_KEY" in p for p in report_data["problems"]))
        self.assertTrue(any("settings.json" in p for p in report_data["problems"]))

    def test_youtube_only_needs_no_apify(self):
        self.write("settings.json", {"platforms": ["youtube"]})
        problems = check_setup.run()["problems"]
        self.assertFalse(any("APIFY_TOKEN" in p for p in problems))


class Scrape(ConfigCase):
    def test_apify_request_is_capped_and_keeps_the_token_out_of_the_url(self):
        request = scrape.apify_request("instagram", "example_creator", 280, 4.0, "apify-test-token")
        self.assertIn("maxItems=280", request.full_url)
        self.assertIn("maxTotalChargeUsd=4.0", request.full_url)
        self.assertNotIn("apify-test-token", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer apify-test-token")
        body = json.loads(request.data)
        self.assertEqual(body["resultsLimit"], 280)
        self.assertTrue(body["directUrls"][0].endswith("/example_creator/"))

    def test_missing_token_stops_before_the_network(self):
        with mock.patch.object(scrape.urllib.request, "urlopen") as urlopen, self.assertRaises(SystemExit), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            scrape.run_apify("tiktok", "example_creator", 10, 1.0)
        self.assertIn("APIFY_TOKEN is not set", stderr.getvalue())
        urlopen.assert_not_called()

    def test_from_raw_needs_no_key(self):
        work = Path(tempfile.mkdtemp(prefix="ct-scrape-", dir=self.config))
        raw = work / "raw.json"
        raw.write_text(json.dumps([{"id": "yt1", "url": "https://example.com/shorts/yt1", "title": "A short",
                                    "duration": 30, "view_count": 500}]))
        out = scrape.run(work, platform="youtube", handle="example_creator", from_raw=raw)
        self.assertEqual(out["posts"][0]["metrics"]["views"], 500)


class YouTubeSetup(ConfigCase):
    def test_handle_and_key_stay_out_of_the_url(self):
        for raw in ("@SomeChannel", "SomeChannel", "https://www.youtube.com/@SomeChannel/shorts"):
            self.assertEqual(scrape.youtube_handle(raw), "SomeChannel")
        request = scrape.youtube_api_request("channels", "yt-test-key", part="contentDetails", forHandle="@SomeChannel")
        self.assertNotIn("yt-test-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "yt-test-key")

    def test_no_key_falls_back_to_the_shorts_listing(self):
        work = Path(tempfile.mkdtemp(prefix="ct-yt-", dir=self.config))
        listing = [{"id": "yt1", "url": "https://example.com/shorts/yt1", "title": "A short", "duration": 30,
                    "view_count": 500}]
        with mock.patch.object(scrape, "run_ytdlp", return_value=listing) as ytdlp, \
                mock.patch.object(scrape.urllib.request, "urlopen") as urlopen, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            out = scrape.run(work, platform="youtube", handle="@SomeChannel", limit=10)
        urlopen.assert_not_called()
        ytdlp.assert_called_once_with("SomeChannel", 10)
        self.assertEqual(out["posts"][0]["format"], "short")

    def test_youtube_only_with_captions_makes_whisper_optional(self):
        self.write("settings.json", {"platforms": ["youtube"]})
        with mock.patch.object(check_setup.importlib.util, "find_spec", return_value=object()):
            report_data = check_setup.run()
        self.assertFalse(any("whisper" in p for p in report_data["problems"]))
        self.assertTrue(any("YOUTUBE_API_KEY" in n for n in report_data["notes"]))
        with mock.patch.object(check_setup.importlib.util, "find_spec", return_value=None), \
                mock.patch.object(check_setup, "tool", return_value={"found": False, "path": None}):
            report_data = check_setup.run()
        self.assertTrue(any("whisper" in p for p in report_data["problems"]))
        self.assertTrue(any("youtube-transcript-api" in n for n in report_data["notes"]))


class BundledForm(ConfigCase):
    def test_blind_sample_reads_the_bundled_post_form(self):
        import blind_sample
        work = full_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        out = blind_sample.run(work, n=6)
        form = json.loads((SCRIPTS.parent / "decisions" / "creator.post.v1.json").read_text())
        self.assertEqual(set(out["questions"]), {"hook_type", "structure", "evidence", "ending"})
        self.assertEqual(out["questions"]["ending"]["instructions"], form["questions"]["ending"]["instructions"])
        self.assertEqual(len(out["posts"]), 6)


class Lint(ConfigCase):
    def test_rendered_page_is_clean(self):
        work = full_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        patterns.run(work, min_n=3)
        page = report.render(work, {"headline": "A plain headline \u2014 with a dash."}, "Example Teardown")
        self.assertEqual(lint_report.lint(page), [])

    def test_flags(self):
        flags = lint_report.lint("<title>x</title><p>One \u2014 two</p><td>None</td><script src=x></script>",
                                 spelling="au")
        text = " ".join(flags)
        for expected in ("viewport", "dash", "leaked", "external"):
            self.assertIn(expected, text)
        self.assertIn("color", " ".join(lint_report.lint('<meta name="viewport"><title>x</title><p>color</p>', "au")))


class Cli(ConfigCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, *args], cwd=SCRIPTS, capture_output=True, text=True, timeout=60,
                              env=dict(os.environ))

    def test_every_cli_help_works_without_keys(self):
        names = sorted(p.name for p in SCRIPTS.glob("*.py") if p.name not in ("common.py", "normalise.py"))
        self.assertGreaterEqual(len(names), 16)
        for name in names:
            result = self.run_script(name, "--help")
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr[-300:]}")
            self.assertIn("usage", result.stdout.lower(), name)

    def test_classify_dry_run_without_keys(self):
        work = classify_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        result = self.run_script("classify.py", "--work", str(work), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 post calls, 3 sentence calls", result.stdout)
        self.assertIn("TYPESAFE_API_KEY: missing", result.stdout)
        self.assertFalse((work / "labels.json").exists())

    def test_classify_real_run_without_key_stops_cleanly(self):
        work = classify_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        result = self.run_script("classify.py", "--work", str(work))
        self.assertEqual(result.returncode, 2)
        self.assertIn("TYPESAFE_API_KEY is not set", result.stdout)

    def test_jev_kill_switch_stops_classify(self):
        import classify
        import jev_client
        work = classify_work(tempfile.mkdtemp(prefix="ct-work-", dir=self.config))
        os.environ["TYPESAFE_API_KEY"] = "ts-test-key-not-real"
        (self.config / "jev.off").touch()
        with mock.patch.object(jev_client.urllib.request, "urlopen") as urlopen, self.assertRaises(classify.SetupError):
            classify.run(work, jev=jev_client)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

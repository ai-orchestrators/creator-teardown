# creator-teardown

A Claude Code / Claude Cowork skill that tears down a creator's whole account (their last 100-300 Instagram reels, TikToks, YouTube Shorts or LinkedIn posts) and finds what actually drives their numbers. Then it writes five versions for your brand.

## Why this exists

Watching a creator's best posts tells you what they did. It does not tell you what worked. Their best posts share traits with their worst ones, they repost winners, and their account grows under them, so a hook style that looks like a formula is often a coincidence.

This skill answers with numbers instead of vibes:

- **Measures every post against the creator's own normal at the time**, so account growth never fakes an outlier
- **Labels every post and every sentence** the same way (hook type, structure, evidence, emotion, ending, the job each sentence does), so patterns are counted, not remembered
- **Shows the miss rate**, not just the hits: "9 of 22 broke out, 13 did not" is a test, not a formula
- **Counts ideas, not posts**, so a winner posted three times cannot fake a pattern
- **Checks every pattern outside the winning shape**, so a trait riding on the real cause gets folded into it
- **Never invents a fact about you**: every claim in a rebuild is proved by a file you named

## What you get

One self-contained HTML report with seven tabs, in dark and light themes, that works on a phone:

| Tab | What is in it |
|---|---|
| Start here | Every post in one picture, the headline, and the whole playbook on one screen |
| What wins | Findings with their hit rates and miss rates, and a filter for every kind of post |
| How they build a post | Post shapes, a timed script anatomy, ways to open, script templates |
| Their best posts | The real images or frames, the hook, argument and ending, why it worked, what to borrow |
| Your versions | Five ready drafts for your brand, each with its hook options, structure map and checks |
| Review panel | A hostile number check, a craft check, a truth check and a copy-distance check |
| Raw data | Every lift table, the pace data, and every post with its labels |

Plus `playbook.json`, `rebuild-drafts.md` and every work file, so any number can be traced back.

## Cost per run

| Part | Cost |
|---|---|
| Jev labels for about 200 posts and their sentences | About US$0.05 to US$0.20. A dry run prints the estimate first, and a cap stops it at US$1 by default |
| Apify pull for Instagram, TikTok or LinkedIn | About US$1 to US$2 for 200-300 posts at current actor prices. Hard capped at US$5 by default |
| YouTube Shorts listing | Free (yt-dlp) |
| Transcription | Free. whisper.cpp runs on your machine and nothing is uploaded |
| Claude | The analyst, playbook, five rebuilds and review panel run on your Claude plan or API usage |

Costs in the report show in your currency, set at setup.

## First run

The skill ships with **zero identity in it**. It does not know your brand, your audience, your voice or your CTAs, and it will not guess.

On first use it runs a setup wizard (`SETUP.md`) that:

1. Checks ffmpeg, yt-dlp and whisper.cpp, and which API keys are present (it reports set or missing, never a value)
2. Asks which platforms you will tear down
3. Points you at the keys you need. **You add them yourself** to your shell or `config/.env`. The skill never asks for a key in the chat
4. Finds your whisper model
5. Asks who the rebuilds are for: brand, audience and their pains in their words, voice file, CTA, and an optional file of true stories
6. Asks who prepared the report (name, website, optional logo), your currency and your spelling

It writes the answers to `config/`. `config/` is gitignored. Your answers and keys never get committed, and never leave your machine.

### What you need

| Tool | Needed for |
|---|---|
| Python 3.9+ | Everything. Standard library only, no pip installs |
| ffmpeg + ffprobe | Measuring and transcribing video, thumbnails |
| whisper.cpp (`whisper-cli`) and a ggml model | Transcribing video posts |
| yt-dlp | YouTube Shorts, and TikTok and LinkedIn video |
| A TypeSafe key | Jev labels. Required |
| An Apify token | Instagram, TikTok and LinkedIn |
| An OpenRouter key | Optional fallback when TypeSafe is busy |

## Installation

### Claude Code (CLI)

User-level (available everywhere):

```bash
git clone https://github.com/ai-orchestrators/creator-teardown.git ~/.claude/skills/creator-teardown
```

Project-level (specific repo only):

```bash
git clone https://github.com/ai-orchestrators/creator-teardown.git .claude/skills/creator-teardown
```

### Claude Cowork (Desktop)

Same skill format. Drop the folder at `~/.claude/skills/creator-teardown/` and Cowork picks it up.

## Usage

### Trigger phrases

- "tear down @some_creator on Instagram"
- "analyse this creator's last 200 reels"
- "what makes @some_creator work on LinkedIn"
- "reverse-engineer their content"

On the first run it will set itself up before doing anything else. After that it is one request in, a finished report out: it asks for missing inputs once, then runs to the end without stopping.

### The rules that matter

- **Public data only.** Never a cookie, a logged-in browser or anyone's account.
- **Never copies the creator.** Rebuilds borrow the shape, never the words, stories or numbers. A script checks every draft and fails any run of 6 or more words shared with the source.
- **Drafts only.** Nothing is posted, scheduled or sent.

## What's in this repo

| Path | What |
|---|---|
| `SKILL.md` | The skill itself: the 11-step run |
| `SETUP.md` | First-use wizard. Builds your `config/` |
| `scripts/` | The pipeline: pull, transcribe, measure, label, count, render. Every script has `--help` |
| `scripts/tests/` | Offline tests: `python3 -m unittest discover -s scripts/tests` |
| `decisions/` | The two Jev question forms (post and sentence) |
| `references/` | The prompt for every agent the run spawns, and the playbook shape |
| `templates/` | The shapes the wizard fills in |
| `config/` | Yours. Gitignored. Created on first run |

## How Jev fits

Jev is TypeSafe's decision model. It does not write. It answers typed questions about a piece of text: pick one option, yes or no, or a place on a scale, each with a confidence. That makes it a good fit for the one part of a teardown that needs judgement at scale: labelling hundreds of posts and thousands of sentences the same way every time, in about 200 ms a call, at about US$0.04 per million input tokens.

| Who | Does | Never does |
|---|---|---|
| Code | Pulls, transcribes, measures pace, finds outliers, does every count and every sum | Judge meaning |
| Jev | Labels each post (10 questions) and each sentence (role and device) | Maths, free text, any action |
| Claude | Writes the playbook from the numbers, red-teams it, writes the rebuilds | Invent a number |

A label under 0.5 confidence becomes `unclear` and never counts toward a pattern. Before Jev runs, a blind Claude agent labels 20 posts on its own, and the agreement rate goes in the report, so you can see how far to trust the labels. That sample also seeds a golden set in `config/evals/` that grows with every run.

The client (`scripts/jev_client.py`) calls TypeSafe first and falls back to OpenRouter only when TypeSafe is rate limited. Create `config/jev.off` to stop every Jev call at once.

## How it pairs with the family

| Skill | What it does here |
|---|---|
| [writing-hooks](https://github.com/ai-orchestrators/writing-hooks) | Five hook options in the borrowed shape |
| [writing-linkedin-posts](https://github.com/ai-orchestrators/writing-linkedin-posts) | Drafts the LinkedIn rebuilds |
| [voice-humaniser](https://github.com/ai-orchestrators/voice-humaniser) | Strips AI-writing tells and rewrites in your voice |
| [voice-scoring-expert](https://github.com/ai-orchestrators/voice-scoring-expert) | Scores voice fit before a draft ships |
| [linkedin-post-analyser](https://github.com/ai-orchestrators/linkedin-post-analyser) | LinkedIn platform fit, the last gate |

All optional. Without them the rebuild agents work straight from your voice file.

## Licence

MIT. See [LICENSE](LICENSE).

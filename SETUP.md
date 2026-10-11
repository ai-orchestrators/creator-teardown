---
name: creator-teardown-setup
description: First-use setup wizard for creator-teardown. Checks the toolchain (ffmpeg, yt-dlp, whisper.cpp) and which API keys are present, then collects platforms, the whisper model, who the rebuilds are for, and the report's "Prepared by" details, and writes config/. TRIGGERS on "set up creator-teardown", "configure creator-teardown", "first run", or automatically when the skill finds no config/settings.json or config/profile.md. SKIP if both exist and the user just wants a teardown.
whenToUse: "Run once, before the first teardown. Re-run to add a platform, change the profile or rebrand the report."
context: inline
allowedTools: [AskUserQuestion, Read, Write, Edit, Bash, Glob]
---

# Setup Wizard

Builds the files in `config/` that `SKILL.md` reads on every run:

| File | Holds |
|---|---|
| `config/settings.json` | Platforms, transcriber, currency, spelling, run folder, cost caps |
| `config/profile.md` | Your default brand: who the five rebuilds are written for |
| `config/profiles/<slug>.md` | One per extra brand of yours. Optional |
| `config/brand.json` | Who prepared the report: name, website, logo. Optional |
| `config/.env` | API keys. **Written by the user, never by you** |

**Core principle: this repo ships with zero identity in it.** Everything about who
you are, who you sell to and how you sound is collected here and written to
`config/`, which is gitignored. Nothing you answer is ever committed back.

`config/` sits beside this file. To keep it elsewhere, the user sets
`CREATOR_TEARDOWN_CONFIG` to that folder before running the skill.

## Before you start

Check which of `config/settings.json`, `config/profile.md` and `config/brand.json` exist.

- **All there, and the user wants a teardown** - do not run this wizard. Hand back to the skill.
- **Some there, or the user wants a change** - load what exists, show the current values,
  and only ask about what is changing or missing.
- **None there** - run the full flow below.

Ask grouped questions with `AskUserQuestion` wherever the options are knowable. Never
invent an answer. If something does not apply, write `none` rather than guessing.

## Step 1 - Toolchain and keys check

Run, from this skill's folder:

```bash
python3 scripts/check_setup.py
```

It prints each tool's path or `missing`, and each key as `set` or `missing`. It never
prints a key's value. Show the user the table.

| Tool | Needed for | Install (macOS with Homebrew) |
|---|---|---|
| python3 3.9+ | everything | ships with macOS |
| ffmpeg + ffprobe | video measuring, transcription, thumbnails | `brew install ffmpeg` |
| whisper.cpp (`whisper-cli`) | transcribing video posts, locally | `brew install whisper-cpp` |
| yt-dlp | YouTube Shorts, and TikTok and LinkedIn video downloads | `brew install yt-dlp` |

On Linux use the package manager, or build whisper.cpp from source. **Do not proceed
past a missing ffmpeg when any video platform is chosen.** Give the install command and stop.

## Step 2 - Platforms

`AskUserQuestion`, multi-select: "Which platforms will you tear down?"

- Instagram (reels and carousels, through Apify)
- TikTok (through Apify)
- YouTube Shorts (through yt-dlp, free)
- LinkedIn (posts, through Apify; no view counts, so the metric is reactions)

Store as `platforms`: any of `instagram`, `tiktok`, `youtube`, `linkedin`.

## Step 3 - API keys (never in the chat)

| Key | Needed when | Where to get it |
|---|---|---|
| `TYPESAFE_API_KEY` | Always. Jev labels every post | A TypeSafe account (typesafe.ai), API keys page |
| `APIFY_TOKEN` | Instagram, TikTok or LinkedIn | An Apify account (apify.com), Settings, API and Integrations |
| `OPENROUTER_API_KEY` | Optional. Used only when TypeSafe is busy (429 or 529) | An OpenRouter account (openrouter.ai), Keys |

For each missing key the chosen platforms need, tell the user to add it themselves,
either as an export in their shell profile or as one line in `config/.env`:

```
TYPESAFE_API_KEY=paste-yours-here
APIFY_TOKEN=paste-yours-here
```

**Never ask the user to paste a key into the chat. Never write a key value into any
file yourself, and never print one.** `config/.env` is gitignored, but the key still
belongs to the user's own editor, not to this conversation.

Then `AskUserQuestion`: "Have you added the keys?" with options **Added, check again**
and **Skip for now**. On "Added", re-run `python3 scripts/check_setup.py`. A missing
`TYPESAFE_API_KEY` does not block setup, but every teardown will stop at step 5 until
it is set.

## Step 4 - Transcriber (only when a video platform is chosen)

Find what is installed:

```bash
command -v whisper-cli whisper-cpp main 2>/dev/null
ls ~/.whisper-models/*.bin ~/whisper.cpp/models/*.bin /opt/homebrew/share/whisper-cpp/*.bin /usr/local/share/whisper-cpp/*.bin 2>/dev/null
```

`AskUserQuestion`: "Which whisper model should transcribe the videos?" Offer each `.bin`
found (up to three), plus:

- **Download one** - tell the user to download a ggml model from the whisper.cpp project
  (`ggml-base.en.bin` is fast, `ggml-medium.en.bin` is more accurate, `large-v3-turbo`
  is best if the machine can carry it) into `~/.whisper-models/`, then re-run this step.
- **Use my own command** - collect an argv list with `{input}` (the video file) and
  `{output}` (where to write the transcript JSON). The command must write
  `{"text": "...", "captions": [{"text": " word", "startMs": 0, "endMs": 320}]}`.

Store `transcriber.binary` (default `whisper-cli`), `transcriber.model` (absolute path),
`transcriber.language` (default `en`, or `auto`) and, if given, `transcriber.command`.

## Step 5 - Who the rebuilds are for

Each run ends with five ready drafts in the user's own voice. Collect:

- **Brand name** and a **one-liner** (what it does, in the audience's words, under 15 words).
- **Audience** - who reads this. Specific beats broad: "agency owners doing $1M-$5M" beats "business owners".
- **Their top three pains, in THEIR words.** The sentence they would say out loud.
- **Awareness stage** (`AskUserQuestion`): cold, problem-aware, solution-aware, most-aware.
- **Default rebuild format** (`AskUserQuestion`): LinkedIn text post, short video script,
  carousel outline, or match each source post's format.
- **Regional English** (`AskUserQuestion`): AU, UK or US.
- **Voice file** - path to a tone-of-voice document, if they have one. Otherwise collect
  five phrases that sound like them and their banned words (offer: delve, leverage,
  unlock, robust, navigate, game-changer).
- **CTA** - the call to action the rebuilds end on, plus any others they use. Never invent one.
- **True-stories file** - path to a file of real stories, results or case studies the
  rebuilds may use. Optional. Without it, rebuilds use no personal story and claim no
  result: they use a moment the reader has lived instead.

Read the voice file and stories file once to confirm the paths work. Do not copy their
contents into `config/`: store the paths.

**More than one brand?** Ask once. The first brand goes to `config/profile.md` (it becomes
`default`). Each other brand gets the same questions and its own file,
`config/profiles/<slug>.md`, with a short lowercase slug. Every run asks which brand it is for.

## Step 5b - Client files (optional)

Teardowns can also be run for a client: the skill builds their brand profile first, then writes
the rebuilds for them. It reads only that client's own material.

> "Do you keep a folder per client? If so, where is the folder that holds them?"

Store the parent folder as `client_files_dir` (for example `~/Clients`, holding one folder per
client). `none` is fine: client runs then work from the client's own posts and any notes the user
points at on the day. Never point it at a folder that mixes several clients' files loose together.

## Step 6 - The report

- **"Prepared by" name** - shown in the byline, footer and phone menu. `none` is fine:
  the byline is then just "Prepared <date>".
- **Website** - the name links here. Optional.
- **Logo path** - a small PNG, JPG or SVG, embedded in the page. Optional. A path relative
  to `config/` or absolute.
- **Currency** (`AskUserQuestion`): US$ only (default), AUD, GBP, EUR (Other for any code).
  For anything but USD, ask for the rate: how many units one US dollar buys today. Costs
  then show in that currency first, with US$ beside them.
- **Spelling of shown text** (`AskUserQuestion`): as written (default), Australian, British.
  AU and UK turn US spellings in quotes and captions into -ise and -our forms.
- **Timezone** for the "Prepared" date and every post date on the page: an IANA name such
  as `Europe/London` or `America/New_York`. Blank means UTC.

## Step 7 - Defaults

Offer, do not assume:

| Key | Default | Meaning |
|---|---|---|
| `runs_dir` | `teardowns` | Run folders go here, relative to the folder Claude is working in |
| `apify_max_cost_usd` | `5` | Hard spend cap on every Apify pull |
| `jev_max_usd` | `1` | Hard cap on one labelling run |
| `client_files_dir` | `null` | Set in Step 5b |

## Generation

1. Read `templates/settings.example.json`, fill it from the answers, and write
   `config/settings.json`.
2. Read `templates/profile.tmpl.md`, replace every placeholder, and write `config/profile.md`
   (and `config/profiles/<slug>.md` for each extra brand).
3. If any report field was given, read `templates/brand.example.json`, fill it, and write
   `config/brand.json`. Leave out fields the user skipped.
4. Run `python3 scripts/check_setup.py` again and show the result. Mark anything still
   missing and which platforms it blocks.
5. Give the user one trigger phrase to test, e.g. "tear down @some_creator on LinkedIn, last 100 posts".

## Hard rules

- **Never write identity into `SKILL.md`, `README.md`, `references/` or `scripts/`.** All of
  it goes to `config/`, which is gitignored.
- **Never handle a key.** Not in the chat, not in a file you write, not in output you print.
- **Never guess a pain, a CTA, a story or a voice phrase.** Ask, or write `none`.
- Re-running this wizard updates `config/` in place. It never touches the skill.

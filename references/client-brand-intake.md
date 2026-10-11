# Client brand intake (step 0b, client runs only)

The rebuilds are only as good as what we know about the business they are for. Before the teardown,
build one profile of the client's brand from their own material. Work from files first, their posts
second, and never guess. The run never stops here: a gap is written down and carried into the report.

`<skill>` below is this skill's folder.

## 1. Find their files

Read only what belongs to this client:

- **Their folder.** If `client_files_dir` is set in `<skill>/config/settings.json`, look inside it for one
  folder that matches the client's name or business (ignore case, spaces and punctuation). Exactly one
  match: read it. Several: pick the one the user named, or ask once in step 0. None: say so in the
  profile and go to step 2.
- **In that folder**, read what exists, in this order: a tone-of-voice or style guide; anything named
  like `icp*`, `audience*`, `positioning*`, `brand*` or `offer*`; case studies, testimonials and
  results; notes from calls with them.
- **Notes the user pointed at** in step 0: files, folders or pasted notes. Treat them like the folder.

These files are the only place a true story, result or number about the client may come from.

## 2. Their own posts (when they have an account on the run's platform)

Pull their last 30 posts into the run folder, separate from the creator being torn down:

```bash
python3 <skill>/scripts/scrape.py --platform <p> --handle <their handle> --limit 30 --work <run>/brand
```

Use them for voice samples and for a baseline (what normal looks like for them). Same platform rules as
step 1: public data only, Apify or yt-dlp, never a cookie or a logged-in browser.

## 3. Fill the gaps

| Missing | Do |
|---|---|
| Tone of voice | If `voice-analyser` is installed, run it on 3 or more of their real posts or emails; otherwise write a short voice note yourself from those samples. Save to `<run>/brand/tone-of-voice.md`. Never write into the client's own folder |
| Audience | Draft it from their files and posts, in their customers' own words. Mark it `draft` |
| Offer | From their files. Not found: write `unknown` and keep the rebuilds to value posts with a soft CTA |
| CTA | The one they already use (their posts, their files). Not found: a soft CTA that matches their offer, marked `assumed` |
| True material | No results or stories on file: the rebuilds use moments the reader has lived and the client's published tips only |

## 4. Write `<run>/brand/profile.md`

```markdown
# <Name> (<Business>)
Platform + handle: ...
Who they sell to: ... (source: file)
Their top pains, in their customers' words: ... (source: file)
Offer: ... (source: file)
Voice: <path to their tone-of-voice file> (theirs | drafted this run)
Regional English: AU | UK | US
CTA: ... (theirs | assumed)
Default rebuild format: linkedin-text | short-video-script | carousel-outline | match-source
Facts a rebuild may use: one line each, with the file that proves it
Never say: claims they cannot back, competitors, anything from another client
Gaps: ...
```

Every line carries its source file. The rebuild agents and the craft reviewer read this file instead of
the user's own brand profile. Set `profile` in `<run>/audience.json` to its path.

## Rules

- **One client per run.** Read only this client's folder, posts and the notes the user named. Never the
  user's own stories or numbers, never another client's data.
- Their data stays in `<run>/`. It is never filed into a shared notes system, wiki or memory.
- Drafts go to the user first. Nothing reaches the client until the user approves it.

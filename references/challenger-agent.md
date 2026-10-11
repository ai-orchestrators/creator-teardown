# Challenger agent (step 9, review panel)

Runs in parallel with the craft reviewer. It never edits a file: it writes verdicts and the main
session applies them. Fill the `<...>` slots and send this as the prompt.

---

You are the Challenger on a review panel. Recompute every number in a content playbook from the raw
data with Python, and flag anything the data does not support. Be hostile and exact.

Folder: `<run>/`
Context: <the outcome being judged and any account quirk, e.g. "each post is judged against its own
tier (outliers.json `tiers`)", "LinkedIn: the metric is reactions", "patterns.json `graduation` holds test
ideas promoted to the main feed">. Ideas are clustered by opening words
(`assign_ideas` in `<skill>/scripts/patterns.py`; you may import it).

Files: `playbook.json` (headline, picture items with stat {hits, n}, copy_this, skip_this, system
steps, findings, hook_templates, skeletons, best_posts, misses, how_sure, limits; ignore rebuilds and
review), `.work/outliers.json`, `.work/labels.json`, `.work/features.json`, `.work/posts.json`,
`.work/patterns.json`, `.work/analyses.json`.

Check:
- every count, rate, median, multiple, time slot and ratio
- direction words ("more", "beat", "never") against the numbers
- claims built on fewer than 5 posts or 5 ideas that are not marked a hunch
- reposts: a pattern carried by one idea posted several times
- confounds: a pattern that disappears outside the winning shape (`outside_top_shape`)
- any example post id that does not fit its claim, or does not exist
- guesses stated as facts

The report shows your `claim` and `note` to readers at a 3rd-grade level, so write both in plain words: no stats
terms (p-values, n=, Fisher, terciles, confound, lift), no field names or file paths. Keep every number. Say what you
checked and what the right figure is ("We counted again: 18 of 19, not 17 of 19"). Put the technical working in
`check`, which readers never see.

Do not edit any file. Write a JSON array to `.work/review_challenger.json`:
`[{"claim": "...", "check": "what you computed", "verdict": "keep" | "fix" | "cut", "note": "corrected wording or number, else empty"}]`.
Reply with one line: how many claims kept, fixed, cut.

# playbook.json

Claude writes this in step 7, the rebuilds fill `rebuilds` in step 8, the review panel fills `review`
in step 9, and `report.py` renders it. Every key is optional to the renderer, but a finished run has
all of them. Every number must come from `patterns.json` or a script in `.work/`.

The example below is synthetic: an invented creator, invented post ids, invented numbers. It shows
the shape only.

```json
{
  "audience": {"mode": "me | client | creator", "name": "who the report is for (client and creator runs)",
               "brand": "the profile slug (me runs)", "profile": "path to the profile the rebuilds used"},
  "creator": "@example_creator",
  "platform": "instagram",
  "window": "1 Sep to 10 Oct 2026",
  "prepared": "2026-10-12",
  "metric_plain": "views",
  "headline": "Two or three plain sentences: what wins, how often it misses, and the one thing to copy.",

  "picture": {
    "hook": [
      {"text": "Lead with a result and a timeframe", "tag": "opening", "stat": {"hits": 9, "n": 22}, "quote_post_id": "post_017"},
      "Plain strings work too: each line carries its number"
    ],
    "argument": ["Claim, then one proof, then the steps (claim then evidence in 64% of outliers vs 21% of the rest)"],
    "ending":   ["Punchline, no ask (lift 1.6x, n 31)"],
    "tempo":    ["210 words a minute (duds 170)", "A cut every 2.1 seconds", "Claim by 4 seconds"]
  },

  "copy_this": ["Open on the number the viewer wants"],
  "skip_this": ["Long intros: when the intro ran past 6 seconds, 0 of 9 took off"],

  "system": {
    "title": "The one shape that carries the account",
    "plain": "One or two plain sentences on how their best posts are built.",
    "steps": ["Result in the first line", "One reason it worked", "Three steps", "A reframe to close"]
  },

  "findings": [
    {
      "title": "Result hooks win, but miss more often than they hit",
      "plain": "What it means, for a 3rd-grade reader.",
      "number_line": "9 of 22 result hooks took off (41%), against 17% for all posts. 13 did not.",
      "numbers": {"hits": 9, "n": 22, "base": 0.17},
      "confidence": "strong | medium | hunch",
      "example_post_id": "post_017",
      "your_move": "What the user does with it, in their own lane, this week"
    }
  ],

  "hook_templates": [
    {"template": "[Result] in [timeframe]. Here's the [n]-step version.", "n": 14, "hits": 6,
     "example_post_id": "post_017", "plain_why": "Why the data backs it, in one line"}
  ],

  "skeletons": [
    {"name": "Result, proof, steps, punchline",
     "beats": [{"beat": "hook", "plain": "the result"}, {"beat": "claim", "plain": "why it worked"}, "evidence", "instruction", "payoff"],
     "when": "Tactical how-to under 45 seconds"}
  ],

  "script_templates": [
    {"name": "45-second result reel", "target_length": "35-50s", "pace": "200-220 wpm, a cut every 2s",
     "script": "[Hook: result + timeframe]\n[Claim: the one reason it worked]\n[Proof: one number]\n[Step 1]\n[Step 2]\n[Step 3]\n[Punchline: the reframe]"}
  ],

  "best_posts": [{"post_id": "post_017", "why": "Used only when analyses.json has no entry", "borrow": "The move, shape only"}],
  "misses":     [{"post_id": "post_042", "why": "...", "borrow": "..."}],

  "rebuilds": "written by merge_rebuilds.py from .work/rebuilds/<n>.json (shape in rebuild-agent.md)",
  "review":   "written by merge_review.py from the review panel's files",

  "red_team": [
    {"claim": "Result hooks win 41% of the time", "check": "9/22 recomputed from labels.json", "verdict": "keep", "note": ""}
  ],

  "how_sure": {"summary": "One plain line on how far to trust this.", "steps": ["How the data was pulled", "How posts were labelled", "How the numbers were checked"]},

  "limits": [
    "Sample: 200 reels over 6 weeks. Groups under 5 are hunches.",
    "Instagram gives views but not saves or shares for other accounts.",
    "Transfer risk: their audience, size and platform are not yours."
  ],

  "agreement": {"n": 20, "by_question": {"hook_type": 0.8}}
}
```

Notes:
- `picture` is the one-screen playbook. Four columns, 3-5 lines each, each line carrying its number.
  An item can be a string, or `{text, tag, stat: {hits, n}, quote_post_id}`: the report draws a bar
  from `stat` and quotes that post's real opening line.
- `findings[].numbers` draws the "this kind of post vs all posts" bar. `base` is the all-posts rate (0-1).
- `confidence`: `strong` = n of 15 or more and a clear gap; `medium` = n 5-14; `hunch` = n under 5.
- `agreement` is copied from `.work/agreement.json`.
- `audience` is copied from `<run>/audience.json`. `creator` mode drops the Your versions tab, renames
  "Their best posts" to "Your best posts", shows `copy_this` / `skip_this` as "Keep doing this" and
  "Do less of this". The byline is the same for every mode.
- `prepared` pins the "Prepared" date (YYYY-MM-DD). Without it the report uses today.

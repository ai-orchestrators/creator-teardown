#!/usr/bin/env python3
"""Render a creator teardown as one self-contained HTML page.

Who prepared it (name, link, logo) comes only from config/brand.json; with none, the byline is just
"Prepared <date>". Costs show in the currency set in config/settings.json (US$ by default), and dates
in settings.timezone (UTC by default).
"""
from __future__ import annotations

import argparse
import base64
import html
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from common import ConfigError, currency_symbol_rate, format_money, load_brand, load_settings, read_json

FONT = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..600&family=Inter:wght@400;500;600;700&display=swap">'
CSS = '''<style>
:root{color-scheme:dark;--bg:#0e0d0c;--panel:#151413;--deep:#1d1c1b;--ink:#fafafa;--muted:#98969e;--line:#29282d;--accent:#a78bfa;--dud:#6f6e75;--track:#252429;--grad:linear-gradient(135deg,#22d3ee,#60a5fa,#a78bfa,#e879f9);--glow:rgba(167,139,250,.13)}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){color-scheme:light;--bg:#f9f8f5;--panel:#ffffff;--deep:#f1efea;--ink:#17171c;--muted:#5b5a64;--line:#e2dfd8;--accent:#6d28d9;--dud:#8b8992;--track:#e7e4dd;--grad:linear-gradient(135deg,#0891b2,#2563eb,#7c3aed,#c026d3);--glow:rgba(124,58,237,.08)}}
:root[data-theme="light"]{color-scheme:light;--bg:#f9f8f5;--panel:#ffffff;--deep:#f1efea;--ink:#17171c;--muted:#5b5a64;--line:#e2dfd8;--accent:#6d28d9;--dud:#8b8992;--track:#e7e4dd;--grad:linear-gradient(135deg,#0891b2,#2563eb,#7c3aed,#c026d3);--glow:rgba(124,58,237,.08)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 Inter,sans-serif;overflow-x:hidden}
a{color:var(--ink);text-decoration-color:var(--accent)}.wrap{max-width:1200px;margin:auto;padding-inline:16px;padding-bottom:70px}
h1,h2{font-family:Fraunces,Georgia,'Times New Roman',serif;font-weight:500;line-height:1.08;letter-spacing:-.02em;text-wrap:balance}h3{font:600 21px/1.25 Inter,system-ui,sans-serif;letter-spacing:-.01em;text-wrap:balance}h1{font-size:clamp(40px,7vw,76px);margin:.15em 0 .2em}h2{font-size:clamp(30px,4.4vw,46px);margin:0 0 16px}h3{margin:0 0 12px}
section{padding-top:56px}.eyebrow{color:var(--muted);text-transform:uppercase;letter-spacing:.13em;font-size:12px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.grid.stats{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}.band-bar{display:flex;height:10px;border-radius:5px;overflow:hidden;margin-top:12px;background:var(--track)}.band-bar i{display:block;height:100%;background:var(--muted)}.band-bar i.outlier{background:var(--accent)}.band-bar i.dud{background:var(--dud)}.dots i{width:6px;height:6px}.panel,.stat,details{background:var(--panel);border-radius:10px;padding:20px;min-width:0}.stat b{display:block;color:var(--ink);font:500 34px Fraunces,Georgia,serif;font-variant-numeric:tabular-nums}.stat span{color:var(--muted);font-size:13px}.picture .panel{position:relative;overflow:hidden}.picture .panel::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--grad)}.picture h3{font-size:24px}.tablewrap{overflow-x:auto;background:var(--panel);border-radius:10px;margin:12px 0 26px}table{border-collapse:collapse;width:100%;min-width:580px}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:12px;white-space:nowrap}td.num,.num{font-family:Inter,system-ui,sans-serif;font-variant-numeric:tabular-nums}.muted{color:var(--muted)}.chip{font-size:11px;text-transform:uppercase;border:1px solid var(--line);border-radius:3px;padding:2px 6px}.chip.outlier{color:var(--accent);border-color:var(--accent)}.chip.dud{color:var(--dud)}.hunch{opacity:.65}.chart{background:var(--panel);border-radius:10px;padding:18px;overflow:hidden}.chart svg{width:100%;height:auto;display:block}.posts{display:grid;gap:10px}details{padding:0}summary{cursor:pointer;padding:16px 20px;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}summary .hook{flex:1 1 260px}details .inside{padding:0 20px 20px}.sent{padding:7px 10px;margin:5px 0;border-left:3px solid var(--muted);background:var(--deep)}.sent.hook,.sent.payoff{border-color:var(--accent)}.pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--deep);padding:16px;border-radius:6px}.stack{display:grid;gap:12px}.list{padding-left:20px}p{margin:8px 0}svg text{fill:var(--muted);font:12px Inter,system-ui,sans-serif}svg .axis{stroke:var(--line)}svg .reference{stroke:var(--muted);stroke-dasharray:5 5}svg .limit{stroke:var(--accent);stroke-dasharray:5 5}svg .normal-dot{fill:var(--muted)}svg .outlier-dot{fill:var(--accent)}svg .dud-dot{fill:var(--dud)}svg .climbing-dot{fill:var(--panel);stroke:var(--muted);stroke-width:2}
@media(max-width:700px){.grid{grid-template-columns:1fr}section{padding-top:40px}.wrap{padding-inline:16px}summary{display:grid;grid-template-columns:1fr}.chart{padding:8px}h1{overflow-wrap:anywhere}}
.tabs{position:sticky;top:env(safe-area-inset-top,0px);z-index:2;display:flex;gap:4px;overflow-x:auto;max-width:100%;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0}.tabs button{flex:none;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--ink);font:600 14px Inter,sans-serif;padding:10px 13px;cursor:pointer}.tabs button[aria-selected="true"]{color:var(--accent);border-color:var(--accent)}.tabs button:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}.tab-panel{padding-top:32px;scroll-margin-top:72px}.tab-panel[hidden]{display:none}.reading{max-width:68ch}.lede{font-size:clamp(21px,3vw,27px);line-height:1.45}.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.finding,.post-card{background:var(--panel);border-radius:10px;padding:22px;margin:16px 0}.number-line{border-left:3px solid var(--accent);padding:8px 14px;background:var(--deep)}.confidence.strong{color:var(--accent);border-color:var(--accent)}.confidence.medium{color:var(--muted)}.confidence.hunch{background:transparent}.mini-chart{max-width:520px;margin:12px 0}.mini-chart svg{width:100%;height:auto}.mini-chart .hit{fill:var(--accent)}.mini-chart .base{fill:var(--muted)}.mini-chart .track{fill:var(--track)}.mini-chart text{fill:var(--ink)}.flow li{margin-bottom:10px}.flow li::marker{color:var(--accent)}.mono{font-family:Inter,system-ui,sans-serif}.post-card.quiet{border:1px solid var(--line);background:transparent}
@media(max-width:700px){.two{grid-template-columns:1fr}.tab-panel{padding-top:24px}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
</style>'''
CSS = CSS.replace('</style>', '''
:root{--role-blue:#6aadc1;--role-sage:#78aa76;--role-gold:#d6a452;--role-violet:#9b8bd6;--role-rose:#d68aa0;--role-sand:#b8a07a}.role-instruction{background:var(--role-violet)!important}.role-reframe,.role-objection{background:var(--role-rose)!important}.role-story_beat{background:var(--role-sand)!important}header{padding-top:24px}header .stats{margin-top:24px}.stat{min-height:132px}.stat b{line-height:1.15}.stat.cost{background:color-mix(in srgb,var(--accent) 12%,var(--panel));border:1px solid color-mix(in srgb,var(--accent) 55%,transparent)}.stat.cost b{font-size:27px}.stat .sub{display:block;margin-top:8px}.format-bar,.mini-bar,.anatomy{display:flex;overflow:hidden;border-radius:4px;background:var(--track);height:8px;margin-top:12px}.format-bar i,.mini-bar i,.anatomy i{display:block;height:100%;background:var(--accent)}.format-bar i:nth-child(2){background:var(--muted)}.format-bar i:nth-child(3){background:var(--dud)}.format-bar i:nth-child(4){background:var(--line)}.dots{display:flex;gap:4px;flex-wrap:wrap;margin-top:12px}.dots i{width:8px;height:8px;border-radius:50%;background:var(--muted)}.dots i.outlier{background:var(--accent)}.dots i.dud{background:var(--dud)}.thumb-small{width:42px;height:42px;object-fit:cover;border-radius:4px;float:right}.spark{width:100%;height:28px;margin-top:9px}.decode-controls{display:flex;align-items:center;gap:14px;margin:16px 0}.decode-controls button,.copy-button,.kind-tabs button{background:var(--deep);border:1px solid var(--line);border-radius:5px;color:var(--ink);padding:7px 12px;cursor:pointer}.decode-controls button:hover,.copy-button:hover,.kind-tabs button[aria-selected="true"]{border-color:var(--accent);color:var(--accent)}.one-picture{margin-top:16px}.one-picture svg a:focus-visible{outline:2px solid var(--accent)}.plot-post{transition:opacity .2s}.plot-post.dim{opacity:.16}.plot-post.pending{opacity:.2;filter:grayscale(1)}.plot-post circle,.plot-post rect{stroke:var(--bg);stroke-width:2}.plot-post:hover{opacity:1!important}.picture li{margin:0 0 14px}.picture .chip{display:inline-block;margin-right:6px}.quote-chip{display:block;margin-top:9px;padding:5px 8px;border-left:2px solid var(--accent);background:var(--deep);font-size:13px}.copy-skip{margin-top:24px}.copy-skip li::marker{color:var(--accent)}.kind-tabs{display:flex;flex-wrap:wrap;gap:7px;margin:16px 0}.kind-list{display:grid;gap:8px}.kind-row{display:grid;grid-template-columns:minmax(100px,2fr) 1fr 1.5fr;gap:10px;align-items:center;width:100%;text-align:left;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:10px;cursor:pointer}.kind-row:hover,.kind-row.active{border-color:var(--accent)}.kind-row .mini-bar{margin:0}.flow-chips{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0 24px}.flow-chips span{padding:8px 10px;border:1px solid var(--line);border-radius:5px}.flow-chips b{color:var(--accent)}.flow-chips em{color:var(--muted);font-style:normal}.anatomy{height:14px;margin:18px 0 8px}.anatomy i{min-width:2px}.role-hook{background:var(--accent)!important}.role-claim,.role-setup{background:var(--role-blue)!important}.role-evidence,.role-proof{background:var(--muted)!important}.role-payoff,.role-benefit{background:var(--role-sage)!important}.role-cta,.role-ending{background:var(--role-gold)!important}.role-other,.role-unclear{background:var(--dud)!important}.anatomy-legend{display:flex;flex-wrap:wrap;gap:9px;font-size:12px;color:var(--muted)}.anatomy-legend i{display:inline-block;width:9px;height:9px;margin-right:4px}.beat-list{list-style:none;padding:0}.beat-list li{border-left:3px solid var(--line);padding:4px 10px;margin:7px 0;background:var(--deep)}.beat-list time{color:var(--accent);font-family:Inter,system-ui,sans-serif}.media-strip{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory;margin:18px 0}.media-strip img{height:280px;width:auto;max-width:85%;object-fit:contain;scroll-snap-align:start;border-radius:5px;background:var(--deep)}.post-card .lede{font-size:23px}.stat-chips{display:flex;flex-wrap:wrap;gap:7px;margin:14px 0}.stat-chips .chip{padding:5px 8px}.breakdown{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:20px}.breakdown h4{margin:0 0 8px;color:var(--accent)}.rebuild-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:24px}.rebuild-layout aside img{max-width:100%;border-radius:5px}.hook-option{padding:9px 12px;border-left:3px solid var(--line);margin:7px 0;background:var(--deep)}.hook-option.chosen{border-color:var(--accent)}.draft-head{display:flex;justify-content:space-between;align-items:center;gap:10px}.review-card{background:var(--panel);padding:20px;border-radius:8px;margin:16px 0}.review-card h3{display:inline;margin-right:12px}.review-card .tablewrap{margin-bottom:0}.tab-panel h3{margin-top:30px;margin-bottom:16px}.tab-panel h2{margin-bottom:18px}.tab-panel .panel h3:first-child,.post-card h3:first-child,.review-card h3:first-child{margin-top:0}.tab-panel p+.panel,.tab-panel p+.grid,.tab-panel p+.two{margin-top:16px}.tab-panel .two>div{min-width:0}
.plot-post image{clip-path:inset(0 round 4px)}.channel-icon,.channel-switch svg,.ch-line svg,.channel-tag svg{display:inline-flex;flex:none}.channel-icon svg{width:20px;height:20px;display:block}.channel-switches{display:inline-flex;gap:2px;padding:3px;border:1px solid var(--line);border-radius:999px;background:var(--panel)}.channel-switch{display:inline-flex;align-items:center;gap:7px;border:0;background:transparent;color:var(--muted);font:600 13px Inter,system-ui,sans-serif;padding:6px 12px;border-radius:999px;cursor:pointer}.channel-switch svg{width:18px;height:18px}.channel-switch[aria-pressed="true"]{background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--ink)}.channel-switch:focus-visible{outline:3px solid var(--accent);outline-offset:2px}.stat .ch-line{display:flex;align-items:center;gap:7px;margin-top:6px}.ch-line svg{width:14px;height:14px}.channel-bar{display:flex;height:8px;border-radius:4px;overflow:hidden;margin-top:10px;background:var(--track)}.channel-bar i{display:block;height:100%}.channel-bar .ch-instagram{background:#e1306c}.channel-bar .ch-youtube{background:#ff0033}.channel-bar .ch-linkedin{background:#0a66c2}.channel-bar .ch-tiktok{background:var(--ink)}.channel-tag{display:flex;align-items:center;gap:8px;margin:0 0 6px}.channel-tag svg{width:16px;height:16px}.format-bar i:nth-child(5){background:var(--track)}.menu-channels{display:none}.menu-bar,.menu-head,.menu-backdrop,.menu-foot,.swipe-hint{display:none}@media(max-width:700px){.menu-channels{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}.menu-channels .channel-switch{border:1px solid var(--line)}.menu-bar{display:block;position:sticky;top:env(safe-area-inset-top,0px);z-index:3;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line)}.menu-toggle{display:flex;align-items:center;gap:12px;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:8px;color:var(--ink);font:600 16px Inter,system-ui,sans-serif;padding:11px 14px;cursor:pointer;text-align:left}.menu-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.menu-hint{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.12em}.burger{display:grid;gap:4px;width:18px}.burger i{display:block;height:2px;border-radius:1px;background:var(--accent)}.tabs{position:fixed;top:0;bottom:0;left:0;width:min(82vw,320px);max-width:none;flex-direction:column;align-items:stretch;gap:4px;overflow-y:auto;overflow-x:hidden;background:var(--panel);border-bottom:0;border-right:1px solid var(--line);padding:calc(16px + env(safe-area-inset-top,0px)) 14px calc(16px + env(safe-area-inset-bottom,0px));transform:translateX(-102%);transition:transform .25s ease;z-index:20;visibility:hidden}body.menu-open .tabs{transform:none;visibility:visible;box-shadow:0 0 60px rgba(0,0,0,.45)}body.menu-open{overflow:hidden}.tabs button{text-align:left;font-size:17px;padding:14px 12px;border-radius:8px}.tabs button[aria-selected="true"]{background:color-mix(in srgb,var(--accent) 14%,transparent);border-color:transparent}.menu-head{display:flex;align-items:center;justify-content:space-between;padding:0 4px 12px;margin-bottom:6px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.13em}.tabs .menu-close{font:400 28px/1 Inter,system-ui,sans-serif;padding:4px 10px;color:var(--ink)}.menu-backdrop{display:block;position:fixed;inset:0;z-index:19;background:rgba(0,0,0,.5)}.menu-backdrop[hidden]{display:none}.menu-foot{display:flex;align-items:center;gap:10px;margin-top:auto;padding:14px 4px 0;border-top:1px solid var(--line);color:var(--ink);text-decoration:none;font:500 17px Fraunces,Georgia,serif}.menu-foot img{width:28px;height:28px;border-radius:50%}.chart.one-picture{overflow-x:auto;padding:12px}.chart.one-picture svg{width:880px;max-width:none}.swipe-hint{display:block;color:var(--muted);font-size:13px;margin-top:6px}}details.beats{margin-top:14px;background:var(--deep)}details.beats summary{padding:12px 16px;font-weight:600}details.beats .beat-list{padding:0 16px 14px 34px;margin:0}.rebuild-layout>*,.breakdown>*,.two>*,.grid>*,.post-card>*{min-width:0}header{position:relative;isolation:isolate}header::before{content:"";position:absolute;z-index:-1;inset:-90px 0 auto 0;height:560px;background:radial-gradient(closest-side at 38% 42%,var(--glow),transparent);pointer-events:none}header h1{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;padding-bottom:.06em}.byline{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;color:var(--muted);font-size:15px;margin:0}.byline a{color:var(--ink);font-weight:600;text-decoration:none;border-bottom:1px solid var(--accent)}.byline a:hover{color:var(--accent)}.byline .sep{opacity:.5}.stat .thumb-link{display:block;margin-top:10px}.thumb-best{display:block;width:100%;height:92px;object-fit:cover;border-radius:6px;border:1px solid var(--line)}.jev-credit{display:flex;align-items:center;gap:9px;margin-top:14px;padding-top:12px;border-top:1px solid var(--line);font-size:13px;color:var(--muted);text-decoration:none}.jev-credit img{width:32px;height:32px;border-radius:50%;flex:none}.jev-credit strong{color:var(--ink);font-weight:700;font-size:16px}.site-footer{margin-top:72px;padding-top:28px;border-top:1px solid var(--line);display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px 28px;color:var(--muted);font-size:14px}.site-footer .brand{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;font:500 20px Fraunces,Georgia,serif}.site-footer .brand img{width:34px;height:34px;border-radius:50%}.site-footer p{margin:0;max-width:62ch}@keyframes tile-rise{from{transform:translateY(12px)}to{transform:translateY(0)}}
@media(max-width:700px){header .stats{grid-template-columns:repeat(2,minmax(0,1fr))}header .stats .stat.cost:nth-child(odd){grid-column:1/-1}.stat{padding:14px;min-height:115px}.stat b{font-size:25px}.breakdown,.rebuild-layout{grid-template-columns:1fr}.media-strip img{height:230px}.kind-row{grid-template-columns:1fr 1fr}.kind-row .mini-bar{grid-column:1/-1}}
</style>''')


# Set by render() from config/settings.json: spelling, currency and timezone for what is shown.
STYLE = {'spelling': 'as-is', 'currency': None, 'timezone': None}
PROFILE_URLS = {'linkedin': 'https://www.linkedin.com/in/{}/', 'instagram': 'https://www.instagram.com/{}/',
                'tiktok': 'https://www.tiktok.com/@{}', 'youtube': 'https://www.youtube.com/@{}', 'x': 'https://x.com/{}'}


def local_zone():
    """settings.timezone (an IANA name such as Europe/London), else UTC."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(STYLE.get('timezone') or 'UTC')
    except Exception:
        return timezone.utc


def prepared_date(value=None) -> str:
    if value:
        day = datetime.fromisoformat(str(value)[:10])
    else:
        day = datetime.now(local_zone())
    return f'{day.day} {day:%B %Y}'


def local_dt(value):
    """A post time in settings.timezone (UTC by default). Stored times are UTC."""
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(local_zone())


def local_iso(value) -> str:
    moment = local_dt(value) if value else None
    return moment.strftime('%Y-%m-%d') if moment else ''


BAND_WORDS = {'outlier': 'took off', 'normal': 'normal', 'dud': 'flopped', 'climbing': 'still climbing'}


def clock(seconds):
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    seconds = round(seconds)
    return f'{seconds // 60}:{seconds % 60:02d}' if seconds >= 60 else f'{seconds}s'


def day_text(value):
    day = local_dt(value) if value else None
    return f'{day.day} {day:%b %Y}' if day else None


def window_text(first: str, last: str) -> str:
    a, b = datetime.fromisoformat(first), datetime.fromisoformat(last)
    left = f'{a.day} {a:%b}' + ('' if a.year == b.year else f' {a.year}')
    return f'{left} to {b.day} {b:%b %Y}'
US_TO_AU = {'behavior': 'behaviour', 'behaviors': 'behaviours', 'color': 'colour', 'colors': 'colours',
            'favorite': 'favourite', 'favorites': 'favourites', 'organize': 'organise', 'organized': 'organised',
            'analyze': 'analyse', 'analyzed': 'analysed', 'realize': 'realise', 'realized': 'realised',
            'center': 'centre', 'optimize': 'optimise', 'optimized': 'optimised', 'prioritize': 'prioritise',
            'labor': 'labour', 'honor': 'honour', 'traveled': 'travelled',
            'license': 'licence', 'licenses': 'licences', 'defense': 'defence', 'offense': 'offence'}
for stem in ('organiz', 'analyz', 'optimiz', 'customiz', 'realiz', 'prioritiz', 'recogniz', 'apologiz', 'specializ',
             'emphasiz', 'summariz', 'minimiz', 'maximiz', 'standardiz', 'categoriz', 'monetiz', 'utiliz', 'memoriz'):
    for ending in ('e', 'es', 'ed', 'ing', 'ation', 'ations'):
        US_TO_AU.setdefault(stem + ending, stem.replace('z', 's') + ending)
US_TO_AU.update({'labeling': 'labelling', 'labeled': 'labelled', 'modeling': 'modelling', 'modeled': 'modelled',
                 'traveling': 'travelling', 'canceled': 'cancelled', 'canceling': 'cancelling', 'catalog': 'catalogue',
                 'catalogs': 'catalogues', 'centers': 'centres', 'centered': 'centred', 'fiber': 'fibre', 'theater': 'theatre',
                 'neighbor': 'neighbour', 'neighbors': 'neighbours', 'humor': 'humour', 'flavor': 'flavour'})
US_RE = re.compile(r"\b(" + "|".join(sorted(US_TO_AU, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def house_style(text: str) -> str:
    """Shown text never carries an em or en dash. With spelling "au" or "uk" in settings, US spellings
    also become British forms (organise, colour, centre)."""
    text = text.replace("\ufffd", "")  # whisper leaves replacement characters where it lost a byte
    text = re.sub(r"\s*[\u2014\u2013]\s*", ", ", text)
    if STYLE.get('spelling') not in ('au', 'uk'):
        return text

    def swap(match):
        au = US_TO_AU[match.group(0).lower()]
        return au.capitalize() if match.group(0)[0].isupper() else au
    return US_RE.sub(swap, text)


def money(usd) -> str:
    return format_money(usd, STYLE.get('currency'))


def esc(value):
    return html.escape(house_style('' if value is None else str(value)), quote=True)


def safe_url(value):
    parsed = urlparse(value or '')
    return esc(value) if parsed.scheme in ('http', 'https') and parsed.netloc else '#'


def fmt(value, suffix=''):
    return f'{value:.2f}{suffix}' if isinstance(value, (int, float)) else 'n/a'


def table(headers, rows):
    head = ''.join(f'<th>{esc(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows)
    return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def chart(posts, bands, hi):
    dated = sorted(posts, key=lambda p: p.get('posted_at') or '')
    values = sorted(r['multiple'] for r in bands.values() if isinstance(r.get('multiple'), (int, float)))
    cap = values[min(len(values) - 1, math.ceil(.95 * len(values)) - 1)] if values else hi
    cap = max(cap, hi, 1.0)
    width, height, left, right, top, bottom = 900, 310, 45, 18, 20, 38
    plot_w, plot_h = width - left - right, height - top - bottom
    y = lambda v: top + plot_h * (1 - min(v, cap) / cap)
    lines = [f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>',
             f'<line class="axis" x1="{left}" y1="{top + plot_h}" x2="{width - right}" y2="{top + plot_h}"/>']
    lines.append(f'<text x="2" y="{top + 4}">{fmt(cap)}x+</text>')
    for value, style in ((1.0, 'reference'), (hi, 'limit')):
        lines.append(f'<line class="{style}" x1="{left}" y1="{y(value):.1f}" x2="{width-right}" y2="{y(value):.1f}"/>')
        lines.append(f'<text x="2" y="{y(value) + 4:.1f}">{fmt(value)}x</text>')
    for i, post in enumerate(dated):
        row = bands.get(str(post['post_id']), {})
        multiple = row.get('multiple')
        if not isinstance(multiple, (int, float)):
            continue
        x = left + plot_w * (i / max(1, len(dated) - 1))
        band = row.get('band', 'normal')
        css = band if band in ('outlier', 'dud', 'climbing') else 'normal'
        lines.append(f'<circle class="{css}-dot" cx="{x:.1f}" cy="{y(multiple):.1f}" r="4"><title>{esc(post.get("post_id"))}: {fmt(multiple)}x</title></circle>')
    if dated:
        lines.append(f'<text x="{left}" y="{height-8}">{esc(local_iso(dated[0].get("posted_at")))}</text>')
        lines.append(f'<text x="{width-115}" y="{height-8}">{esc(local_iso(dated[-1].get("posted_at")))}</text>')
    return f'<div class="chart"><svg viewBox="0 0 {width} {height}" role="img" aria-label="Post performance over time">{"".join(lines)}</svg></div>'


def item_html(item):
    """Plain strings stay as they are; playbook dicts become 'Key: value' runs."""
    if isinstance(item, dict):
        return ' · '.join(f'<b>{esc(key.replace("_", " ").title())}:</b> {esc(value)}'
                          for key, value in item.items() if value not in (None, '', []))
    return esc(item)


def listed(items):
    if isinstance(items, str):
        items = [items]
    return '<ul class="list">' + ''.join(f'<li>{item_html(item)}</li>' for item in (items or [])) + '</ul>'


def audience_of(playbook) -> dict:
    """Who the run is for: 'me' (the user's own brand), 'client' (a client's brand) or 'creator' (the person analysed)."""
    audience = dict((playbook or {}).get('audience') or {})
    audience['mode'] = audience.get('mode') if audience.get('mode') in ('me', 'client', 'creator') else 'me'
    return audience


def tabs_for(audience) -> list:
    if audience['mode'] != 'creator':
        return list(TABS)
    names = {'build': 'How you build a post', 'best': 'Your best posts'}
    return [(tab_id, names.get(tab_id, label)) for tab_id, label in TABS if tab_id != 'yours']


TABS = (('start', 'Start here'), ('wins', 'What wins'), ('build', 'How they build a post'),
        ('best', 'Their best posts'), ('yours', 'Your versions'), ('sure', 'Review panel'),
        ('data', 'Raw data'))


def joins(a: str, b: str) -> str | None:
    """'We do about 1.' + '2 million.' or 'in L.' + 'A.' were cut by the splitter: give the joiner, else None."""
    a, b = a.strip(), b.strip()
    if re.search(r'\d\.$', a) and re.match(r'\d', b):
        return ''
    if re.search(r'\b[A-Z]\.$', a) and re.match(r'[A-Z]\.', b):
        return ' '
    return None


def tidy_spoken(text: str) -> str:
    """Whisper writes '1.3' as '1. 3' mid-sentence: put the decimal back for display."""
    return re.sub(r'(?<=\d)\. (?=\d)', '.', text)


def merged_texts(sentences) -> list:
    out = []
    for s in sentences:
        text = str(s.get('text') if isinstance(s, dict) else s or '')
        glue = joins(out[-1], text) if out else None
        if glue is not None:
            out[-1] = out[-1].rstrip() + glue + text.strip()
        else:
            out.append(text)
    return out


def opening(post_id, posts, features, cap=22):
    post = posts.get(str(post_id), {})
    feat = features.get(str(post_id), {})
    text = str(feat.get('segments', {}).get('hook_text') or (post.get('caption') or '').split('\n')[0]).strip()
    if feat.get('sentences') and re.search(r'(\d|\b[A-Z])\.$', text):
        whole, joined = merged_texts(feat['sentences']), ''
        for part in whole:  # take whole sentences until the hook is covered
            joined = (joined + ' ' + part.strip()).strip()
            if len(joined) >= len(text):
                break
        text = joined or text
    text = tidy_spoken(text)
    if len(text.split()) > cap:
        words = re.split(r'(?<=[.!?])\s+', text, maxsplit=1)[0].split()
        text = ' '.join(words[:cap]) + ('\u2026' if len(words) > cap else '')
    return text


def hook_key(text) -> str:
    """A hook with any leading tag ("[Result]", "Curiosity:") and punctuation removed, for matching."""
    text = re.sub(r'^\s*(\[[^\]]*\]|\([^)]*\)|[A-Za-z][A-Za-z /&-]{1,30}:)\s*', '', str(text or ''))
    return ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', text.lower().replace('\u2019', '').replace("'", '')).split())


def same_hook(option, chosen) -> bool:
    a, b = hook_key(option), hook_key(chosen)
    return bool(a and b) and (a == b or a in b or b in a)


def post_link(post):
    return f'<a href="{safe_url(post.get("url"))}">Open post</a>' if post else ''


def rate_bars(numbers, hit_word='took off', base_label='All posts'):
    try:
        hits, n, base = int(numbers['hits']), int(numbers['n']), float(numbers['base'])
        if n <= 0 or not math.isfinite(base):
            return ''
    except (KeyError, TypeError, ValueError, OverflowError):
        return ''
    rate = min(1, max(0, hits / n))
    base = min(1, max(0, base))
    return (f'<div class="mini-chart"><svg viewBox="0 0 520 95" role="img" '
            f'aria-label="This kind of post: {hits} of {n}; {base_label.lower()}: {base:.0%}">'
            '<text x="0" y="16">This kind of post</text><rect class="track" x="0" y="23" width="520" height="13"/>'
            f'<rect class="hit" x="0" y="23" width="{520 * rate:.1f}" height="13"/>'
            f'<text x="0" y="62">{base_label}</text><rect class="track" x="0" y="69" width="520" height="13"/>'
            f'<rect class="base" x="0" y="69" width="{520 * base:.1f}" height="13"/></svg>'
            f'<p class="muted">{hits} of {n} {hit_word}. {base_label}: {base:.0%}.</p></div>')


def embedded_visuals(work):
    source = read_json(work / 'visuals.json') if (work / 'visuals.json').exists() else {}
    result, full_bytes = {}, 0
    for post_id, entry in source.items():
        if not isinstance(entry, dict):
            continue
        media = {'thumb': None, 'full': []}
        for kind, paths in (('thumb', [entry.get('thumb')]), ('full', (entry.get('frames') or []) + (entry.get('images') or []))):
            for path in paths:
                if not isinstance(path, str):
                    continue
                file = (work / path).resolve()
                if not file.is_relative_to(work.resolve()) or file.suffix.lower() not in ('.jpg', '.jpeg') or not file.is_file():
                    continue
                size = file.stat().st_size
                if size > 250_000 or (kind == 'full' and full_bytes + size > 9_000_000):
                    continue
                uri = 'data:image/jpeg;base64,' + base64.b64encode(file.read_bytes()).decode('ascii')
                if kind == 'thumb':
                    media['thumb'] = uri
                else:
                    media['full'].append(uri)
                    full_bytes += size
        result[str(post_id)] = media
    return result


def picture_item(item, posts, features):
    if not isinstance(item, dict) or 'text' not in item:
        return f'<li>{item_html(item)}</li>'
    bits = ['<li>']
    if item.get('tag'):
        bits.append(f'<span class="chip">{esc(item["tag"])}</span>')
    bits.append(esc(item.get('text')))
    stat = item.get('stat') or {}
    if isinstance(stat, dict) and isinstance(stat.get('hits'), (int, float)) and isinstance(stat.get('n'), (int, float)) and stat['n'] > 0:
        bits.append(f'<div class="mini-bar" aria-label="{esc(stat["hits"])} of {esc(stat["n"])}"><i style="width:{min(100, max(0, 100 * stat["hits"] / stat["n"])):.1f}%"></i></div><small>{esc(stat["hits"])} of {esc(stat["n"])}</small>')
    if item.get('quote_post_id'):
        quote = (posts.get(str(item['quote_post_id']), {}).get('caption') or '').split('\n')[0].strip() \
            if item.get('quote_field') == 'title' else opening(item['quote_post_id'], posts, features)
        if quote:
            bits.append(f'<span class="quote-chip">“{esc(quote)}”</span>')
    bits.append('</li>')
    return ''.join(bits)


def picture_chart(posts, bands, hi, visuals, featured_ids=(), features=None):
    dated = sorted(posts, key=lambda p: p.get('posted_at') or '')
    by_id = {str(p['post_id']): p for p in posts}
    values = sorted(row['multiple'] for row in bands.values() if isinstance(row.get('multiple'), (int, float)) and row['multiple'] > 0)
    cap = max(1, hi, values[min(len(values) - 1, math.ceil(.98 * len(values)) - 1)] if values else hi)
    width, height, left, top, plot_w, plot_h = 1000, 390, 56, 28, 920, 310
    low = .1
    y = lambda v: top + plot_h * (1 - min(1, max(0, (math.log10(max(low, v)) - math.log10(low)) / (math.log10(cap) - math.log10(low)))))
    lines = [f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}"/>',
             f'<line class="axis" x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}"/>']
    for value, css in ((1, 'reference'), (hi, 'limit')):
        lines.append(f'<line class="{css}" x1="{left}" y1="{y(value):.1f}" x2="{left+plot_w}" y2="{y(value):.1f}"/><text x="2" y="{y(value)+4:.1f}">{value:g}x</text>')
    lines.append(f'<text x="2" y="{top+4}">{cap:.1f}x+</text>')
    count = max(1, len(dated) - 1)
    for i, post in enumerate(dated):
        post_id = str(post['post_id'])
        row = bands.get(post_id, {})
        multiple = row.get('multiple')
        plotted = multiple if isinstance(multiple, (int, float)) else .1
        x = left + plot_w * i / count
        yy = y(plotted)
        band = row.get('band')
        css = band if band in ('outlier', 'dud', 'climbing') else 'normal'
        target = f'best-post-{post_id}' if post_id in featured_ids else f'data-post-{post_id}'
        tooltip = f'{local_iso(post.get("posted_at"))} · {post.get("format") or ""} · {opening(post_id, by_id, features or {})} · {f"{multiple:.1f}x" if isinstance(multiple, (int, float)) else "no metric"}'
        thumb = visuals.get(post_id, {}).get('thumb')
        mark = (f'<image href="{thumb}" x="{x-13:.1f}" y="{yy-13:.1f}" width="26" height="26" preserveAspectRatio="xMidYMid slice"/>'
                if thumb else f'<rect class="{css}-dot" x="{x-10:.1f}" y="{yy-10:.1f}" width="20" height="20" rx="3"/>')
        lines.append(f'<a class="plot-post" data-post="{esc(post_id)}" href="#{esc(target)}" tabindex="0"><title>{esc(tooltip)}</title>{mark}</a>')
    if dated:
        lines.append(f'<text x="{left}" y="{height-12}">{esc(local_iso(dated[0].get("posted_at")))}</text><text x="{width-120}" y="{height-12}">{esc(local_iso(dated[-1].get("posted_at")))}</text>')
    return f'<div class="chart one-picture"><svg viewBox="0 0 {width} {height}" role="img" aria-label="Every post in one picture">{"".join(lines)}</svg></div><p class="swipe-hint">Swipe the chart sideways to see every post.</p>'


def anatomy(post_id, features, labels):
    raw_sentences = features.get(post_id, {}).get('sentences') or []
    raw_roles = labels.get('sentences', {}).get(post_id) or []
    # A list number on its own line ("1.") reads as part of the next item, so show them together.
    sentences, roles, carry = [], [], None
    for i, sentence in enumerate(raw_sentences):
        if re.fullmatch(r'\(?\d{1,3}[.)]', (sentence.get('text') or '').strip()):
            carry = sentence
            continue
        if carry:
            sentence = {**sentence, 'text': f"{carry['text']} {sentence.get('text', '')}",
                        'start_s': carry.get('start_s', sentence.get('start_s'))}
            carry = None
        sentences.append(sentence)
        roles.append(raw_roles[i] if i < len(raw_roles) else {})
    if not sentences:
        return '<p class="muted">No script available.</p>'
    timed = all(isinstance(s.get('start_s'), (int, float)) and isinstance(s.get('end_s'), (int, float)) for s in sentences)
    weights = [max(.1, s['end_s'] - s['start_s']) if timed else 1 for s in sentences]
    total = sum(weights)
    bars, beats, legend = [], [], []
    skip = set()
    for i, sentence in enumerate(sentences):
        if i in skip:
            continue
        text, weight = sentence.get('text') or '', weights[i]
        j = i
        while j + 1 < len(sentences) and joins(text, sentences[j + 1].get('text') or '') is not None:
            text = text.rstrip() + joins(text, sentences[j + 1].get('text') or '') + (sentences[j + 1].get('text') or '').strip()
            weight += weights[j + 1]
            j += 1
            skip.add(j)
        sentence = dict(sentence, text=tidy_spoken(text))
        role = roles[i].get('role', {}).get('value', 'other') if i < len(roles) else sentence.get('position', 'other')
        role = role if role in ('hook', 'claim', 'setup', 'evidence', 'proof', 'payoff', 'benefit', 'cta', 'ending',
                                'instruction', 'reframe', 'objection', 'story_beat') else 'other'
        role_label = role.replace('_', ' ')
        if role not in legend:
            legend.append(role)
        bars.append(f'<i class="role-{role}" style="width:{weight/total*100:.2f}%" title="{esc(role)}: {esc(sentence.get("text"))}"></i>')
        at = sentence.get('start_s', 0)
        marker = f'{int(at)//60}:{int(at)%60:02d}' if timed else f'Line {i+1}'
        beats.append(f'<li><time>{esc(marker)}</time> <span class="chip">{esc(role_label)}</span> {esc(sentence.get("text"))}</li>')
    key = ''.join(f'<span><i class="role-{role}"></i>{esc(role.replace("_", " "))}</span>' for role in legend)
    lines = f'<ol class="beat-list">{"".join(beats)}</ol>'
    if len(beats) > 12:
        lines = f'<details class="beats"><summary>Every line, in order ({len(beats)})</summary>{lines}</details>'
    return f'<div class="anatomy" aria-label="Script anatomy">{"".join(bars)}</div><div class="anatomy-legend">{key}</div>{lines}'


LENGTH_NAMES = {'under_15s': 'Under 15 seconds', '15_to_30s': '15 to 30 seconds', '30_to_60s': '30 to 60 seconds',
                '60_to_90s': '60 to 90 seconds', 'over_90s': 'Over 90 seconds', 'short': 'Short caption (no video)',
                'medium': 'Medium caption (no video)', 'long': 'Long caption (no video)'}


LENGTH_ORDER = ('Under 30 seconds', '30 to 60 seconds', '60 to 90 seconds', '90 seconds to 3 minutes', 'Over 3 minutes')


def length_key(post, features):
    """A video's real length band (the post's own duration, not the window we transcribed); captions keep their bucket."""
    seconds = post.get('duration_s') or (features.get(str(post['post_id']), {}).get('tempo') or {}).get('duration_s')
    if (post.get('format') or '') in ('video', 'reel', 'short') and isinstance(seconds, (int, float)) and seconds > 0:
        for limit, name in ((30, LENGTH_ORDER[0]), (60, LENGTH_ORDER[1]), (90, LENGTH_ORDER[2]), (180.5, LENGTH_ORDER[3])):
            if seconds < limit:
                return name
        return LENGTH_ORDER[4]
    bucket = features.get(str(post['post_id']), {}).get('length_bucket')
    return LENGTH_NAMES.get(bucket, bucket)


def length_rows(posts, features, outliers) -> list:
    bands = outliers.get('posts') or {}
    groups = {}
    for post in posts:
        band = (bands.get(str(post['post_id'])) or {}).get('band')
        if band in ('outlier', 'normal', 'dud'):
            groups.setdefault(length_key(post, features), []).append(band)
    order = {name: i for i, name in enumerate(LENGTH_ORDER)}
    return [{'value': name, 'n': len(group), 'outliers': group.count('outlier'), 'outlier_rate': group.count('outlier') / len(group)}
            for name, group in sorted(groups.items(), key=lambda pair: order.get(pair[0], 99)) if name]


def nice_value(key, value) -> str:
    if key == 'length_bucket' and value in LENGTH_NAMES:
        return LENGTH_NAMES[value]
    text = str(value).replace('_', ' ').strip()
    return text[:1].upper() + text[1:]


def plural(n, word) -> str:
    return f'{n} {word}' if n == 1 else f'{n} {word}s'


def kinds_panel(posts, features, labels, patterns, outliers, visuals, featured_ids, media=None):
    grad = patterns.get('graduation') or {}
    keys = (('format', 'Format'), ('hook_type', 'Opening'), ('structure', 'Structure'),
            ('topic', 'Topic'), ('length_bucket', 'Length'), ('ending', 'Ending'))
    lifts = grad.get('lifts', {}) if grad else patterns.get('lifts', {})
    bits = ['<h3>Which kinds win?</h3><div class="kind-tabs" role="tablist" aria-label="Post kinds">']
    for i, (key, label) in enumerate(keys):
        bits.append(f'<button type="button" data-kind="{key}" aria-selected="{"true" if i == 0 else "false"}">{label}</button>')
    bits.append('</div>')
    for i, (key, label) in enumerate(keys):
        bits.append(f'<div class="kind-list" data-kind-list="{key}"{"" if i == 0 else " hidden"}>')
        rows = lifts.get(key) or patterns.get('lifts', {}).get(key, [])
        if key == 'length_bucket' and not grad:
            rows = length_rows(posts, features, outliers)
        for row in rows:
            value = row.get('value')
            ids = []
            for post in posts:
                pid = str(post['post_id'])
                if key == 'format':
                    candidate = post.get('format')
                elif key == 'length_bucket' and not grad:
                    candidate = length_key(post, features)
                elif key == 'length_bucket':
                    candidate = features.get(pid, {}).get(key)
                else:
                    answer = labels.get('posts', {}).get(pid, {}).get(key, {})
                    candidate = answer.get('value') if isinstance(answer, dict) else answer
                if str(candidate) == str(value):
                    ids.append(pid)
            rate = row.get('outlier_rate')
            width = min(100, max(0, rate * 100)) if isinstance(rate, (int, float)) else 0
            rate_text = f'{rate:.0%}' if isinstance(rate, (int, float)) else 'n/a'
            rate_label = 'promoted' if grad and lifts.get(key) else 'took off'
            bits.append(f'<button type="button" class="kind-row" data-posts="{esc("|".join(ids))}"><strong>{esc(nice_value(key, value))}</strong><span>{esc(plural(row.get("n"), "post") if isinstance(row.get("n"), int) else row.get("n"))} · {rate_text} {rate_label}</span><span class="mini-bar"><i style="width:{width:.1f}%"></i></span></button>')
        bits.append('</div>')
    caption_only = sum(1 for row in (media or {}).values() if isinstance(row, dict) and row.get('status') == 'too_long')
    if caption_only:
        bits.append(f'<p class="muted">{plural(caption_only, "reel")} ran over 3 minutes, so {"its" if caption_only == 1 else "their"} labels come from the caption only. They still count in these lists.</p>')
    bits.append(picture_chart(posts, outliers.get('posts', {}), outliers.get('hi', 1.5), visuals, featured_ids, features))
    return ''.join(bits)


def guided_panels(playbook, posts, features, outliers, agreement, patterns=None, labels=None, visuals=None, analyses=None, media=None):
    patterns, labels, visuals, analyses = patterns or {}, labels or {}, visuals or {}, analyses or {}
    by_id = {str(post['post_id']): post for post in posts}
    featured_ids = {str(item.get('post_id')) for key in ('best_posts', 'misses') for item in (playbook or {}).get(key, [])}
    plot = ('<h3>Every post in one picture</h3><div class="decode-controls"><span class="decode-count" aria-live="polite">'
            f'Decoding {len(posts)} / {len(posts)}</span><button type="button" class="decode-stop">Stop</button>'
            '<button type="button" class="decode-replay">Replay</button></div>' +
            picture_chart(posts, outliers.get('posts', {}), outliers.get('hi', 1.5), visuals, featured_ids, features))
    if not playbook:
        return [plot + '<p>Not written yet. Playbook not written yet.</p>',
                '<p>Not written yet. Playbook not written yet.</p>' + kinds_panel(posts, features, labels, patterns, outliers, visuals, featured_ids, media)] + ['<p>Not written yet. Playbook not written yet.</p>'] * 4
    parts = []
    picture = playbook.get('picture') or {}
    start = [plot, f'<p class="lede reading">{esc(playbook.get("headline"))}</p>',
             '<h3>The playbook on one page</h3><div class="grid picture">']
    for key, label in (('hook', 'How they open'), ('argument', 'What they say'),
                       ('ending', 'How they finish'), ('tempo', 'Length and pace')):
        items = picture.get(key) or []
        if isinstance(items, (str, dict)):
            items = [items]
        start.append(f'<div class="panel"><h3>{label}</h3><ul class="list">{"".join(picture_item(item, by_id, features) for item in items)}</ul></div>')
    keep, drop = ('Keep doing this', 'Do less of this') if audience_of(playbook)['mode'] == 'creator' else ('Copy this', 'Skip this')
    start.append(f'</div><div class="two copy-skip"><div><h3>{keep}</h3><ul class="list">' +
                 ''.join(f'<li>✓ {item_html(item)}</li>' for item in (playbook.get('copy_this') or [])) +
                 f'</ul></div><div><h3>{drop}</h3><ul class="list">' +
                 ''.join(f'<li>✗ {item_html(item)}</li>' for item in (playbook.get('skip_this') or [])) + '</ul></div></div>')
    sure = playbook.get('how_sure') or {}
    start.append(f'<p class="reading"><a href="#sure">Review panel</a> {esc(sure.get("summary"))}</p>')
    parts.append(''.join(start))

    wins = []
    system = playbook.get('system') or {}
    if system:
        wins.append(f'<article class="finding"><h3>{esc(system.get("title"))}</h3><p class="reading">{esc(system.get("plain"))}</p>'
                    f'<ol class="flow">{"".join(f"<li>{esc(step)}</li>" for step in (system.get("steps") or []))}</ol></article>')
    for finding in playbook.get('findings') or []:
        post = by_id.get(str(finding.get('example_post_id')))
        confidence = finding.get('confidence') if finding.get('confidence') in ('strong', 'medium', 'hunch') else None
        wins.append(f'<article class="finding"><h3>{esc(finding.get("title"))}</h3>'
                    f'<p class="reading">{esc(finding.get("plain"))}</p>'
                    f'<p class="number-line">{esc(finding.get("number_line"))}</p>'
                    f'{rate_bars(finding.get("numbers") or {}, *(("came back", "All test ideas") if patterns.get("graduation") else ()))}'
                    + (f'<span class="chip confidence {confidence}">{confidence}</span>' if confidence else ''))
        if post:
            wins.append(f'<p class="reading">{esc(opening(post["post_id"], by_id, features))} {post_link(post)}</p>')
        wins.append((f'<p class="reading"><b>Try this:</b> {esc(finding.get("your_move"))}</p>' if finding.get('your_move') else '') + '</article>')
    wins.append(kinds_panel(posts, features, labels, patterns, outliers, visuals, featured_ids, media))
    parts.append(''.join(wins))

    build = ['<h3>Post shapes</h3>']
    for skeleton in playbook.get('skeletons') or []:
        if not isinstance(skeleton, dict):
            build.append(f'<p>{esc(skeleton)}</p>')
            continue
        beats = skeleton.get('beats') or []
        build.append(f'<h3>{esc(skeleton.get("name"))}</h3><div class="flow-chips">')
        for i, beat in enumerate(beats):
            if i:
                build.append('<em>→</em>')
            if isinstance(beat, dict):
                build.append(f'<span><b>{i+1}.</b> {esc(beat.get("beat"))} {esc(beat.get("plain"))}</span>')
            else:
                build.append(f'<span><b>{i+1}.</b> {esc(beat)}</span>')
        build.append(f'</div><p class="reading">{esc(skeleton.get("when"))}</p>')
    top = next((str(item.get('post_id')) for item in (playbook or {}).get('best_posts') or [] if str(item.get('post_id')) in features), None)
    top = top or next((str(r['post_id']) for r in patterns.get('top_outliers', []) if str(r.get('post_id')) in features), None)
    if not top:
        ranked = sorted(((row.get('multiple'), pid) for pid, row in (outliers.get('posts') or {}).items()
                         if isinstance(row.get('multiple'), (int, float)) and pid in features), reverse=True)
        top = ranked[0][1] if ranked else None
    if top:
        build.append(f'<h3>Script anatomy</h3><p>{esc(opening(top, by_id, features))}</p>{anatomy(top, features, labels)}')
    build.append('<h3>Ways to open</h3>')
    for hook in playbook.get('hook_templates') or []:
        if not isinstance(hook, dict):
            build.append(f'<div class="pre mono">{esc(hook)}</div>')
            continue
        post = by_id.get(str(hook.get('example_post_id')))
        build.append(f'<div class="pre mono">{esc(hook.get("template"))}</div>'
                     f'<p class="reading">{esc(hook.get("plain_why") or hook.get("why"))}</p>')
        if hook.get('n') is not None and hook.get('hits') is not None:
            build.append(f'<p>{esc(hook["n"])} posts, {esc(hook["hits"])} took off</p>')
        if post:
            build.append(f'<p class="reading">{esc(opening(post["post_id"], by_id, features))} {post_link(post)}</p>')
    build.append('<h3>Scripts to try</h3>')
    for script in playbook.get('script_templates') or []:
        if isinstance(script, dict):
            build.append(f'<h3>{esc(script.get("name"))}</h3><p>{esc(script.get("target_length"))} · {esc(script.get("pace") or script.get("tempo"))}</p>'
                         f'<div class="pre">{esc(script.get("script"))}</div>')
        else:
            build.append(f'<div class="pre">{esc(script)}</div>')
    parts.append(''.join(build))

    best = []
    for key, label, css in (('best_posts', 'Posts that took off', ''), ('misses', 'Posts that missed', ' quiet')):
        best.append(f'<h3>{label}</h3>')
        for item in playbook.get(key) or []:
            post_id = str(item.get('post_id'))
            post = by_id.get(post_id, {})
            row = (outliers.get('posts') or {}).get(post_id, {})
            multiple = row.get('multiple')
            best.append(f'<article id="best-post-{esc(post_id)}" class="post-card{css}">')
            media = visuals.get(post_id, {})
            frames = media.get('full') or ([media['thumb']] if media.get('thumb') else [])
            best.append('<div class="media-strip" aria-label="Post media">' + ''.join(f'<img src="{src}" alt="Post media">' for src in frames) + '</div>')
            chips = [(key, f"{(post.get('metrics') or {}).get(key):,}") for key in ('views', 'likes', 'comments', 'shares')
                     if (post.get('metrics') or {}).get(key) is not None]
            chips += [('Performance', f'{multiple:.1f} times their normal' if isinstance(multiple, (int, float)) else None),
                      ('Result', BAND_WORDS.get(row.get('band'), row.get('band'))),
                      ('Group', (tier_info(outliers, post.get('platform')).get('names') or {}).get(row.get('tier'))),
                      ('Format', post.get('format')),
                      ('Length', clock(post.get('duration_s') or features.get(post_id, {}).get('tempo', {}).get('duration_s'))),
                      ('Date', day_text(post.get('posted_at')))]
            best.append('<div class="stat-chips">' + ''.join(f'<span class="chip">{esc(name)}: {esc(value)}</span>' for name, value in chips if value is not None) + '</div>')
            best.append(f'<p>{post_link(post)}</p><h3>Inside the post</h3><p class="lede reading">{esc(opening(post_id, by_id, features))}</p>{anatomy(post_id, features, labels)}')
            analysis = analyses.get(post_id) or {}
            if analysis:
                hook, argument, ending = analysis.get('hook') or {}, analysis.get('argument') or {}, analysis.get('ending') or {}
                if item.get('why'):
                    best.append(f'<p class="reading"><b>In short:</b> {esc(item.get("why"))}</p>')
                best.append('<div class="breakdown">')
                best.append(f'<div><h4>Hook</h4><p>{esc(hook.get("line"))}</p><p>{esc(hook.get("why"))}</p></div>')
                best.append(f'<div><h4>Argument</h4><p>{esc(argument.get("summary"))}</p>{listed(argument.get("beats"))}</div>')
                cta_html = f'<p>{esc(ending.get("cta"))}</p>' if str(ending.get('cta') or '').strip().lower() not in ('', 'none', 'n/a') else ''
                best.append(f'<div><h4>Ending</h4><p>{esc(ending.get("line"))}</p>{cta_html}<p>{esc(ending.get("why"))}</p></div>')
                best.append(f'<div><h4>What you see</h4><p>{esc(analysis.get("visual"))}</p></div>')
                best.append(f'<div><h4>{"What it had going for it" if css else "Why it worked"}</h4>{listed(analysis.get("drivers"))}</div><div><h4>What held it back</h4>{listed(analysis.get("drags"))}</div>')
                best.append(f'<div><h4>Borrow</h4><p>{esc(item.get("borrow") or analysis.get("borrow"))}</p></div></div>')
            else:
                best.append(f'<p class="reading">{esc(item.get("why"))}</p><p class="reading"><b>Borrow:</b> {esc(item.get("borrow"))}</p>')
            best.append('</article>')
    parts.append(''.join(best))

    yours = []
    for rebuild in playbook.get('rebuilds') or []:
        source_id = str(rebuild.get('source_post_id'))
        source = by_id.get(source_id, {})
        thumb = visuals.get(source_id, {}).get('thumb')
        row = (outliers.get('posts') or {}).get(source_id, {})
        yours.append(f'<article class="post-card"><h3>{esc(rebuild.get("title"))}</h3><div class="rebuild-layout"><aside>')
        if thumb:
            yours.append(f'<img src="{thumb}" alt="Source post thumbnail">')
        yours.append(f'<p>{esc(opening(source_id, by_id, features))}</p><div class="stat-chips">')
        for field in ('views', 'likes', 'comments', 'shares'):
            if (source.get('metrics') or {}).get(field) is not None:
                yours.append(f'<span class="chip">{field}: {esc(format(source["metrics"][field], ","))}</span>')
        if isinstance(row.get('multiple'), (int, float)):
            yours.append(f'<span class="chip">{row["multiple"]:.1f}x</span>')
        yours.append(f'</div><p>{post_link(source)}</p></aside><div><p class="eyebrow">{esc(str(rebuild.get("format") or "").replace("-", " "))}</p><h4>Hook options</h4>')
        chosen = rebuild.get('chosen_hook')
        options = rebuild.get('hook_options') or []
        pick = next((i for i, option in enumerate(options) if same_hook(option, chosen)), None) if chosen else None
        for i, option in enumerate(options):
            yours.append(f'<div class="hook-option{" chosen" if i == pick else ""}">{esc(option)}</div>')
        if chosen and pick is None:
            yours.append(f'<div class="hook-option chosen">{esc(chosen)}</div>')
        if chosen and rebuild.get('chosen_hook_why'):
            yours.append(f'<p><b>Why this hook:</b> {esc(rebuild.get("chosen_hook_why"))}</p>')
        yours.append(f'<div class="draft-head"><h4>Draft</h4><button type="button" class="copy-button">Copy</button></div><div class="pre draft-text">{esc(rebuild.get("draft"))}</div>')
        if rebuild.get('cta'):
            yours.append(f'<p><b>CTA:</b> {esc(rebuild["cta"])}</p>')
        if rebuild.get('structure_map'):
            yours.append('<h4>Structure map</h4>' + table(('Beat', 'Line'), [(esc(r.get('beat')), esc(r.get('line'))) for r in rebuild['structure_map']]))
        yours.append('<div class="stat-chips">')
        for name, value in (rebuild.get('checks') or {}).items():
            text = str(value)
            short = text if name == 'copy_distance' else re.split(r'\s\(|\.\s|;\s', text, maxsplit=1)[0]
            yours.append(f'<span class="chip" title="{esc(text)}">{esc(name.replace("_", " "))}: {esc(short)}</span>')
        for score in rebuild.get('scores') or []:
            yours.append(f'<span class="chip">{esc(score.get("label"))}: {esc(score.get("value"))}</span>')
        yours.append('</div>')
        yours.append(f'{listed(rebuild.get("notes"))}</div></div></article>')
    parts.append(''.join(yours) or '<p>No versions drafted yet.</p>')

    check = []
    for reviewer in playbook.get('review') or []:
        verdict = reviewer.get('verdict') if reviewer.get('verdict') in ('pass', 'fixed', 'flagged') else 'flagged'
        check.append(f'<article class="review-card"><h3>{esc(reviewer.get("role"))}</h3><span class="chip">{esc(verdict)}</span><p>{esc(reviewer.get("summary"))}</p>')
        check.append(table(('Claim', 'Verdict', 'Note'), [(esc(r.get('claim')), esc(r.get('verdict')), esc(r.get('note'))) for r in reviewer.get('items') or []]))
        check.append('</article>')
    check.append(f'<h3>How we did it</h3><p class="reading">{esc(sure.get("summary"))}</p><ol class="flow">')
    check.extend(f'<li>{esc(step)}</li>' for step in sure.get('steps') or [])
    check.append('</ol>')
    agreed = agreement or playbook.get('agreement') or {}
    names = {'hook_type': 'hook', 'structure': 'shape', 'evidence': 'proof', 'ending': 'ending'}
    for key, value in (agreed.get('by_question') or {}).items():
        if isinstance(value, (int, float)):
            check.append(f'<p class="reading">Jev and a second reader agreed on the {esc(names.get(key, key.replace("_", " ")))} '
                         f'{value:.0%} of the time.</p>')
    rows = []
    for row in playbook.get('red_team') or []:
        verdict = row.get('verdict', '')
        chip = {'keep': 'keep', 'fix': 'fixed', 'fixed': 'fixed', 'cut': 'cut'}.get(verdict, verdict)
        rows.append((esc(row.get('claim')), esc(row.get('check') or row.get('checked')),
                     f'<span class="chip">{esc(chip)}</span>', esc(row.get('note'))))
    if rows:
        check.append('<h3>Claims we checked</h3>' + table(('Claim', 'What we checked', 'Verdict', 'Note'), rows))
    check.append('<h3>Limits</h3>' + listed(playbook.get('limits')))
    parts.append(''.join(check))
    return parts


CHANNEL_NAMES = {'instagram': 'Instagram', 'youtube': 'YouTube', 'linkedin': 'LinkedIn', 'tiktok': 'TikTok', 'x': 'X'}
CHANNEL_ICONS = {
    'instagram': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="#e1306c" stroke-width="2.2"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="#e1306c" stroke-width="2.2"/><circle cx="17.4" cy="6.6" r="1.3" fill="#e1306c"/></svg>',
    'youtube': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="4.5" width="21" height="15" rx="4.5" fill="#ff0033"/><path d="M10 8.8v6.4l5.6-3.2z" fill="#fff"/></svg>',
    'linkedin': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="4" fill="#0a66c2"/><path d="M7 10.2v6.8M7 7v.1M11 17v-4.1a2.3 2.3 0 0 1 4.6 0V17M11 10.2V17" stroke="#fff" stroke-width="2.1" stroke-linecap="round" fill="none"/></svg>',
    'tiktok': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3.5v11a3.6 3.6 0 1 1-3.6-3.6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M14 3.5c.6 2.6 2.4 4.2 5 4.4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
    'x': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4l14 16M19 4L5 20" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
}


def channel_icon(platform) -> str:
    return CHANNEL_ICONS.get(platform, '')


def tier_info(outliers, platform) -> dict:
    """Which kind of split the account has (reach: tests vs main feed, format: Shorts vs long videos) and its names."""
    tiers = outliers.get('tiers') or {}
    if not tiers:
        return {}
    kind = tiers.get('kind') or 'reach'
    names = tiers.get('names') or ({'low': 'Shorts', 'high': 'long videos'} if kind == 'format' else
                                   {'low': 'test reels' if platform == 'instagram' else 'test posts', 'high': 'main feed'})
    return {'kind': kind, 'names': names}


def load_channel(work, playbook) -> dict:
    work = Path(work)
    posts_data = read_json(work / 'posts.json')
    ctx = {'work': work, 'playbook': playbook, 'posts_data': posts_data, 'posts': posts_data['posts'],
           'features': read_json(work / 'features.json'), 'outliers': read_json(work / 'outliers.json'),
           'labels': read_json(work / 'labels.json'), 'patterns': read_json(work / 'patterns.json'),
           'agreement': read_json(work / 'agreement.json') if (work / 'agreement.json').exists() else None,
           'visuals': embedded_visuals(work),
           'analyses': read_json(work / 'analyses.json') if (work / 'analyses.json').exists() else {},
           'media': read_json(work / 'media.json') if (work / 'media.json').exists() else {}}
    ctx['platform'] = (posts_data.get('platform') or '').lower()
    ctx['handle'] = posts_data.get('handle') or ''
    ctx['profile'] = PROFILE_URLS.get(ctx['platform'], '').format(ctx['handle'].lstrip('@')) if ctx['handle'] else ''
    ctx['dates'] = sorted(local_iso(p['posted_at']) for p in ctx['posts'] if p.get('posted_at'))
    ctx['window'] = window_text(ctx['dates'][0], ctx['dates'][-1]) if ctx['dates'] else ''
    ctx['tiers'] = tier_info(ctx['outliers'], ctx['platform'])
    ctx['usd'] = float(ctx['labels'].get('cost_usd') or 0)
    return ctx


def metric_of(post, key):
    return (post.get('metrics') or {}).get(key)


def format_bar(posts) -> str:
    counts = {key: sum((p.get('format') or '').lower() == key for p in posts) for key in ('video', 'short', 'image', 'carousel', 'text')}
    total = max(1, len(posts))
    return ('<div class="format-bar" aria-label="Post formats">'
            + ''.join(f'<i style="width:{n/total*100:.1f}%" title="{key}: {n}"></i>' for key, n in counts.items()) + '</div>')


def judged_bar(judged) -> str:
    if len(judged) <= 100:
        return '<div class="dots" aria-label="Judged posts">' + ''.join(f'<i class="{esc(r.get("band"))}"></i>' for r in judged) + '</div>'
    share = {b: sum(r.get('band') == b for r in judged) / len(judged) * 100 for b in ('outlier', 'normal', 'dud')}
    return ('<div class="band-bar" aria-label="Judged posts by band">'
            + ''.join(f'<i class="{b}" style="width:{w:.1f}%" title="{b}: {w:.0f}%"></i>' for b, w in share.items()) + '</div>')


def channel_numbers(ctx) -> dict:
    """The header numbers for one channel."""
    posts, outliers, playbook = ctx['posts'], ctx['outliers'], ctx['playbook']
    bands = outliers.get('posts') or {}
    metric = outliers.get('metric') or 'views'
    values = [metric_of(p, metric) for p in posts if isinstance(metric_of(p, metric), (int, float))]
    median = statistics.median(values) if values else 0
    weekly = {}
    for p in posts:
        if p.get('posted_at') and isinstance(metric_of(p, metric), (int, float)):
            moment = local_dt(p['posted_at'])
            if moment:
                weekly.setdefault(moment.strftime('%G-%V'), []).append(metric_of(p, metric))
    trend = [statistics.median(weekly[k]) for k in sorted(weekly)]
    spark = ''
    if trend:
        lo, high = min(trend), max(trend)
        points = ' '.join(f'{i * 100 / max(1, len(trend)-1):.1f},{26 - (v-lo) * 23 / max(1, high-lo):.1f}' for i, v in enumerate(trend))
        spark = f'<svg class="spark" viewBox="0 0 100 28" preserveAspectRatio="none" role="img" aria-label="Weekly median"><polyline points="{points}" fill="none" stroke="var(--accent)" stroke-width="2"/></svg>'
    interactions = [sum(metric_of(p, k) or 0 for k in ('likes', 'comments', 'shares')) for p in posts]
    judged = [r for r in bands.values() if r.get('band') in ('outlier', 'normal', 'dud')]
    tiers = ctx['tiers']
    tier_of = {str(pid): r.get('tier') for pid, r in bands.items()}
    metric_plain = esc((playbook or {}).get("metric_plain") or metric)
    median_label, median_sub = f'Median {metric_plain}', ''
    if tiers:
        by_tier = {t: [metric_of(p, metric) for p in posts if tier_of.get(str(p['post_id'])) == t and isinstance(metric_of(p, metric), (int, float))]
                   for t in ('high', 'low')}
        if by_tier['high']:
            median = statistics.median(by_tier['high'])
            median_label = f'Median {metric_plain}, {tiers["names"]["high"]}'
        if by_tier['low']:
            median_sub = f'<span class="sub">{esc(tiers["names"]["low"][:1].upper() + tiers["names"]["low"][1:])}: {statistics.median(by_tier["low"]):,.0f}</span>'
    # Test reels are judged against a tiny baseline, so their multiples run hot: on a reach split only the main feed competes.
    pool = [(pid, r) for pid, r in bands.items() if isinstance(r.get('multiple'), (int, float))
            and (tiers.get('kind') != 'reach' or r.get('tier') == 'high')]
    top_id, top_row = max(pool, key=lambda pair: pair[1]['multiple'], default=(None, {}))
    return {'metric': metric, 'median': median, 'median_label': median_label, 'median_sub': median_sub, 'spark': spark,
            'interactions': interactions, 'judged': judged, 'takeoff': sum(r.get('band') == 'outlier' for r in judged),
            'top_id': top_id, 'top_row': top_row, 'views': sum(metric_of(p, 'views') or 0 for p in posts),
            'best_label': 'Best main-feed post' if tiers.get('kind') == 'reach' else 'Best post',
            'median_short': 'median' + (f', {tiers["names"]["high"]}' if tiers and by_tier['high'] else '')}


def best_thumb(ctx, top_id) -> str:
    thumb = ctx['visuals'].get(top_id, {}).get('thumb')
    url = next((p.get('url') for p in ctx['posts'] if str(p.get('post_id')) == str(top_id)), '')
    image = f'<img class="thumb-best" src="{thumb}" alt="The best post">' if thumb else ''
    return f'<a class="thumb-link" href="{esc(url)}">{image}</a>' if image and url else image


def compact(n) -> str:
    n = float(n or 0)
    for size, unit in ((1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if abs(n) >= size:
            return f'{n / size:.1f}'.rstrip('0').rstrip('.') + unit
    return f'{n:,.0f}'


def tile(value, label, extra='', count=None) -> str:
    raw = str(value).replace(',', '')
    attrs = count or ''
    if count is None and raw.isdigit():
        n = int(raw)
        if n >= 1_000_000_000:
            value, attrs = f'{n/1e9:.1f}B', f' data-count="{n/1e9:.1f}" data-decimals="1" data-suffix="B"'
        elif n >= 1_000_000:
            value, attrs = f'{n/1e6:.1f}M', f' data-count="{n/1e6:.1f}" data-decimals="1" data-suffix="M"'
        else:
            attrs = f' data-count="{n}"'
    return f'<div class="stat"><b{attrs}>{esc(value)}</b><span>{label}</span>{extra}</div>'


def cost_tile(usd) -> str:
    mark = load_brand()['jev_mark']
    credit = (f'<a class="jev-credit" href="https://typesafe.ai"><img src="{mark}" alt="Jev by TypeSafe"><span>Labelled by <strong>Jev</strong></span></a>'
              if mark else '<span class="sub">Labelled by Jev</span>')
    symbol, rate, is_usd = currency_symbol_rate(STYLE.get('currency'))
    return (f'<div class="stat cost"><b id="ai-cost" data-cost="{usd:.6f}" data-rate="{rate}" data-symbol="{esc(symbol)}">'
            f'{esc(symbol)}{usd * rate:.2f}</b><span>AI cost{"" if is_usd else f" (US${usd:.2f})"}</span>{credit}</div>')


def single_tiles(ctx) -> list:
    n = channel_numbers(ctx)
    top_row, judged = n['top_row'], n['judged']
    tiles = [tile(len(ctx['posts']), 'Posts analysed', (f'<span class="sub">{esc(ctx["window"])}</span>' if ctx['window'] else '') + format_bar(ctx['posts'])),
             tile(f'{n["median"]:,.0f}', n['median_label'], n['median_sub'] + n['spark']),
             tile(f'{sum(n["interactions"]):,}', 'Interactions', f'<span class="sub">Median per post: {statistics.median(n["interactions"]):,.0f}</span>' if n['interactions'] else ''),
             tile(n['takeoff'], 'Took off', (f'<span class="sub">{n["takeoff"] / len(judged):.0%} of judged posts</span>' if judged else '') + judged_bar(judged)),
             tile(f'{top_row["multiple"]:.1f}x' if top_row else 'n/a', n['best_label'], best_thumb(ctx, n['top_id']),
                  f' data-count="{top_row["multiple"]:.1f}" data-decimals="1" data-suffix="x"' if top_row else '')]
    grad = ctx['patterns'].get('graduation')
    if grad:
        promoted, ideas = grad.get('promoted') or 0, grad.get('ideas') or 0
        tiles.append(tile(f'{promoted} of {ideas}', 'Promoted tests', f'<div class="mini-bar"><i style="width:{promoted/max(1,ideas)*100:.1f}%"></i></div>',
                          f' data-count="{promoted}" data-suffix=" of {ideas}"'))
    return tiles + [cost_tile(ctx['usd'])]


def multi_tiles(ctxs) -> list:
    """One stat strip for every channel together: totals, with each channel's share underneath."""
    nums = [channel_numbers(c) for c in ctxs]
    line = lambda c, text: f'<span class="sub ch-line">{channel_icon(c["platform"])}{text}</span>'
    dates = sorted(d for c in ctxs for d in c['dates'])
    total = sum(len(c['posts']) for c in ctxs)
    split = ('<div class="channel-bar" aria-label="Posts by channel">'
             + ''.join(f'<i class="ch-{esc(c["platform"])}" style="width:{len(c["posts"])/max(1,total)*100:.1f}%" title="{esc(CHANNEL_NAMES.get(c["platform"], c["platform"]))}: {len(c["posts"])}"></i>' for c in ctxs) + '</div>')
    tiles = [tile(total, 'Posts analysed', (f'<span class="sub">{esc(window_text(dates[0], dates[-1]))}</span>' if dates else '')
                  + ''.join(line(c, f'{len(c["posts"]):,} {esc(CHANNEL_NAMES.get(c["platform"], c["platform"]))}') for c in ctxs) + split)]
    views = sum(n['views'] for n in nums)
    if views:
        tiles.append(tile(f'{views:,}', 'Views', ''.join(line(c, f'{compact(n["median"])} {n["median_short"]}') for c, n in zip(ctxs, nums))))
    tiles.append(tile(f'{sum(sum(n["interactions"]) for n in nums):,}', 'Interactions',
                      ''.join(line(c, compact(sum(n['interactions']))) for c, n in zip(ctxs, nums))))
    judged = [r for n in nums for r in n['judged']]
    takeoff = sum(n['takeoff'] for n in nums)
    tiles.append(tile(takeoff, 'Took off', (f'<span class="sub">{takeoff / len(judged):.0%} of judged posts</span>' if judged else '') + judged_bar(judged)))
    best = max(((c, n) for c, n in zip(ctxs, nums) if n['top_row']), key=lambda pair: pair[1]['top_row']['multiple'], default=None)
    if best:
        c, n = best
        tiles.append(tile(f'{n["top_row"]["multiple"]:.1f}x', f'Best post, {esc(CHANNEL_NAMES.get(c["platform"], c["platform"]))}', best_thumb(c, n['top_id']),
                          f' data-count="{n["top_row"]["multiple"]:.1f}" data-decimals="1" data-suffix="x"'))
    return tiles + [cost_tile(sum(c['usd'] for c in ctxs))]


def raw_data_html(posts_data, posts, features, outliers, labels, patterns, agreement) -> str:
    parts = []
    parts.append('<h2>Raw data</h2><section><h3>Post performance over time</h3>')
    parts.append(chart(posts, outliers.get('posts', {}), outliers.get('hi', 1.5)))
    tiers = outliers.get('tiers')
    if tiers:
        info = tier_info(outliers, (posts_data.get('platform') or '').lower())
        how = f'split at {tiers.get("cut"):,.0f} {esc(outliers.get("metric"))}' if tiers.get('cut') else 'split by format'
        parts.append(f'<p>Judged in two groups, {how}: {esc(tiers.get("low", {}).get("n"))} {esc(info["names"]["low"])} and '
                     f'{esc(tiers.get("high", {}).get("n"))} {esc(info["names"]["high"])}. Each post is compared with its own group.</p>')
    grad = patterns.get('graduation')
    if grad:
        parts.append(f'<h3>Posts that moved up</h3><p>{esc(grad.get("promoted"))} of {esc(grad.get("ideas"))} '
                     f'ideas moved from the low group to the high group.</p>')
        for key, rows in (grad.get('lifts') or {}).items():
            parts.append(f'<h3>{esc(key.replace("_", " ").title())}</h3>')
            parts.append(table(('Value', 'Posts', 'Moved up', 'How often it took off', 'Lift'),
                               [(esc(row.get('value')), esc(row.get('n')), esc(row.get('outliers')),
                                 fmt(row.get('outlier_rate') * 100 if row.get('outlier_rate') is not None else None, '%'),
                                 fmt(row.get('lift'), 'x')) for row in rows]))
    parts.append('</section><section><h2>What moves the number</h2>')
    keys = ('hook_type', 'structure', 'topic', 'evidence', 'emotion', 'advice', 'identity', 'ending',
            'payoff_delivered', 'specificity', 'format', 'length_bucket', 'weekday',
            'cta_share', 'cta_follow', 'cta_comment_keyword', 'cta_link', 'cta_question')
    for key in keys:
        parts.append(f'<h3>{esc(key.replace("_", " ").title())}</h3>')
        rows = []
        for row in patterns.get('lifts', {}).get(key, []):
            chip = '<span class="chip">hunch</span>' if row.get('tier') == 'hunch' else ''
            outside = row.get('outside_top_shape') or {}
            cells = (esc(row.get('value')), esc(row.get('n')),
                     esc(f"{row.get('outliers')} ({row.get('outlier_ideas', row.get('outliers'))} ideas)"),
                     fmt(row.get('outlier_rate') * 100 if row.get('outlier_rate') is not None else None, '%'),
                     fmt(row.get('lift'), 'x'),
                     esc(f"{outside['outliers']} of {outside['n']}") if outside.get('n') else '<span class="muted">none</span>')
            if chip:
                cells = tuple(f'<span class="hunch">{cell}</span>' for cell in cells)
            rows.append((cells[0] + chip, *cells[1:]))
        shape = next((r.get('outside_top_shape', {}).get('shape') for r in patterns.get('lifts', {}).get(key, [])
                      if r.get('outside_top_shape')), None)
        parts.append(table(('Value', 'Posts', 'Posts that took off', 'How often it took off', 'Lift',
                            f'Posts outside {shape}' if shape else 'Outside top shape'), rows))
    repeats = patterns.get('repeats', [])
    if repeats:
        parts.append('<h3>Ideas posted more than once</h3>')
        parts.append(table(('Opening words', 'Times posted', 'Bands'),
                           [(esc(r['idea']), esc(r['posts']), esc(', '.join(f'{k} {v}' for k, v in r['bands'].items())))
                            for r in repeats[:15]]))
    parts.append('</section><section><h2>Tempo</h2>')
    rows = [(esc(key), fmt(row.get('spearman')), fmt(row.get('median_outlier')),
             fmt(row.get('median_normal')), fmt(row.get('median_dud')),
             esc(', '.join(f"{t['label']} {fmt(t['outlier_rate'])}" for t in row.get('terciles', []))))
            for key, row in patterns.get('tempo', {}).items()
            if row.get('spearman') is not None]  # no spread (every caption has 0 arrows on a video account): nothing to show
    parts.append(table(('Field', 'Spearman', 'Outlier median', 'Normal median', 'Dud median', 'Terciles'), rows))
    parts.append('</section><section><h2>Argument skeleton</h2><h3>Role sequences</h3>')
    sent = patterns.get('sentences', {})
    parts.append(table(('Sequence', 'Lift', 'Support'),
                       [(esc(' → '.join(row['sequence'])), fmt(row.get('lift'), 'x'), esc(row.get('support')))
                        for row in sent.get('ngrams', [])[:20]]))
    parts.append('<h3>Top outlier sequences</h3>')
    parts.append(listed([f"{' → '.join(r['sequence'])} ({r['count']})" for r in sent.get('sequences', [])]))
    parts.append('<h3>First role occurrence</h3>')
    parts.append(table(('Band', 'Claim', 'Evidence', 'Payoff', 'CTA'),
                       [(esc(band), *(fmt(values.get(key)) for key in ('claim', 'evidence', 'payoff', 'cta')))
                        for band, values in sent.get('timing', {}).items()]))
    parts.append('</section>')
    parts.append('<section><h2>Every post</h2><div class="posts">')
    for post in sorted(posts, key=lambda p: p.get('posted_at') or '', reverse=True):
        post_id = str(post['post_id'])
        feat = features.get(post_id, {})
        row = outliers.get('posts', {}).get(post_id, {})
        band = row.get('band', 'unknown')
        hook = opening(post_id, {post_id: post}, features, cap=40) or post.get('caption', '')[:160]
        parts.append(f'<details><summary id="data-post-{esc(post_id)}"><span>{esc(local_iso(post.get("posted_at")))}</span><span>{esc(post.get("format"))}</span><span class="chip {esc(band)}">{esc(band)}</span><b class="num">{fmt(row.get("multiple"), "x")}</b><span class="hook">{esc(hook)}</span></summary><div class="inside">')
        parts.append(f'<p><a href="{safe_url(post.get("url"))}">Open source post</a></p><h3>Labels</h3>')
        label = labels.get('posts', {}).get(post_id, {})
        parts.append(table(('Question', 'Answer'), [(esc(key), esc(value.get('level') if key == 'specificity' else value.get('flag') if key == 'payoff_delivered' else value.get('value'))) for key, value in label.items()]))
        parts.append('<h3>Tempo</h3>')
        parts.append(table(('Field', 'Value'), [(esc(key.replace('_', ' ')), esc(round(value, 1) if isinstance(value, float) else value)) for key, value in feat.get('tempo', {}).items()]))
        parts.append('<h3>Sentences</h3>')
        sentence_labels = labels.get('sentences', {}).get(post_id, [])
        for i, sentence in enumerate(feat.get('sentences', [])):
            role = sentence_labels[i].get('role', {}).get('value', 'unclear') if i < len(sentence_labels) else 'unlabelled'
            parts.append(f'<div class="sent {esc(role)}"><span class="muted">{esc(sentence.get("position"))} · {esc(role)}</span> {esc(sentence.get("text"))}</div>')
        parts.append('</div></details>')
    parts.append('</div></section><section><h2>Method</h2>')
    parts.append(f'<p>Data pulled: {esc(posts_data.get("pulled_at"))}. {esc(len(posts))} posts from {esc(posts_data.get("platform"))}.</p>')
    parts.append(f'<p>Metric: {esc(outliers.get("metric"))}. Median baseline: {esc(outliers.get("baseline", {}).get("global_median"))}.</p>')
    parts.append(f'<p>Outliers use a rolling median of nearby mature posts. High threshold: {esc(outliers.get("hi"))}x. Low threshold: {esc(outliers.get("lo"))}x. Age guard: {esc(outliers.get("min_age_hours"))} hours.</p>')
    parts.append(f'<p>Jev model: {esc(labels.get("model"))}. Calls: {esc(labels.get("calls"))}. Cost: {esc(money(labels.get("cost_usd")))}.</p>')
    if agreement:
        parts.append(f'<p>Blind agreement: {esc(agreement.get("n"))} posts. ' + ', '.join(f'{esc(key)} {fmt(value * 100)}%' for key, value in agreement.get('by_question', {}).items()) + '</p>')
    parts.append('</section>')
    return ''.join(parts)


def channel_sections(ctx, tabs, multi) -> str:
    ch = ctx['platform'] if multi else ''
    suffix = f'-{ch}' if multi else ''
    owner = f' data-channel="{esc(ch)}"' if multi else ''
    tag = (f'<p class="eyebrow channel-tag">{channel_icon(ch)}{esc(CHANNEL_NAMES.get(ch, ch))}</p>' if multi else '')
    contents = dict(zip([tab_id for tab_id, _ in TABS], guided_panels(
        ctx['playbook'], ctx['posts'], ctx['features'], ctx['outliers'], ctx['agreement'], ctx['patterns'],
        ctx['labels'], ctx['visuals'], ctx['analyses'], ctx['media'])))
    out = []
    for tab_id, label in tabs:
        if tab_id == 'data':
            body = raw_data_html(ctx['posts_data'], ctx['posts'], ctx['features'], ctx['outliers'], ctx['labels'],
                                 ctx['patterns'], ctx['agreement'])
        else:
            body = f'<h2>{label}</h2>{contents.get(tab_id, "")}'
        cost = f' data-cost="{ctx["usd"]:.6f}"' if tab_id == 'start' else ''
        out.append(f'<section class="tab-panel" id="{tab_id}{suffix}" data-tab="{tab_id}"{owner}{cost} role="tabpanel" '
                   f'aria-labelledby="tab-{tab_id}">{tag}{body}</section>')
    return ''.join(out)


def render(work: Path, playbook: dict | None, title: str, prepared=None, also=()) -> str:
    """One channel, or several (`also`: more (work, playbook) pairs) behind a channel switch."""
    settings = load_settings()
    STYLE.update(spelling=settings['spelling'], currency=settings['currency'], timezone=settings.get('timezone'))
    ctxs = [load_channel(work, playbook)] + [load_channel(w, pb) for w, pb in also]
    multi = len(ctxs) > 1
    first = ctxs[0]
    brand = load_brand()
    tabs = tabs_for(audience_of(first['playbook']))
    when = f'Prepared {esc(prepared_date(prepared or (first["playbook"] or {}).get("prepared")))}'
    by = (f' by <a href="{esc(brand["url"])}">{esc(brand["name"])}</a>' if brand['url'] else f' by {esc(brand["name"])}') if brand['name'] else ''

    def who(c, i=0):
        only = f' data-channel-only="{esc(c["platform"])}"' + (' hidden' if i else '') if multi else ''
        return (f'<a class="who" href="{esc(c["profile"])}"{only}>{esc(c["handle"])}</a>' if c['profile']
                else f'<span class="who"{only}>{esc(c["handle"])}</span>')

    def switch(c, i):
        name = esc(CHANNEL_NAMES.get(c['platform'], c['platform']))
        return (f'<button type="button" class="channel-switch" data-channel="{esc(c["platform"])}" '
                f'aria-pressed="{"true" if i == 0 else "false"}" title="{name}">{channel_icon(c["platform"])}<span>{name}</span></button>')

    if multi:
        switches = ''.join(switch(c, i) for i, c in enumerate(ctxs))
        lead = f'<span class="channel-switches" role="group" aria-label="Channels">{switches}</span>' + ''.join(who(c, i) for i, c in enumerate(ctxs))
    else:
        name = esc(CHANNEL_NAMES.get(first['platform'], first['platform']))
        lead = f'<span class="channel-icon" title="{name}" aria-label="{name}">{channel_icon(first["platform"])}</span>{who(first)}'
    parts = ['<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
             f'<title>{esc(title)}</title>', FONT, CSS, '<div class="wrap">',
             f'<header><p class="eyebrow">Creator teardown</p><h1>{esc(title)}</h1><p class="byline">{lead}<span class="sep">|</span>{when}{by}</p><div class="grid stats">']
    parts.extend(multi_tiles(ctxs) if multi else single_tiles(first))
    parts.append('</div></header><div class="menu-bar"><button type="button" class="menu-toggle" aria-expanded="false" aria-controls="report-menu">'
                 '<span class="burger" aria-hidden="true"><i></i><i></i><i></i></span><span class="menu-label">Start here</span><span class="menu-hint">Menu</span></button></div>'
                 '<div class="menu-backdrop" hidden></div>'
                 '<nav class="tabs" id="report-menu" role="tablist" aria-label="Report sections">'
                 '<div class="menu-head"><span>Sections</span><button type="button" class="menu-close" aria-label="Close menu">&times;</button></div>')
    if multi:
        parts.append('<div class="menu-channels" role="group" aria-label="Channels">' + ''.join(switch(c, i) for i, c in enumerate(ctxs)) + '</div>')
    suffix = f'-{first["platform"]}' if multi else ''
    for i, (tab_id, label) in enumerate(tabs):
        parts.append(f'<button type="button" role="tab" id="tab-{tab_id}" data-tab="{tab_id}" aria-controls="{tab_id}{suffix}" '
                     f'aria-selected="{"true" if i == 0 else "false"}">{label}</button>')
    if brand['name']:
        foot_logo = f'<img src="{brand["logo"]}" alt="">' if brand['logo'] else ''
        parts.append(f'<a class="menu-foot" href="{esc(brand["url"])}">{foot_logo}{esc(brand["name"])}</a>' if brand['url']
                     else f'<span class="menu-foot">{foot_logo}{esc(brand["name"])}</span>')
    parts.append('</nav>')
    for c in ctxs:
        parts.append(channel_sections(c, tabs, multi))
    logo = f'<img src="{brand["logo"]}" alt="">' if brand['logo'] else ''
    name = brand['name'] or 'Creator teardown'
    mark = f'<a class="brand" href="{esc(brand["url"])}">{logo}{esc(name)}</a>' if brand['url'] else f'<span class="brand">{logo}{esc(name)}</span>'
    source = (f'the creator\'s public posts on {" and ".join(esc(CHANNEL_NAMES.get(c["platform"], c["platform"])) for c in ctxs)}' if multi
              else f'{esc(first["handle"])}\'s public posts')
    parts.append(f'<footer class="site-footer">{mark}<p>{when}. Every number comes from {source}. Post labels by Jev from TypeSafe.</p></footer></div>')
    parts.append('''<script>(function(){
const costEl=document.getElementById('ai-cost'),SYM=costEl?.dataset.symbol||'US$',RATE=Number(costEl?.dataset.rate||1);
const tabs=[...document.querySelectorAll('.tabs [role="tab"]')],panels=[...document.querySelectorAll('.tab-panel')],switches=[...document.querySelectorAll('.channel-switch')];
let channel=(switches.find(s=>s.getAttribute('aria-pressed')==='true')||switches[0])?.dataset.channel||'',tab='start';
const panelFor=(t,c)=>panels.find(p=>p.dataset.tab===t&&(p.dataset.channel||'')===(c||''));
function syncLabel(){const t=document.querySelector('.tabs [aria-selected="true"]'),l=document.querySelector('.menu-label'),s=switches.find(x=>x.dataset.channel===channel);if(t&&l)l.textContent=(s?s.textContent.trim()+' · ':'')+t.textContent}
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches,played=new Set();let timer,marks=[],counter=null,usd=0;
function setStep(n){for(let i=0;i<marks.length;i++)marks[i].classList.toggle('pending',i>=n);if(counter)counter.textContent='Decoding '+n+' / '+marks.length+' · '+SYM+(usd*n/Math.max(1,marks.length)*RATE).toFixed(2)+' spent'}
function finish(){clearInterval(timer);setStep(marks.length)}
function play(){finish();const p=panelFor('start',channel);marks=p?[...p.querySelectorAll('.plot-post')]:[];counter=p?p.querySelector('.decode-count'):null;usd=Number(p?.dataset.cost||0);if(reduced||!marks.length){finish();return}const start=performance.now();setStep(0);timer=setInterval(()=>{const n=Math.min(marks.length,Math.round((performance.now()-start)/6000*marks.length));setStep(n);if(n>=marks.length)clearInterval(timer)},40)}
function decodeOnce(){if(!played.has(channel)){played.add(channel);play()}}
for(const b of document.querySelectorAll('.decode-stop'))b.addEventListener('click',finish);
for(const b of document.querySelectorAll('.decode-replay'))b.addEventListener('click',play);
function show(updateHash){if(!panelFor(tab,channel))tab='start';for(const p of panels)p.hidden=!(p.dataset.tab===tab&&(p.dataset.channel||'')===channel);for(const t of tabs){t.setAttribute('aria-selected',String(t.dataset.tab===tab));const p=panelFor(t.dataset.tab,channel);if(p)t.setAttribute('aria-controls',p.id)}for(const s of switches)s.setAttribute('aria-pressed',String(s.dataset.channel===channel));for(const h of document.querySelectorAll('[data-channel-only]'))h.hidden=h.dataset.channelOnly!==channel;if(updateHash){try{history.replaceState(null,'','#'+panelFor(tab,channel).id)}catch(e){}}syncLabel();if(tab==='start')decodeOnce()}
function open(t,updateHash){tab=t;show(updateHash)}
for(const t of tabs)t.addEventListener('click',()=>open(t.dataset.tab,true));
for(const s of switches)s.addEventListener('click',()=>{channel=s.dataset.channel;show(true)});
function followHash(){const id=decodeURIComponent(location.hash.slice(1)),el=id?document.getElementById(id):null,panel=el?(el.classList.contains('tab-panel')?el:el.closest('.tab-panel')):null;if(panel){channel=panel.dataset.channel||'';tab=panel.dataset.tab;show(false);if(el!==panel){const box=el.closest('details');if(box)box.open=true;el.scrollIntoView()}}else{if(id&&panelFor(id,channel))tab=id;show(false)}}
window.addEventListener('hashchange',followHash);followHash();
const menuToggle=document.querySelector('.menu-toggle'),menuBackdrop=document.querySelector('.menu-backdrop'),menuClose=document.querySelector('.menu-close');
function setMenu(on){document.body.classList.toggle('menu-open',on);if(menuBackdrop)menuBackdrop.hidden=!on;menuToggle?.setAttribute('aria-expanded',String(on));if(on)setTimeout(()=>document.querySelector('.tabs [aria-selected="true"]')?.focus(),50)}
menuToggle?.addEventListener('click',()=>setMenu(!document.body.classList.contains('menu-open')));menuBackdrop?.addEventListener('click',()=>setMenu(false));menuClose?.addEventListener('click',()=>{setMenu(false);menuToggle?.focus()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('menu-open')){setMenu(false);menuToggle?.focus()}});
for(const t of tabs)t.addEventListener('click',()=>{if(!document.body.classList.contains('menu-open'))return;setMenu(false);const p=document.getElementById(t.getAttribute('aria-controls')),bar=document.querySelector('.menu-bar');if(p)window.scrollTo(0,p.getBoundingClientRect().top+scrollY-(bar?.offsetHeight||0)-8)});
for(const s of document.querySelectorAll('.menu-channels .channel-switch'))s.addEventListener('click',()=>{setMenu(false);const p=panelFor(tab,channel),bar=document.querySelector('.menu-bar');if(p)window.scrollTo(0,p.getBoundingClientRect().top+scrollY-(bar?.offsetHeight||0)-8)});
for(const link of document.querySelectorAll('.one-picture a'))link.addEventListener('click',()=>{setTimeout(followHash,0)});
for(const tab of document.querySelectorAll('.kind-tabs button'))tab.addEventListener('click',()=>{const panel=tab.closest('.tab-panel');for(const button of panel.querySelectorAll('.kind-tabs button'))button.setAttribute('aria-selected',String(button===tab));for(const list of panel.querySelectorAll('[data-kind-list]'))list.hidden=list.dataset.kindList!==tab.dataset.kind;for(const mark of panel.querySelectorAll('.one-picture .plot-post'))mark.classList.remove('dim')});
for(const row of document.querySelectorAll('.kind-row'))row.addEventListener('click',()=>{const panel=row.closest('.tab-panel'),ids=new Set(row.dataset.posts.split('|'));for(const peer of panel.querySelectorAll('.kind-row'))peer.classList.toggle('active',peer===row);for(const mark of panel.querySelectorAll('.one-picture .plot-post'))mark.classList.toggle('dim',!ids.has(mark.dataset.post))});
for(const button of document.querySelectorAll('.copy-button'))button.addEventListener('click',async()=>{const block=button.closest('.post-card').querySelector('.draft-text'),value=block?.innerText||'';try{await navigator.clipboard.writeText(value);button.textContent='Copied'}catch(e){const selection=window.getSelection(),range=document.createRange();range.selectNodeContents(block);selection.removeAllRanges();selection.addRange(range);button.textContent='Select and copy'}});
if(!reduced){document.querySelectorAll('.stat').forEach((tile,i)=>{tile.style.animation='tile-rise .3s ease both';tile.style.animationDelay=(i*55)+'ms'});for(const number of document.querySelectorAll('.stat b[data-count]')){const target=Number(number.dataset.count),decimals=Number(number.dataset.decimals||0),suffix=number.dataset.suffix||'',start=performance.now();function tick(now){const fraction=Math.min(1,(now-start)/650);number.textContent=(target*fraction).toLocaleString(undefined,{minimumFractionDigits:decimals,maximumFractionDigits:decimals})+suffix;if(fraction<1)requestAnimationFrame(tick)}requestAnimationFrame(tick)}}
})()</script>''')
    page = ''.join(parts)
    limit = 15_000_000  # the artifact cap is 16MB: drop the largest post media first if a page runs over
    if len(page.encode('utf-8')) > limit:
        for ctx in reversed(ctxs):
            for media in reversed(list(ctx['visuals'].values())):
                for uri in reversed(media.get('full', [])):
                    page = page.replace(f'<img src="{uri}" alt="Post media">', '')
                    if len(page.encode('utf-8')) <= limit:
                        return page
    return page


def run(work: Path, *, playbook=None, title='Creator teardown', out=None, prepared=None, also=()) -> str:
    """`also`: more run folders (each with .work/ and playbook.json) shown as extra channels."""
    work = Path(work)
    if isinstance(playbook, (str, Path)):
        playbook = read_json(playbook)
    if playbook is None and (work / 'playbook.json').exists():
        playbook = read_json(work / 'playbook.json')
    channels = []
    for folder in also:
        folder = Path(folder)
        extra = folder / 'playbook.json'
        channels.append((folder / '.work', read_json(extra) if extra.exists() else None))
    page = render(work, playbook, title, prepared, channels)
    target = Path(out) if out else work / 'report.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding='utf-8')
    return page


def main():
    parser = argparse.ArgumentParser(description='Render the teardown as one self-contained HTML page.')
    parser.add_argument('--work', type=Path, required=True, help='the run .work folder')
    parser.add_argument('--playbook', type=Path)
    parser.add_argument('--title', default='Creator teardown')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--prepared', help='date shown as Prepared (YYYY-MM-DD); default playbook.prepared, else today')
    parser.add_argument('--also', type=Path, action='append', default=[],
                        help='another run folder for the same creator on a second channel (repeatable)')
    args = parser.parse_args()
    try:
        run(args.work, playbook=args.playbook, title=args.title, out=args.out, prepared=args.prepared, also=args.also)
    except ConfigError as exc:
        parser.exit(2, f'ERROR: {exc}\n')
    print(f"Report written to {args.out or args.work / 'report.html'}")


if __name__ == '__main__':
    main()

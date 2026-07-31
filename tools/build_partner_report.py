#!/usr/bin/env python3
"""Loupe — partner (boutique) engagement report generator.

Builds the private page we send a retail partner like Gemini so they can see
what their pieces are actually doing inside the app.

WHAT IT OPTIMISES FOR
  Rate over volume. The partnership is days old and the absolute numbers are
  small; a page led by "57 saves" reads as noise. A page led by "your dresses
  save at 4x the rate of your accessories" is useful on day three and stays
  useful at 100x the traffic. Volume is still reported, plainly, further down —
  a report that hides its denominator is not worth sending.

  It also has to survive the partner checking our arithmetic, so every rate is
  printed next to the app-wide figure for the same metric, over the same window,
  and the method is spelled out at the bottom.

PRIVACY MODEL (this is a static site, so there is no server to check a password)
  The page at /partners/<slug>/ contains NO numbers. It is a shell that reads
  ?k=<token> and fetches /partners/d/<token>.json. Without the token there is
  nothing to read — not hidden, absent. The token is a 22-char random string, so
  the data URL is not enumerable, and /partners/ is disallowed in robots.txt and
  marked noindex so it never reaches a search index.

  This is "unguessable link" security, the same model as a Google Doc shared by
  link. It is right for engagement stats a partner would happily be shown. It
  would NOT be right for anything genuinely confidential.

DATA
  PostHog (HogQL) when POSTHOG_API_KEY is set; otherwise the committed snapshot
  in data/<slug>.json, so the page can always be rebuilt and reviewed offline.
  A live run rewrites the snapshot, which keeps the numbers in git history and
  makes each week's report diffable against the last.

USAGE
  $env:POSTHOG_API_KEY="phx_..."          # optional; falls back to snapshot
  $env:POSTHOG_PROJECT_ID="489958"
  python tools/build_partner_report.py --partner gemini
  python tools/build_partner_report.py --partner gemini --rotate-key   # new URL
"""

import argparse
import datetime as dt
import html
import json
import math
import os
import pathlib
import secrets
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "tools" / "data"
CATALOG_URL = "https://cdn.jsdelivr.net/gh/HOboGoblin45/loupe-feed@main/loupe-feed/catalog.json"

POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.posthog.com").rstrip("/")
POSTHOG_KEY = os.environ.get("POSTHOG_API_KEY", "")
POSTHOG_PROJECT = os.environ.get("POSTHOG_PROJECT_ID", "489958")

WINDOW_DAYS = 45


# ─── data access ──────────────────────────────────────────────────────────────

def hogql(query):
    """Run one HogQL query. Returns list-of-rows, or None if we have no key."""
    if not POSTHOG_KEY:
        return None
    req = urllib.request.Request(
        f"{POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT}/query/",
        data=json.dumps({"query": {"kind": "HogQLQuery", "query": query}}).encode(),
        headers={
            "Authorization": f"Bearer {POSTHOG_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def fetch_catalog():
    with urllib.request.urlopen(CATALOG_URL, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


# ─── stats ────────────────────────────────────────────────────────────────────

def wilson(successes, trials, z=1.96):
    """95% CI on a rate. Printed on the page because a rate off 1,000 swipes is
    an estimate, and a partner who is told '11.9%' deserves the error bar."""
    if not trials:
        return 0.0, 0.0, 0.0
    p = successes / trials
    den = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / den
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def compute(partner_id, catalog, ph):
    """Everything the page shows, derived here so the HTML stays dumb."""
    products = catalog["products"]
    retailers = catalog.get("retailers", {})
    meta = retailers.get(partner_id, {})

    mine = [p for p in products if (p.get("retailer") or "").lower() == partner_id]
    if not mine:
        sys.exit(f"No products in the live catalog for retailer '{partner_id}'.")

    # Which of the partner's labels are theirs ALONE in our catalog. Engagement
    # for those brands is the partner's engagement with nothing else mixed in,
    # which is how we can report a rate before retailer-level telemetry (shipped
    # 2026-07-31) has accumulated. Once it has, `retailers` in brand_engagement
    # supersedes this and the proxy can go.
    by_brand_retailers = {}
    for p in products:
        by_brand_retailers.setdefault(p.get("brand", "?"), set()).add(
            (p.get("retailer") or "direct").lower()
        )
    my_brands = sorted({p["brand"] for p in mine})
    exclusive = sorted(b for b in my_brands if by_brand_retailers.get(b) == {partner_id})

    eng = ph["engagement"]          # {brand: [imps, likes, saves]}
    saves_by_product = ph["saves_by_product"]
    saves_by_category = ph["saves_by_category"]
    clicks = ph["clicks"]

    def tally(brands):
        i = sum(eng.get(b, [0, 0, 0])[0] for b in brands)
        l = sum(eng.get(b, [0, 0, 0])[1] for b in brands)
        s = sum(eng.get(b, [0, 0, 0])[2] for b in brands)
        return i, l, s

    imps, likes, saves = tally(exclusive)
    others = [b for b in eng if b not in set(exclusive)]
    a_imps, a_likes, a_saves = tally(others)

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else 0.0

    _, lo, hi = wilson(likes + saves, imps)

    # Category: share of the partner's FEED vs share of their SAVES. The ratio
    # is the single most actionable number here — it says what to send more of.
    feed_mix = {}
    for p in mine:
        feed_mix[p.get("category", "other")] = feed_mix.get(p.get("category", "other"), 0) + 1
    total_saves = sum(saves_by_category.values()) or 1
    cats = []
    for c, n in sorted(feed_mix.items(), key=lambda kv: -kv[1]):
        sv = saves_by_category.get(c, 0)
        cats.append({
            "category": c,
            "pieces": n,
            "feed_pct": pct(n, len(mine)),
            "saves": sv,
            "saves_pct": pct(sv, total_saves),
            # 100 = saves exactly in proportion to shelf space.
            "index": round((sv / n) / (total_saves / len(mine)) * 100) if n else 0,
        })

    by_id = {p["id"]: p for p in mine}
    top = []
    for pid, n in sorted(saves_by_product.items(), key=lambda kv: -kv[1]):
        p = by_id.get(pid)
        if not p:
            continue                      # sold out and dropped from the feed
        top.append({
            "name": p.get("name", ""), "brand": p.get("brand", ""),
            "price": p.get("price"), "image": p.get("imageUrl", ""),
            "url": p.get("affiliateUrl", ""), "saves": n,
            "category": p.get("category", ""),
        })
        if len(top) >= 12:
            break

    brands_tbl = []
    for b in exclusive:
        i, l, s = eng.get(b, [0, 0, 0])
        if i < 8:
            continue                      # too thin to quote a rate off
        brands_tbl.append({
            "brand": b, "imps": i, "likes": l, "saves": s,
            "approval": pct(l + s, i),
            "pieces": sum(1 for p in mine if p["brand"] == b),
        })
    brands_tbl.sort(key=lambda r: -r["approval"])

    prices = sorted(p["price"] for p in mine if isinstance(p.get("price"), (int, float)))

    return {
        "partner": partner_id,
        "name": meta.get("name", partner_id.title()),
        "store": meta.get("store", {}),
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%B %-d, %Y") if os.name != "nt"
                     else dt.datetime.now(dt.timezone.utc).strftime("%B %d, %Y").replace(" 0", " "),
        "window_days": WINDOW_DAYS,
        "pieces": len(mine),
        "labels": len(my_brands),
        "exclusive_labels": len(exclusive),
        "price_median": prices[len(prices) // 2] if prices else 0,
        "price_lo": prices[0] if prices else 0,
        "price_hi": prices[-1] if prices else 0,
        "headline": {
            "impressions": imps,
            "likes": likes,
            "saves": saves,
            "clicks": clicks,
            "approval": pct(likes + saves, imps),
            "approval_lo": round(lo * 100, 1),
            "approval_hi": round(hi * 100, 1),
            "save_rate": pct(saves, imps),
            "save_intent": pct(saves, likes + saves),
            "app_approval": pct(a_likes + a_saves, a_imps),
            "app_save_rate": pct(a_saves, a_imps),
            "app_save_intent": pct(a_saves, a_likes + a_saves),
            "app_impressions": a_imps,
        },
        "categories": cats,
        "top": top,
        "brands": brands_tbl,
    }


# ─── PostHog queries ──────────────────────────────────────────────────────────

def pull(partner_id):
    """Live pull; returns None if there's no key so the caller can fall back."""
    if not POSTHOG_KEY:
        return None

    eng_rows = hogql(f"""
        SELECT kv.1 AS brand,
               toInt(sum(toFloatOrZero(JSONExtractRaw(kv.2,'impressions')))) AS imps,
               toInt(sum(toFloatOrZero(JSONExtractRaw(kv.2,'likes'))))       AS likes,
               toInt(sum(toFloatOrZero(JSONExtractRaw(kv.2,'saves'))))       AS saves
        FROM events
        ARRAY JOIN JSONExtractKeysAndValuesRaw(assumeNotNull(toString(properties.brands))) AS kv
        WHERE event = 'brand_engagement'
          AND timestamp >= now() - INTERVAL {WINDOW_DAYS} DAY
        GROUP BY brand
    """)
    prod_rows = hogql(f"""
        SELECT JSONExtractString(properties,'productId') AS pid, count() AS saves
        FROM events
        WHERE event = 'product_saved'
          AND JSONExtractString(properties,'retailer') = '{partner_id}'
          AND timestamp >= now() - INTERVAL {WINDOW_DAYS} DAY
        GROUP BY pid
    """)
    cat_rows = hogql(f"""
        SELECT JSONExtractString(properties,'category') AS c, count() AS saves
        FROM events
        WHERE event = 'product_saved'
          AND JSONExtractString(properties,'retailer') = '{partner_id}'
          AND timestamp >= now() - INTERVAL {WINDOW_DAYS} DAY
        GROUP BY c
    """)
    click_rows = hogql(f"""
        SELECT count() FROM events
        WHERE event = 'shop_click'
          AND JSONExtractString(properties,'retailer') = '{partner_id}'
          AND timestamp >= now() - INTERVAL {WINDOW_DAYS} DAY
    """)
    return {
        "engagement": {r[0]: [r[1], r[2], r[3]] for r in eng_rows},
        "saves_by_product": {r[0]: r[1] for r in prod_rows},
        "saves_by_category": {r[0]: r[1] for r in cat_rows},
        "clicks": click_rows[0][0] if click_rows else 0,
        "pulled_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


# ─── page ─────────────────────────────────────────────────────────────────────

E = lambda s: html.escape(str(s), quote=True)


def render_shell(d, token):
    """The page. Deliberately contains no numbers — see PRIVACY MODEL above."""
    name = E(d["name"])
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>{name} on Loupe — engagement</title>
<link rel="icon" type="image/png" href="/icon.png"/>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Beth+Ellen&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&display=swap" rel="stylesheet">
<style>
:root{{--pink:#F3CBF0;--pink-soft:#FCEFF8;--ink:#141414;--muted:#5A565A;--line:#E7E2E7;--coral:#FE6F6F;--white:#FFF;--paper:#FAF8F6;--good:#1F7A4D;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);line-height:1.55;-webkit-font-smoothing:antialiased;}}
a{{color:inherit;}}
.wrap{{max-width:940px;margin:0 auto;padding:0 22px;}}
.serif{{font-family:"Fraunces",Georgia,serif;font-weight:500;letter-spacing:-.5px;}}
.script{{font-family:"Beth Ellen",cursive;font-weight:400;}}
.eyebrow{{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--coral);font-weight:700;}}
.muted{{color:var(--muted);}}
header{{border-bottom:1px solid var(--line);background:var(--white);}}
.nav{{display:flex;align-items:center;justify-content:space-between;height:64px;}}
.logo{{font-size:22px;}}
.hero{{padding:44px 0 30px;}}
h1{{font-size:clamp(28px,5vw,42px);line-height:1.12;margin:8px 0 10px;}}
h2{{font-size:22px;margin:0 0 6px;}}
section{{padding:30px 0;border-top:1px solid var(--line);}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:14px;margin-top:18px;}}
.card{{background:var(--white);border:1px solid var(--line);border-radius:16px;padding:20px;}}
.card.lead{{border-color:var(--pink);background:var(--pink-soft);}}
.big{{font-size:40px;line-height:1;letter-spacing:-1.5px;}}
.vs{{font-size:13px;margin-top:9px;}}
.bar{{height:7px;border-radius:99px;background:#EDE9ED;overflow:hidden;margin-top:11px;}}
.bar i{{display:block;height:100%;background:var(--pink);}}
.bar i.alt{{background:var(--ink);}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px;}}
th,td{{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line);}}
th:first-child,td:first-child{{text-align:left;}}
th{{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted);font-weight:700;}}
.idx{{display:inline-block;min-width:52px;padding:2px 9px;border-radius:99px;font-weight:700;font-size:13px;background:#EFEFEF;}}
.idx.up{{background:var(--pink);}}
.idx.down{{background:#F1F1F1;color:var(--muted);}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:16px;margin-top:18px;}}
.p img{{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:12px;background:#F1EFED;display:block;}}
.p b{{display:block;font-size:13px;margin-top:8px;}}
.p span{{display:block;font-size:12.5px;color:var(--muted);}}
.tag{{display:inline-block;margin-top:5px;font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;background:var(--pink);border-radius:99px;padding:2px 9px;}}
.note{{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:18px 20px;font-size:13.5px;color:var(--muted);}}
.note b{{color:var(--ink);}}
footer{{padding:30px 0 60px;font-size:13px;color:var(--muted);border-top:1px solid var(--line);}}
#gate{{max-width:520px;margin:16vh auto;text-align:center;padding:0 22px;}}
#gate p{{color:var(--muted);margin-top:10px;}}
.hide{{display:none;}}
@media(max-width:640px){{.big{{font-size:32px;}} th,td{{padding:8px 5px;font-size:13px;}}}}
</style></head><body>

<div id="gate">
  <div class="logo script">Loupe</div>
  <h2 class="serif" style="margin-top:16px">This report is private</h2>
  <p>Open it with the full link from your email. If the link stopped working, reply to that email and we'll send a fresh one.</p>
</div>

<div id="report" class="hide">
<header><div class="wrap nav">
  <a href="https://useloupe.shop" class="logo script">Loupe</a>
  <span class="muted" style="font-size:13px">Partner report &middot; <span id="gen"></span></span>
</div></header>

<div class="wrap">
  <div class="hero">
    <div class="eyebrow">Private partner report</div>
    <h1 class="serif"><span id="pname"></span> on Loupe</h1>
    <p class="muted" id="sub"></p>
  </div>
</div>

<div class="wrap"><section style="border-top:none;padding-top:0">
  <h2 class="serif">How your pieces perform</h2>
  <p class="muted">Every number is a rate, next to the same rate for the whole app over the same window. Rates are what a young feed can honestly be judged on; the raw counts are further down.</p>
  <div class="cards" id="rates"></div>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">What to send us more of</h2>
  <p class="muted">Share of your shelf space in the app against share of the saves it earned. <b>100 means a category saves exactly in proportion to how much of your feed it is.</b></p>
  <table id="cats"><thead><tr><th>Category</th><th>Pieces</th><th>% of feed</th><th>Saves</th><th>% of saves</th><th>Index</th></tr></thead><tbody></tbody></table>
  <p class="muted" style="margin-top:12px;font-size:13.5px" id="catread"></p>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">Your most saved pieces</h2>
  <p class="muted">A save is deliberate: the piece goes into her Dresser and she gets told when it drops in price or comes back in stock.</p>
  <div class="grid" id="top"></div>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">By label</h2>
  <p class="muted">Labels we carry only through you, so these are your numbers and nobody else's. Labels under 8 impressions are held back rather than quoted off too little.</p>
  <table id="brands"><thead><tr><th>Label</th><th>Pieces</th><th>Shown</th><th>Liked</th><th>Saved</th><th>Approval</th></tr></thead><tbody></tbody></table>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">The raw counts</h2>
  <div class="cards" id="volume"></div>
  <p class="muted" style="margin-top:16px;font-size:13.5px">These are small, and we would rather show you them than round them into something that sounds bigger. Loupe is early. What the rates above tell you is how your pieces do <em>per person who sees them</em>, and that number is already meaningful.</p>
</section></div>

<div class="wrap"><section>
  <h2 class="serif">How this is measured</h2>
  <div class="note" id="method"></div>
</section></div>

<div class="wrap"><footer>
  <b class="serif">Loupe</b> &middot; <a href="https://useloupe.shop">useloupe.shop</a><br>
  This page is private and refreshes on its own. Questions about any number here: just reply to the email it came in.
</footer></div>
</div>

<script>
(function(){{
  var k = new URLSearchParams(location.search).get('k') || '';
  if (!/^[A-Za-z0-9_-]{{10,64}}$/.test(k)) return;         // no key, no fetch
  fetch('/partners/d/' + k + '.json', {{cache:'no-store'}})
    .then(function(r){{ if(!r.ok) throw 0; return r.json(); }})
    .then(render)
    .catch(function(){{}});                                 // bad key -> gate stays

  function esc(s){{ return String(s==null?'':s).replace(/[&<>"]/g,function(c){{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]; }}); }}
  function n(x){{ return Number(x||0).toLocaleString(); }}

  function card(o){{
    var d = o.delta;
    return '<div class="card' + (o.lead?' lead':'') + '">'
      + '<div class="eyebrow">' + esc(o.label) + '</div>'
      + '<div class="big serif">' + esc(o.value) + '</div>'
      + '<div class="vs muted">' + o.vs + '</div>'
      + (o.mine!=null ? '<div class="bar"><i style="width:' + Math.min(100, o.mine/o.scale*100) + '%"></i></div>'
                      + '<div class="bar"><i class="alt" style="width:' + Math.min(100, o.theirs/o.scale*100) + '%"></i></div>' : '')
      + '</div>';
  }}

  function render(d){{
    var h = d.headline;
    document.getElementById('gate').className = 'hide';
    document.getElementById('report').className = '';
    document.title = d.name + ' on Loupe — engagement';
    document.getElementById('pname').textContent = d.name;
    document.getElementById('gen').textContent = d.generated;
    document.getElementById('sub').textContent =
      d.pieces + ' pieces from ' + d.labels + ' labels, live in the app. '
      + 'Median price $' + d.price_median + '. Trailing ' + d.window_days + ' days.';

    var scale = Math.max(h.approval, h.app_approval, h.save_intent, h.app_save_intent);
    document.getElementById('rates').innerHTML = [
      card({{ lead:true, label:'Save intent', value:h.save_intent + '%',
        vs:'of everyone who engaged with your pieces went on to <b>save</b> one, against <b>'
           + h.app_save_intent + '%</b> app-wide. Your pieces get browsed less and committed to more.',
        mine:h.save_intent, theirs:h.app_save_intent, scale:scale }}),
      card({{ label:'Save rate', value:h.save_rate + '%',
        vs:'of the times a piece of yours was shown, it was saved. App-wide: <b>' + h.app_save_rate + '%</b>.',
        mine:h.save_rate, theirs:h.app_save_rate, scale:scale }}),
      card({{ label:'Approval rate', value:h.approval + '%',
        vs:'liked or saved rather than passed (95% confidence: ' + h.approval_lo + '–' + h.approval_hi
           + '%). App-wide: <b>' + h.app_approval + '%</b> — so your pieces are passed on more often than average, and the category table below shows where that comes from.',
        mine:h.approval, theirs:h.app_approval, scale:scale }})
    ].join('');

    var tb = document.querySelector('#cats tbody'), best = null;
    tb.innerHTML = d.categories.map(function(c){{
      if (c.pieces >= 15 && (!best || c.index > best.index)) best = c;
      var cls = c.index >= 130 ? 'idx up' : (c.index < 70 ? 'idx down' : 'idx');
      return '<tr><td style="text-transform:capitalize">' + esc(c.category) + '</td><td>' + c.pieces
        + '</td><td>' + c.feed_pct + '%</td><td>' + c.saves + '</td><td>' + c.saves_pct
        + '%</td><td><span class="' + cls + '">' + c.index + '</span></td></tr>';
    }}).join('');
    var top = d.categories.slice().sort(function(a,b){{ return b.index - a.index; }})[0];
    if (top) document.getElementById('catread').innerHTML =
      '<b>' + esc(top.category) + '</b> are ' + top.feed_pct + '% of what we show from you and '
      + top.saves_pct + '% of what gets saved — they earn saves at <b>' + (top.index/100).toFixed(1)
      + 'x</b> the rate of an average piece in your feed. That is the clearest thing this report has to say: more of those.';

    document.getElementById('top').innerHTML = d.top.map(function(p){{
      return '<a class="p" href="' + esc(p.url) + '" target="_blank" rel="noopener">'
        + '<img loading="lazy" src="' + esc(p.image) + '" alt="' + esc(p.name) + '">'
        + '<b>' + esc(p.brand) + '</b><span>' + esc(p.name) + '</span>'
        + '<span>$' + n(p.price) + '</span>'
        + '<span class="tag">' + p.saves + ' save' + (p.saves===1?'':'s') + '</span></a>';
    }}).join('');

    document.querySelector('#brands tbody').innerHTML = d.brands.map(function(b){{
      return '<tr><td>' + esc(b.brand) + '</td><td>' + b.pieces + '</td><td>' + n(b.imps)
        + '</td><td>' + b.likes + '</td><td>' + b.saves + '</td><td><b>' + b.approval + '%</b></td></tr>';
    }}).join('');

    document.getElementById('volume').innerHTML = [
      card({{label:'Times shown', value:n(h.impressions), vs:'your pieces at the top of someone\\'s deck'}}),
      card({{label:'Saved', value:n(h.saves), vs:'into a Dresser, with price-drop alerts attached'}}),
      card({{label:'Liked', value:n(h.likes), vs:'swiped right, teaching the feed'}}),
      card({{label:'Sent to your site', value:n(h.clicks), vs:'tapped through to shop, tagged so you can see them in your own analytics'}})
    ].join('');

    document.getElementById('method').innerHTML =
      '<b>Window.</b> Trailing ' + d.window_days + ' days, refreshed weekly. <br>'
      + '<b>Impression.</b> A piece reaching the top of the deck, where it is the only thing on screen. Every one was actually looked at.<br>'
      + '<b>Approval.</b> (likes + saves) / times shown. <b>Save intent.</b> saves / (likes + saves).<br>'
      + '<b>Whose numbers.</b> The ' + d.exclusive_labels + ' labels we carry only through ' + esc(d.name)
      + ', so nothing from another stockist is mixed in.<br>'
      + '<b>Comparison.</b> Every app-wide figure is the same metric over the same window across '
      + n(h.app_impressions) + ' impressions.<br>'
      + '<b>What we do not have.</b> Whether a click became a sale. Your own analytics can tell you that — '
      + 'every link we send you carries a UTM tag.';
  }}
}})();
</script>
</body></html>"""


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partner", default="gemini")
    ap.add_argument("--rotate-key", action="store_true",
                    help="mint a new token (invalidates the old link)")
    args = ap.parse_args()
    pid = args.partner.lower()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = DATA_DIR / f"{pid}.json"

    ph = pull(pid)
    if ph:
        snap_path.write_text(json.dumps(ph, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"pulled live from PostHog -> {snap_path.name}")
    else:
        if not snap_path.exists():
            sys.exit(f"No POSTHOG_API_KEY and no snapshot at {snap_path}.")
        ph = json.loads(snap_path.read_text(encoding="utf-8"))
        print(f"no POSTHOG_API_KEY — using snapshot from {ph.get('pulled_at','?')}")

    print("fetching live catalog…")
    d = compute(pid, fetch_catalog(), ph)

    # The token IS the password, so it is kept out of git.
    keys_path = DATA_DIR / "keys.json"
    keys = json.loads(keys_path.read_text(encoding="utf-8")) if keys_path.exists() else {}
    if args.rotate_key or pid not in keys:
        old = keys.get(pid)
        keys[pid] = secrets.token_urlsafe(16)
        keys_path.write_text(json.dumps(keys, indent=1), encoding="utf-8")
        if old:
            (ROOT / "partners" / "d" / f"{old}.json").unlink(missing_ok=True)
            print(f"rotated key — the old link is now dead")
    token = keys[pid]

    out_dir = ROOT / "partners" / pid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_shell(d, token), encoding="utf-8")

    data_dir = ROOT / "partners" / "d"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"{token}.json").write_text(
        json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    h = d["headline"]
    print(f"\n  {d['name']}: {d['pieces']} pieces / {d['labels']} labels")
    print(f"  approval {h['approval']}% (app {h['app_approval']}%)  "
          f"save rate {h['save_rate']}% (app {h['app_save_rate']}%)  "
          f"save intent {h['save_intent']}% (app {h['app_save_intent']}%)")
    print(f"\n  https://useloupe.shop/partners/{pid}/?k={token}\n")


if __name__ == "__main__":
    main()

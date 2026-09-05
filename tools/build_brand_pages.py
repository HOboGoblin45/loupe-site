#!/usr/bin/env python3
"""build_brand_pages.py — regenerate the per-brand SEO directory at brands/.

Reads the live Loupe catalog (a local file via --catalog, or the public
jsDelivr URL) and rebuilds:

  * brands/<slug>.html          — one page per "Loupe brand" (available
                                   products, no `retailer` key)
  * brands/index.html           — the directory landing page
  * brands/<slug>.html (stubs)  — brands that used to exist but no longer
                                   qualify get replaced with a tiny
                                   noindex redirect stub (never deleted)
  * sitemap.xml                 — brand-page <url> entries only; every
                                   other entry is left untouched

The original page generator was never committed to this repo. This script
was re-created from the shipped output (brands/1xblue.html + brands/index.html
were used as the spec) so the HTML shape, classes and wording match exactly;
only the data is fresh.

Everything here is deterministic: no timestamps, no randomness, no reliance
on dict/set iteration order for anything that ends up in the output. Running
this script twice against the same catalog produces byte-identical files.

Usage:
    python tools/build_brand_pages.py [--catalog PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from urllib.parse import urlsplit

# --------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.dirname(TOOLS_DIR)
BRANDS_DIR = os.path.join(SITE_ROOT, "brands")
SITEMAP_PATH = os.path.join(SITE_ROOT, "sitemap.xml")

CATALOG_URL = "https://cdn.jsdelivr.net/gh/HOboGoblin45/loupe-feed@main/loupe-feed/catalog.json"

SITE_BASE = "https://useloupe.shop"
APP_STORE_URL = "https://apps.apple.com/app/id6781137336"
OG_IMAGE = f"{SITE_BASE}/og.jpg"

FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Beth+Ellen&family=Fraunces:'
    'opsz,wght@9..144,400;9..144,500;9..144,600&display=swap" rel="stylesheet">'
)

CATEGORIES = ["tops", "bottoms", "dresses", "outerwear", "shoes", "accessories"]
CATEGORY_INDEX = {c: i for i, c in enumerate(CATEGORIES)}
CATEGORY_LABELS = {
    "tops": "Tops",
    "bottoms": "Bottoms",
    "dresses": "Dresses",
    "outerwear": "Outerwear",
    "shoes": "Shoes",
    "accessories": "Accessories",
}
CATEGORY_COLORS = {
    "tops": "#F3CBF0",
    "bottoms": "#8A8AAA",
    "dresses": "#FE6F6F",
    "outerwear": "#D9CBB8",
    "shoes": "#9BB5D6",
    "accessories": "#A7C4A0",
}
MIX_FLOOR = 0.03

FEW_PIECES_LIMIT = 6  # similar-brand count uses 6; kept separate name below
SIMILAR_COUNT = 6
CARD_LIMIT = 8

# Similarity score weights: category-mix cosine, color-mix cosine, price closeness.
SIM_W_CATEGORY = 0.5
SIM_W_COLOR = 0.3
SIM_W_PRICE = 0.2

# Words the copy must never contain (checked on every generated file).
BANNED_PATTERNS = [
    re.compile(r"\bAI\b"),
    re.compile(r"\balgorithm\w*\b", re.IGNORECASE),
    re.compile(r"\brecommend\w*\b", re.IGNORECASE),
    re.compile(r"\bpersonali[sz]ed?\b", re.IGNORECASE),
]

# The shared <style> block, copied verbatim from the live brands/1xblue.html.
BASE_STYLE = """:root{--pink:#F3CBF0;--pink-soft:#FCEFF8;--ink:#141414;--navy:#15152A;--muted:#6E6A6E;--line:#ECE7EC;--coral:#FE6F6F;--white:#FFFFFF;--paper:#FAF8F6;}
*{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);line-height:1.55;-webkit-font-smoothing:antialiased;}
a{color:inherit;text-decoration:none;}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px;}
.serif{font-family:"Fraunces",Georgia,serif;font-weight:500;letter-spacing:-.5px;}
.script{font-family:"Beth Ellen",cursive;font-weight:400;}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--coral);font-weight:700;}
.muted{color:var(--muted);}
.btn{display:inline-flex;align-items:center;gap:8px;background:var(--ink);color:var(--white);padding:13px 24px;border-radius:999px;font-size:15px;font-weight:600;transition:transform .14s ease;}
.btn:hover{transform:translateY(-2px);}
.btn-pink{background:var(--pink);color:var(--ink);}
.btn-ghost{background:transparent;color:var(--ink);border:1px solid var(--ink);}
header{position:sticky;top:0;z-index:60;background:rgba(250,248,246,.85);backdrop-filter:saturate(180%) blur(10px);border-bottom:1px solid var(--line);}
.nav{display:flex;align-items:center;justify-content:space-between;height:66px;}
.logo{font-size:23px;line-height:1.4;}
.nav-links{display:flex;gap:26px;align-items:center;font-size:14px;color:var(--muted);}
.nav .btn{padding:10px 20px;font-size:14px;}
@media(max-width:720px){.nav-links a.hide-sm{display:none;}}
.crumb{font-size:13px;color:var(--muted);padding:20px 0 0;}
.crumb a:hover{color:var(--ink);}
.bhero{padding:26px 0 40px;}
.bhero h1{font-size:clamp(34px,6vw,58px);letter-spacing:-1.6px;margin:8px 0 14px;}
.bhero .lead{font-size:clamp(16px,2.2vw,19px);color:var(--muted);max-width:60ch;margin-bottom:22px;}
.statline{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0 6px;}
.stat{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:12px 16px;min-width:120px;}
.stat .k{font-size:12px;letter-spacing:.4px;text-transform:uppercase;color:var(--muted);font-weight:700;}
.stat .v{font-size:20px;font-weight:600;letter-spacing:-.4px;margin-top:2px;}
.cta-row{display:flex;gap:12px;flex-wrap:wrap;margin-top:22px;}
section.block{padding:46px 0;}
.h2{font-size:clamp(22px,3.4vw,32px);letter-spacing:-.8px;margin-bottom:6px;}
.sub{color:var(--muted);margin-bottom:24px;}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}
@media(max-width:900px){.grid{grid-template-columns:repeat(3,1fr);}}
@media(max-width:620px){.grid{grid-template-columns:repeat(2,1fr);}}
.card{background:var(--white);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;}
.card .ph{aspect-ratio:3/4;background:var(--pink-soft);overflow:hidden;}
.card .ph img{width:100%;height:100%;object-fit:cover;display:block;}
.card .m{padding:11px 13px 14px;}
.card .nm{font-size:13.5px;line-height:1.3;max-height:2.6em;overflow:hidden;}
.card .pr{font-size:13px;color:var(--muted);margin-top:4px;font-weight:600;}
.mix{display:flex;height:12px;border-radius:999px;overflow:hidden;gap:2px;max-width:560px;margin:6px 0 14px;}
.mix span{height:12px;border-radius:2px;}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--muted);}
.legend i{display:inline-block;width:9px;height:9px;border-radius:999px;margin-right:6px;vertical-align:middle;}
.simrow{display:flex;flex-wrap:wrap;gap:9px 10px;}
.simrow a{font-size:14px;background:var(--white);border:1px solid var(--line);padding:8px 15px;border-radius:999px;transition:transform .12s;}
.simrow a:hover{transform:translateY(-2px);border-color:var(--ink);}
.disclosure{padding:26px 0;border-top:1px solid var(--line);}
.disclosure p{text-align:center;font-size:12.5px;color:var(--muted);max-width:74ch;margin:0 auto;}
footer{padding:40px 0 60px;background:var(--paper);border-top:1px solid var(--line);}
.foot{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;}
.foot .logo{font-size:28px;}
.foot-links{display:flex;gap:20px;font-size:14px;color:var(--muted);flex-wrap:wrap;}
.foot-links a:hover{color:var(--ink);}
.copyright{font-size:13px;color:var(--muted);margin-top:18px;}"""

# Extra rules appended after BASE_STYLE only on brands/index.html.
INDEX_EXTRA_STYLE = """
.dhero{padding:34px 0 22px;}
.dhero h1{font-size:clamp(32px,5.4vw,52px);letter-spacing:-1.4px;margin:8px 0 12px;}
.dhero p{color:var(--muted);max-width:60ch;font-size:17px;}
.dgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:8px 0 40px;}
@media(max-width:820px){.dgrid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:560px){.dgrid{grid-template-columns:1fr;}}
.dcard{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:15px 17px;display:flex;flex-direction:column;gap:3px;transition:transform .12s,border-color .12s;}
.dcard:hover{transform:translateY(-2px);border-color:var(--ink);}
.dn{font-size:16px;font-weight:600;letter-spacing:-.3px;}
.dm{font-size:13px;color:var(--muted);}"""

HEADER_HTML = (
    '<header><div class="wrap nav"><a href="/" class="logo script">Loupe</a>'
    '<nav class="nav-links"><a href="/brands/" class="hide-sm">All brands</a>'
    '<a href="/#how" class="hide-sm">How it works</a>'
    f'<a href="{APP_STORE_URL}" target="_blank" rel="noopener" class="btn btn-pink">Get the app</a>'
    "</nav></div></header>"
)

FOOTER_HTML = (
    '<section class="disclosure"><div class="wrap"><p><strong>Affiliate disclosure:</strong> '
    "Loupe may earn a commission when you buy through links in the app and on this site, at no "
    "additional cost to you. We only feature brands we genuinely love, and commissions never "
    "influence what we show you. Prices and availability are pulled from each brand and may change."
    "</p></div></section>"
    '<footer><div class="wrap"><div class="foot"><a href="/" class="logo script">Loupe</a>'
    '<nav class="foot-links"><a href="/brands/">All brands</a><a href="/#how">How it works</a>'
    f'<a href="{APP_STORE_URL}" target="_blank" rel="noopener">iPhone app</a>'
    '<a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a>'
    '<a href="mailto:crescicharles@gmail.com">Contact</a></nav></div>'
    '<p class="copyright">© 2026 Loupe. Independent fashion discovery.</p></div></footer>'
)

STUB_HTML = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
    '<meta name="robots" content="noindex">'
    f'<link rel="canonical" href="{SITE_BASE}/brands/">'
    '<meta http-equiv="refresh" content="0; url=/brands/">'
    "<title>Redirecting…</title></head><body>"
    "<script>location.replace('/brands/')</script>"
    '<p>This brand page has moved. <a href="/brands/">Browse all brands on Loupe</a>.</p>'
    "</body></html>"
)


# --------------------------------------------------------------------------
# Slug
# --------------------------------------------------------------------------

def slugify(brand: str) -> str:
    s = brand.lower().replace("’", "").replace("'", "").replace("+", " plus ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def self_test_slugify() -> None:
    cases = {
        "SIEDRÉS": "siedr-s",
        "Pärlemor": "p-rlemor",
        "With Jéan": "with-j-an",
        "DémodéMODÉ": "d-mod-mod",
        "C'est Nous": "cest-nous",
        "Susmie's": "susmies",
        "Bec + Bridge": "bec-plus-bridge",
        "1XBLUE": "1xblue",
    }
    for brand, expected in cases.items():
        got = slugify(brand)
        assert got == expected, f"slug self-test failed for {brand!r}: got {got!r}, expected {expected!r}"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------
# Catalog loading / filtering
# --------------------------------------------------------------------------

def load_catalog(path: str | None) -> dict:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "loupe-build-brand-pages/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_brand_groups(catalog: dict) -> dict[str, list[dict]]:
    """Only products that are available AND not part of a retailer's shelf."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in catalog["products"]:
        if not p.get("available"):
            continue
        if "retailer" in p:
            continue
        groups[p["brand"]].append(p)
    return dict(groups)


def color_vocabulary(groups: dict[str, list[dict]]) -> list[str]:
    colors = set()
    for items in groups.values():
        for p in items:
            colors.update(p.get("colorTags", []))
    return sorted(colors)


# --------------------------------------------------------------------------
# Per-brand stats
# --------------------------------------------------------------------------

def price_band(median: int) -> str:
    if median < 100:
        return "accessible"
    if median < 300:
        return "mid-range"
    if median < 700:
        return "elevated"
    return "luxury"


def brand_homepage(items: list[dict]) -> str:
    domains: Counter = Counter()
    schemes: Counter = Counter()
    for p in items:
        parts = urlsplit(p["affiliateUrl"])
        if parts.netloc:
            domains[parts.netloc] += 1
            schemes[parts.scheme or "https"] += 1
    domain = domains.most_common(1)[0][0]
    scheme = schemes.most_common(1)[0][0]
    return f"{scheme}://{domain}/"


def rewrite_affiliate_url(url: str) -> str:
    if "utm_campaign=app" in url:
        return url.replace("utm_campaign=app", "utm_campaign=brand-directory")
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_campaign=brand-directory"


def pick_pieces(items: list[dict], limit: int = CARD_LIMIT) -> list[dict]:
    """Deterministically pick up to `limit` products, round-robin across
    categories (canonical order) so the picks cover different categories
    where possible. Within a category, most-recently-published first,
    ties broken by product id (stable, since both are plain strings).

    Products whose own (brand-authored) name happens to trip the banned-word
    self-check (e.g. a novelty T-shirt literally titled "'AI Betrayed Me'")
    are skipped so Loupe's own directory copy never surfaces them, unless
    doing so would leave a brand with nothing to show at all."""
    clean_items = [p for p in items if not any(pat.search(p["name"]) for pat in BANNED_PATTERNS)]
    if not clean_items:
        clean_items = items
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in clean_items:
        by_cat[p["category"]].append(p)
    for cat in by_cat:
        ordered = sorted(by_cat[cat], key=lambda p: p["id"])
        ordered = sorted(ordered, key=lambda p: p["publishedAt"], reverse=True)
        by_cat[cat] = ordered

    picks: list[dict] = []
    idx = {c: 0 for c in CATEGORIES}
    while len(picks) < limit:
        progressed = False
        for cat in CATEGORIES:
            bucket = by_cat.get(cat, [])
            if idx[cat] < len(bucket):
                picks.append(bucket[idx[cat]])
                idx[cat] += 1
                progressed = True
                if len(picks) >= limit:
                    break
        if not progressed:
            break
    return picks


def compute_stats(brand: str, items: list[dict], color_list: list[str]) -> dict:
    n = len(items)
    prices = sorted(p["price"] for p in items)
    lo, hi = prices[0], prices[-1]
    median = int(round(statistics.median(prices)))

    cat_counts = Counter(p["category"] for p in items)
    cat_shares = {c: cat_counts.get(c, 0) / n for c in CATEGORIES}
    nonzero_cats = [c for c in CATEGORIES if cat_counts.get(c, 0) > 0]
    ordered_cats = sorted(nonzero_cats, key=lambda c: (-cat_shares[c], CATEGORY_INDEX[c]))

    color_counts: Counter = Counter()
    for p in items:
        for c in p.get("colorTags", []):
            color_counts[c] += 1
    total_tags = sum(color_counts.values())
    color_shares = {
        c: (color_counts.get(c, 0) / total_tags if total_tags else 0.0) for c in color_list
    }
    ordered_colors = sorted(color_counts.keys(), key=lambda c: (-color_counts[c], c))

    return {
        "brand": brand,
        "count": n,
        "lo": lo,
        "hi": hi,
        "median": median,
        "band": price_band(median),
        "cat_counts": cat_counts,
        "cat_shares": cat_shares,
        "ordered_cats": ordered_cats,
        "top_cats": ordered_cats[:3],
        "color_counts": color_counts,
        "color_shares": color_shares,
        "top_colors": ordered_colors[:3],
        "homepage": brand_homepage(items),
        "pieces": pick_pieces(items),
        "items": items,
    }


def join_and(values: list[str]) -> str:
    values = list(values)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])} and {values[-1]}"


def build_lead(stats: dict) -> str:
    n = stats["count"]
    piece_word = "piece" if n == 1 else "pieces"
    cats_txt = join_and(stats["top_cats"])
    colors_txt = ", ".join(stats["top_colors"])
    return (
        f"{stats['brand']} is an independent label on Loupe, best known on the app for {cats_txt}. "
        f"With {n} {piece_word} in the current feed and a {stats['band']} price range "
        f"(${stats['lo']}–${stats['hi']}, typically around ${stats['median']}), "
        f"it's the kind of brand you won't find on every other shopping app. "
        f"Their palette leans {colors_txt}."
    )


def build_summary(stats: dict, total_brands: int) -> str:
    n = stats["count"]
    piece_word = "piece" if n == 1 else "pieces"
    other_count = total_brands - 1
    return (
        f"{stats['brand']}: {n} {piece_word}, ${stats['lo']}–${stats['hi']}. "
        f"Discover {stats['brand']} and {other_count}+ other independent brands by swiping on Loupe. "
        f"Save pieces, see your Style DNA, shop direct."
    )


# --------------------------------------------------------------------------
# Similar brands
# --------------------------------------------------------------------------

def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def price_closeness(median_a: int, median_b: int) -> float:
    la = math.log(max(median_a, 1))
    lb = math.log(max(median_b, 1))
    return math.exp(-abs(la - lb))


def compute_similar(slug: str, stats_by_slug: dict[str, dict], all_slugs: list[str]) -> list[str]:
    target = stats_by_slug[slug]
    scored = []
    for other_slug in all_slugs:
        if other_slug == slug:
            continue
        other = stats_by_slug[other_slug]
        cat_sim = cosine(target["cat_vector"], other["cat_vector"])
        color_sim = cosine(target["color_vector"], other["color_vector"])
        price_sim = price_closeness(target["median"], other["median"])
        score = SIM_W_CATEGORY * cat_sim + SIM_W_COLOR * color_sim + SIM_W_PRICE * price_sim
        scored.append((score, other_slug))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s for _, s in scored[:SIMILAR_COUNT]]


# --------------------------------------------------------------------------
# HTML rendering — per brand page
# --------------------------------------------------------------------------

def render_card(p: dict) -> str:
    url = esc(rewrite_affiliate_url(p["affiliateUrl"]))
    img = esc(p["imageUrl"])
    name = esc(p["name"])
    return (
        f'<a href="{url}" target="_blank" rel="noopener nofollow sponsored">'
        f'<div class="card"><div class="ph"><img src="{img}" alt="{name}" loading="lazy"></div>'
        f'<div class="m"><div class="nm">{name}</div><div class="pr">${p["price"]}</div></div>'
        f"</div></a>"
    )


def render_mix(stats: dict) -> tuple[str, str]:
    spans = []
    legend = []
    for cat in stats["ordered_cats"]:
        share = stats["cat_shares"][cat]
        flex = max(share, MIX_FLOOR)
        color = CATEGORY_COLORS[cat]
        spans.append(f'<span style="flex-grow:{flex};background:{color}"></span>')
        pct = round(share * 100)
        legend.append(f'<span><i style="background:{color}"></i>{CATEGORY_LABELS[cat]} {pct}%</span>')
    return "".join(spans), "".join(legend)


def render_brand_page(
    slug: str,
    stats: dict,
    total_brands: int,
    stats_by_slug: dict[str, dict],
) -> str:
    brand = stats["brand"]
    brand_esc = esc(brand)
    other_count = total_brands - 1

    lead_raw = build_lead(stats)
    summary_raw = build_summary(stats, total_brands)
    lead_esc = esc(lead_raw)
    summary_esc = esc(summary_raw)

    brand_url = f"{SITE_BASE}/brands/{slug}.html"
    homepage_url = stats["homepage"] + "?utm_source=loupe&utm_medium=referral&utm_campaign=brand-directory"

    brand_ld = {
        "@context": "https://schema.org",
        "@type": "Brand",
        "name": brand,
        "url": brand_url,
        "description": lead_raw,
        "makesOffer": {
            "@type": "AggregateOffer",
            "offerCount": stats["count"],
            "lowPrice": stats["lo"],
            "highPrice": stats["hi"],
            "priceCurrency": "USD",
        },
    }
    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Loupe", "item": SITE_BASE},
            {"@type": "ListItem", "position": 2, "name": "Brands", "item": f"{SITE_BASE}/brands/"},
            {"@type": "ListItem", "position": 3, "name": brand, "item": brand_url},
        ],
    }

    cards_html = "".join(render_card(p) for p in stats["pieces"])
    mix_spans, legend_spans = render_mix(stats)
    similar_slugs = compute_similar(slug, stats_by_slug, sorted(stats_by_slug.keys()))
    similar_html = "".join(
        f'<a href="/brands/{s}.html">{esc(stats_by_slug[s]["brand"])}</a>' for s in similar_slugs
    )

    lines = [
        '<!DOCTYPE html><html lang="en"><head>',
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="apple-itunes-app" content="app-id=6781137336">',
        f"<title>{brand_esc} — Shop {brand_esc} on Loupe | Independent Fashion</title>",
        f'<meta name="description" content="{summary_esc}">',
        '<link rel="icon" type="image/png" href="/icon.png" />',
        '<link rel="apple-touch-icon" href="/icon.png" />',
        f'<link rel="canonical" href="{brand_url}">',
        f'<meta property="og:title" content="{brand_esc} on Loupe">',
        f'<meta property="og:description" content="{summary_esc}">',
        f'<meta property="og:type" content="website"><meta property="og:url" content="{brand_url}">',
        f'<meta property="og:image" content="{OG_IMAGE}" />',
        '<meta property="og:image:width" content="1200" />',
        '<meta property="og:image:height" content="630" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:image" content="{OG_IMAGE}" />',
        FONTS_LINK,
        f'<script type="application/ld+json">{json.dumps(brand_ld)}</script>',
        f'<script type="application/ld+json">{json.dumps(breadcrumb_ld)}</script>',
        "<style>",
        BASE_STYLE,
        "</style></head><body>",
        HEADER_HTML,
        f'<div class="wrap crumb"><a href="/">Loupe</a> / <a href="/brands/">Brands</a> / {brand_esc}</div>',
        '<section class="bhero"><div class="wrap">',
        '<span class="eyebrow">Independent label</span>',
        f'<h1 class="serif">{brand_esc}</h1>',
        f'<p class="lead">{lead_esc}</p>',
        '<div class="statline"><div class="stat"><div class="k">Pieces in feed</div>'
        f'<div class="v">{stats["count"]}</div></div><div class="stat"><div class="k">Price range</div>'
        f'<div class="v">${stats["lo"]}–${stats["hi"]}</div></div><div class="stat">'
        f'<div class="k">Typical price</div><div class="v">${stats["median"]}</div></div></div>',
        f'<div class="cta-row"><a href="{APP_STORE_URL}" target="_blank" rel="noopener" class="btn">'
        f'Discover {brand_esc} on Loupe</a><a href="{esc(homepage_url)}" target="_blank" '
        f'rel="noopener nofollow sponsored" class="btn btn-ghost">Shop {brand_esc} →</a></div>',
        "</div></section>",
        "<section class='block' style='background:var(--white);border-top:1px solid var(--line);'>"
        "<div class='wrap'><h2 class='h2 serif'>A few pieces</h2>"
        f"<p class='sub'>Live from {brand_esc}’s current feed. Tap to shop direct.</p>"
        f"<div class='grid'>{cards_html}</div></div></section>",
        f"<section class='block'><div class='wrap'><h2 class='h2 serif'>What {brand_esc} makes</h2>"
        f"<div class='mix'>{mix_spans}</div><div class='legend'>{legend_spans}</div></div></section>",
        "<section class='block' style='background:var(--pink-soft);'><div class='wrap'>"
        f"<h2 class='h2 serif'>Brands like {brand_esc}</h2>"
        "<p class='sub'>Matched by category, palette and price from the live Loupe catalog.</p>"
        f"<div class='simrow'>{similar_html}</div></div></section>",
        '<section class="block" style="text-align:center;"><div class="wrap">',
        '<span class="eyebrow">Free on iPhone</span>',
        f'<h2 class="h2 serif" style="margin:10px auto 8px;">Swipe {brand_esc} into your Dresser.</h2>',
        f'<p class="sub" style="max-width:46ch;margin:0 auto 20px;">Discover {brand_esc} alongside '
        f"{other_count}+ independent brands. Save what you love, see your Style DNA, shop direct.</p>",
        f'<a href="{APP_STORE_URL}" target="_blank" rel="noopener" class="btn">Get Loupe on the App Store</a>',
        "</div></section>",
        FOOTER_HTML,
        "</body></html>",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# HTML rendering — brands/index.html
# --------------------------------------------------------------------------

def render_index_page(order: list[str], stats_by_slug: dict[str, dict], total_brands: int, total_pieces: int) -> str:
    brands_plus = f"{(total_brands // 10) * 10}+"
    pieces_plus = f"{format((total_pieces // 1000) * 1000, ',')}+"

    meta_desc_raw = (
        f"Browse {brands_plus} independent and niche fashion brands on Loupe — {pieces_plus} pieces "
        "from labels like Paloma Wool, Mirror Palais, Lisa Says Gah and With Jéan. The indie brands "
        "you won’t find on every other app."
    )
    meta_desc_esc = esc(meta_desc_raw)
    title_raw = f"All {brands_plus} Independent Brands on Loupe | Indie Fashion Directory"
    title_esc = esc(title_raw)

    collection_ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Loupe Brand Directory",
        "url": f"{SITE_BASE}/brands/",
        "description": meta_desc_raw,
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": total_brands,
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": stats_by_slug[slug]["brand"],
                    "url": f"{SITE_BASE}/brands/{slug}.html",
                }
                for i, slug in enumerate(order)
            ],
        },
    }

    dgrid_cards = []
    for slug in order:
        stats = stats_by_slug[slug]
        piece_word = "piece" if stats["count"] == 1 else "pieces"
        dgrid_cards.append(
            f'<a href="/brands/{slug}.html" class="dcard"><span class="dn">{esc(stats["brand"])}</span>'
            f'<span class="dm">{stats["count"]} {piece_word} · from ${stats["lo"]}</span></a>'
        )
    dgrid_html = "".join(dgrid_cards)

    lines = [
        '<!DOCTYPE html><html lang="en"><head>',
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="apple-itunes-app" content="app-id=6781137336">',
        f"<title>{title_esc}</title>",
        f'<meta name="description" content="{meta_desc_esc}">',
        '<link rel="icon" type="image/png" href="/icon.png" />',
        '<link rel="apple-touch-icon" href="/icon.png" />',
        f'<link rel="canonical" href="{SITE_BASE}/brands/">',
        f'<meta property="og:title" content="{title_esc}">'
        f'<meta property="og:description" content="{meta_desc_esc}">',
        f'<meta property="og:type" content="website"><meta property="og:url" content="{SITE_BASE}/brands/">',
        f'<meta property="og:image" content="{OG_IMAGE}" />',
        '<meta property="og:image:width" content="1200" />',
        '<meta property="og:image:height" content="630" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:image" content="{OG_IMAGE}" />',
        FONTS_LINK,
        f'<script type="application/ld+json">{json.dumps(collection_ld)}</script>',
        "<style>",
        BASE_STYLE + INDEX_EXTRA_STYLE,
        "</style></head><body>",
        HEADER_HTML,
        '<div class="wrap crumb"><a href="/">Loupe</a> / Brands</div>',
        '<section class="dhero"><div class="wrap">',
        '<span class="eyebrow">The full roster</span>',
        f'<h1 class="serif">All {brands_plus} independent brands on Loupe.</h1>',
        f"<p>{pieces_plus} pieces from labels you won’t find on every other app — from cult "
        "favorites like Paloma Wool, Mirror Palais and Lisa Says Gah to brands you haven’t met yet. "
        "Swipe them all, free, on iPhone.</p>",
        f'<div class="cta-row" style="margin-top:20px;"><a href="{APP_STORE_URL}" target="_blank" '
        'rel="noopener" class="btn">Get Loupe on the App Store</a></div>',
        "</div></section>",
        f'<section><div class="wrap"><div class="dgrid">{dgrid_html}</div></div></section>',
        FOOTER_HTML,
        "</body></html>",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# sitemap.xml
# --------------------------------------------------------------------------

_BRAND_PAGE_RE = re.compile(r"^https://useloupe\.shop/brands/[^/]+\.html$")


def update_sitemap_content(raw: str, brand_slug_pairs: list[tuple[str, str]]) -> str:
    """brand_slug_pairs: list of (brand_name, slug) for the CURRENT brand set."""
    first = raw.index("<url>")
    last_end = raw.rindex("</url>") + len("</url>")
    prefix = raw[:first]
    suffix = raw[last_end:]
    body = raw[first:last_end]
    entries = re.findall(r"<url>.*?</url>", body)

    kept = []
    for e in entries:
        m = re.search(r"<loc>(.*?)</loc>", e)
        loc = m.group(1) if m else ""
        if _BRAND_PAGE_RE.match(loc):
            continue  # drop; rebuilt below
        kept.append(e)

    ordered_pairs = sorted(brand_slug_pairs, key=lambda t: t[0].lower())
    new_entries = [f"<url><loc>{SITE_BASE}/brands/{slug}.html</loc></url>" for _, slug in ordered_pairs]

    return prefix + "".join(kept) + "".join(new_entries) + suffix


# --------------------------------------------------------------------------
# Banned-word check
# --------------------------------------------------------------------------

def check_banned_words(files: dict[str, str]) -> None:
    violations = []
    for path, content in files.items():
        for pattern in BANNED_PATTERNS:
            m = pattern.search(content)
            if m:
                violations.append(f"{path}: matched {pattern.pattern!r} -> {m.group(0)!r}")
    if violations:
        raise RuntimeError("Banned-word check failed:\n" + "\n".join(violations))


# --------------------------------------------------------------------------
# File writing (idempotent)
# --------------------------------------------------------------------------

def write_if_changed(path: str, content: str, dry_run: bool) -> tuple[bool, bool]:
    """Returns (is_new, is_changed). Never rewrites a byte-identical file."""
    data = content.encode("utf-8")
    existing = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            existing = f.read()
    is_new = existing is None
    is_changed = existing != data
    if is_changed and not dry_run:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    return is_new, is_changed


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Regenerate the Loupe brand directory pages.")
    parser.add_argument("--catalog", default=None, help="Path to a local catalog.json (else downloads the live URL).")
    parser.add_argument("--dry-run", action="store_true", help="Compute everything but do not write files.")
    args = parser.parse_args()

    self_test_slugify()

    catalog = load_catalog(args.catalog)
    groups = build_brand_groups(catalog)
    total_brands = len(groups)
    total_pieces = sum(len(v) for v in groups.values())
    colors = color_vocabulary(groups)

    slug_of: dict[str, str] = {brand: slugify(brand) for brand in groups}
    slugs_seen = list(slug_of.values())
    dupes = sorted({s for s in slugs_seen if slugs_seen.count(s) > 1})
    assert not dupes, f"slug collision(s) detected: {dupes}"

    stats_by_slug: dict[str, dict] = {}
    for brand, items in groups.items():
        slug = slug_of[brand]
        stats = compute_stats(brand, items, colors)
        stats["slug"] = slug
        stats["cat_vector"] = [stats["cat_shares"][c] for c in CATEGORIES]
        stats["color_vector"] = [stats["color_shares"][c] for c in colors]
        stats_by_slug[slug] = stats

    # Display order for brands/index.html: the live page's original ordering
    # convention could not be inferred from the data (it is neither
    # alphabetical nor monotonic by piece count -- e.g. on the shipped page
    # "Woodrose Deli" (40 pieces) precedes "Maem Disko" (23) which precedes
    # "Apres Studio" (60)), so we fall back to piece-count desc, then brand
    # name (case-insensitive) asc, as explicitly permitted by spec.
    order = sorted(stats_by_slug.keys(), key=lambda s: (-stats_by_slug[s]["count"], stats_by_slug[s]["brand"].lower()))

    # --- Render brand pages -------------------------------------------------
    planned_files: dict[str, str] = {}
    for slug in order:
        stats = stats_by_slug[slug]
        path = os.path.join(BRANDS_DIR, f"{slug}.html")
        planned_files[path] = render_brand_page(slug, stats, total_brands, stats_by_slug)

    # --- Render index.html ---------------------------------------------------
    index_path = os.path.join(BRANDS_DIR, "index.html")
    planned_files[index_path] = render_index_page(order, stats_by_slug, total_brands, total_pieces)

    # --- Determine stub targets: existing files no longer in the brand set --
    existing_slugs = set()
    if os.path.isdir(BRANDS_DIR):
        for name in os.listdir(BRANDS_DIR):
            if name.endswith(".html") and name != "index.html":
                existing_slugs.add(name[:-len(".html")])
    dead_slugs = sorted(existing_slugs - set(stats_by_slug.keys()))
    stub_paths = []
    for slug in dead_slugs:
        path = os.path.join(BRANDS_DIR, f"{slug}.html")
        planned_files[path] = STUB_HTML
        stub_paths.append(path)

    # --- Banned-word self-check before touching disk ------------------------
    check_banned_words(planned_files)

    # --- Write ---------------------------------------------------------------
    changed_brand_pages = []
    new_count = 0
    changed_count = 0
    for slug in order:
        path = os.path.join(BRANDS_DIR, f"{slug}.html")
        is_new, is_changed = write_if_changed(path, planned_files[path], args.dry_run)
        if is_new:
            new_count += 1
        if is_changed:
            changed_count += 1
            changed_brand_pages.append(slug)

    index_is_new, index_is_changed = write_if_changed(index_path, planned_files[index_path], args.dry_run)

    stubs_written = 0
    for path in stub_paths:
        _, is_changed = write_if_changed(path, planned_files[path], args.dry_run)
        if is_changed:
            stubs_written += 1

    # --- sitemap.xml -----------------------------------------------------------
    with open(SITEMAP_PATH, "r", encoding="utf-8") as f:
        sitemap_raw = f.read()
    brand_slug_pairs = [(stats_by_slug[s]["brand"], s) for s in stats_by_slug]
    new_sitemap = update_sitemap_content(sitemap_raw, brand_slug_pairs)
    check_banned_words({SITEMAP_PATH: new_sitemap})
    sitemap_is_new, sitemap_is_changed = write_if_changed(SITEMAP_PATH, new_sitemap, args.dry_run)

    # --- Summary ---------------------------------------------------------------
    total_bytes = sum(len(c.encode("utf-8")) for c in planned_files.values())

    print(f"catalog products (raw): {len(catalog.get('products', []))}")
    print(f"brands (available, non-retailer): {total_brands}")
    print(f"pieces (available, non-retailer): {total_pieces}")
    print(f"brand pages written/considered: {len(order)} (new: {new_count}, changed: {changed_count})")
    print(f"index.html: new={index_is_new} changed={index_is_changed}")
    print(f"dead slugs found: {len(dead_slugs)} -> stubs changed/written: {stubs_written}")
    if dead_slugs:
        print("  dead slugs: " + ", ".join(dead_slugs))
    print(f"sitemap.xml: new={sitemap_is_new} changed={sitemap_is_changed}")
    print(f"total planned bytes (brands dir content): {total_bytes}")
    if changed_brand_pages:
        print(f"brand pages that changed ({len(changed_brand_pages)}):")
        print("  " + ", ".join(changed_brand_pages))
    else:
        print("no brand pages changed (idempotent run)")
    if args.dry_run:
        print("DRY RUN: no files were written.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
